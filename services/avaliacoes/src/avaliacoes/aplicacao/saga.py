"""Saga de disputa procedente (orquestração, spec §4.3).

1. ``estorno_pendente`` com commit (feito por ``DecidirDisputa``);
2. ``POST /v1/pagamentos/{id}/estornos`` com ``Idempotency-Key: disputa-{id}``;
3. sucesso → ``resolvida`` + ``disputa.resolvida``;
4. falha transitória → continua pendente; o worker repete com backoff (até o limite);
5. falha definitiva → ``estorno_falhou`` com o código da recusa; tentativas esgotadas com a
   última falha transitória → ``estorno_falhou`` com ``RESULTADO_INCERTO`` (conferir em
   Pagamentos); ambos publicam ``disputa.estorno_falhou``.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from avaliacoes.aplicacao.eventos import (
    DISPUTA_ESTORNO_FALHOU,
    DISPUTA_RESOLVIDA,
    dados_disputa_estorno_falhou,
    dados_disputa_resolvida,
)
from avaliacoes.aplicacao.portas import (
    EmissorDeToken,
    EstornoRealizado,
    FabricaUnidadeDeTrabalho,
    FalhaDefinitiva,
    FalhaTransitoria,
    PortaPagamentos,
    Relogio,
    ResultadoEstorno,
)
from avaliacoes.dominio.disputa import Disputa, StatusDisputa
from avaliacoes.dominio.erros import DisputaNaoEncontrada
from plataforma.correlation import correlation_id_em
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)

# Tentativas esgotadas com a última falha transitória (timeout, 5xx, chave em processamento):
# o estorno pode ter sido feito em Pagamentos; o admin confere lá antes de agir.
MOTIVO_RESULTADO_INCERTO = "RESULTADO_INCERTO"


@dataclass(frozen=True, slots=True)
class PoliticaDeRetentativa:
    max_tentativas: int = 10
    espera_base: timedelta = timedelta(seconds=5)
    espera_maxima: timedelta = timedelta(minutes=5)
    atraso_inicial: timedelta = timedelta(seconds=30)
    reserva: timedelta = timedelta(seconds=60)

    def espera_apos(self, tentativas: int) -> timedelta:
        """Backoff exponencial: base, 2x base, 4x base... limitado a ``espera_maxima``."""
        fator: int = 2 ** max(tentativas - 1, 0)
        return min(self.espera_base * fator, self.espera_maxima)

    def esgotou(self, tentativas: int) -> bool:
        return tentativas >= self.max_tentativas


class SagaEstorno:
    def __init__(
        self,
        uow: FabricaUnidadeDeTrabalho,
        pagamentos: PortaPagamentos,
        emissor_token: EmissorDeToken,
        *,
        politica: PoliticaDeRetentativa | None = None,
        relogio: Relogio = agora_utc,
    ) -> None:
        self._uow = uow
        self._pagamentos = pagamentos
        self._emissor = emissor_token
        self.politica = politica or PoliticaDeRetentativa()
        self._relogio = relogio

    async def tentar(self, disputa_id: uuid.UUID) -> Disputa:
        """Uma tentativa de estorno (passos 2 a 5). Seguro para repetir."""
        async with self._uow() as uow:
            disputa = await uow.disputas.obter(disputa_id)
        if disputa is None:
            raise DisputaNaoEncontrada()
        if disputa.status is not StatusDisputa.ESTORNO_PENDENTE:
            return disputa
        _log.info(
            "estorno_solicitado",
            disputa_id=str(disputa.id),
            pagamento_id=disputa.pagamento_id,
            tentativa=disputa.tentativas_estorno + 1,
        )
        resultado = await self._pagamentos.estornar(
            disputa.pagamento_id,
            valor_centavos=disputa.valor_a_estornar(),
            motivo=disputa.motivo_estorno,
            chave_idempotencia=disputa.chave_idempotencia_estorno,
            token=self._emissor.emitir(),
        )
        return await self._aplicar(disputa_id, resultado)

    async def _aplicar(self, disputa_id: uuid.UUID, resultado: ResultadoEstorno) -> Disputa:
        agora = self._relogio()
        async with self._uow() as uow:
            disputa = await uow.disputas.obter(disputa_id, para_atualizar=True)
            if disputa is None:  # pragma: no cover - disputas não são apagadas
                raise DisputaNaoEncontrada()
            if disputa.status is not StatusDisputa.ESTORNO_PENDENTE:
                _log.info("estorno_ja_concluido", disputa_id=str(disputa_id))
                return disputa
            disputa.contar_tentativa()
            match resultado:
                case EstornoRealizado(estorno_id=estorno_id):
                    disputa.concluir_estorno(estorno_id=estorno_id, agora=agora)
                    uow.registrar_evento(DISPUTA_RESOLVIDA, dados_disputa_resolvida(disputa))
                case FalhaDefinitiva(motivo=motivo):
                    disputa.falhar_estorno(motivo=motivo, agora=agora)
                    uow.registrar_evento(
                        DISPUTA_ESTORNO_FALHOU, dados_disputa_estorno_falhou(disputa)
                    )
                case FalhaTransitoria() if self.politica.esgotou(disputa.tentativas_estorno):
                    disputa.falhar_estorno(motivo=MOTIVO_RESULTADO_INCERTO, agora=agora)
                    uow.registrar_evento(
                        DISPUTA_ESTORNO_FALHOU, dados_disputa_estorno_falhou(disputa)
                    )
                case FalhaTransitoria():
                    disputa.adiar_estorno(
                        proxima_tentativa_em=agora
                        + self.politica.espera_apos(disputa.tentativas_estorno),
                        agora=agora,
                    )
            await uow.disputas.salvar(disputa)
            await uow.commit()
        _log.info(
            "estorno_processado",
            disputa_id=str(disputa.id),
            resultado=type(resultado).__name__,
            motivo=getattr(resultado, "motivo", None),
            status=disputa.status.value,
            tentativas=disputa.tentativas_estorno,
        )
        return disputa


class RetentativaDeEstornos:
    """Usada pelo worker: repete as sagas pendentes cujo horário chegou."""

    def __init__(
        self,
        uow: FabricaUnidadeDeTrabalho,
        saga: SagaEstorno,
        *,
        tamanho_lote: int = 10,
        relogio: Relogio = agora_utc,
    ) -> None:
        self._uow = uow
        self._saga = saga
        self._tamanho_lote = tamanho_lote
        self._relogio = relogio

    async def processar_lote(self) -> int:
        """Reserva um lote, tenta cada disputa e devolve quantas foram processadas."""
        agora = self._relogio()
        async with self._uow() as uow:
            ids = await uow.disputas.reservar_para_retentativa(
                agora=agora,
                reservar_ate=agora + self._saga.politica.reserva,
                limite=self._tamanho_lote,
            )
            await uow.commit()
        for disputa_id in ids:
            with correlation_id_em(f"disputa-{disputa_id}"):
                try:
                    await self._saga.tentar(disputa_id)
                except Exception:
                    _log.exception("retentativa_estorno_falhou", disputa_id=str(disputa_id))
        return len(ids)
