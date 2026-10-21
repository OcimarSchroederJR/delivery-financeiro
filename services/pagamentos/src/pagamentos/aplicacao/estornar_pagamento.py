"""Caso de uso: estornar (total ou parcialmente) um pagamento (spec §4.1)."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from pagamentos.aplicacao.idempotencia import ReservaIdempotencia
from pagamentos.aplicacao.portas import (
    Apresentador,
    FabricaUnidadeDeTrabalho,
    GeradorDeId,
    Relogio,
)
from pagamentos.dominio.erros import PagamentoNaoEncontrado
from pagamentos.dominio.eventos import TIPO_PAGAMENTO_ESTORNADO, dados_pagamento_estornado
from pagamentos.dominio.pagamento import Estorno, StatusPagamento
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


@dataclass(frozen=True, slots=True)
class ComandoEstornar:
    pagamento_id: UUID
    motivo: str
    valor_centavos: int | None = None


@dataclass(frozen=True, slots=True)
class ResultadoEstorno:
    estorno: Estorno
    status_pagamento: StatusPagamento


class EstornarPagamento:
    def __init__(
        self,
        *,
        fabrica_uow: FabricaUnidadeDeTrabalho,
        apresentador: Apresentador,
        relogio: Relogio = agora_utc,
        gerar_id: GeradorDeId = uuid4,
    ) -> None:
        self._fabrica_uow = fabrica_uow
        self._apresentador = apresentador
        self._relogio = relogio
        self._gerar_id = gerar_id

    async def executar(
        self, comando: ComandoEstornar, reserva: ReservaIdempotencia | None = None
    ) -> ResultadoEstorno:
        async with self._fabrica_uow() as uow:
            # A trava serializa estornos concorrentes do mesmo pagamento (saldo correto).
            pagamento = await uow.pagamentos.obter(comando.pagamento_id, para_atualizar=True)
            if pagamento is None:
                raise PagamentoNaoEncontrado()
            estorno = pagamento.estornar(
                valor_centavos=comando.valor_centavos,
                motivo=comando.motivo,
                estorno_id=self._gerar_id(),
                agora=self._relogio(),
            )
            await uow.pagamentos.salvar(pagamento)
            uow.eventos.registrar(
                TIPO_PAGAMENTO_ESTORNADO, dados_pagamento_estornado(pagamento, estorno)
            )
            if reserva is not None:
                await uow.chaves_idempotencia.concluir(
                    reserva.escopo,
                    reserva.chave,
                    status_resposta=201,
                    corpo_resposta=self._apresentador.estorno(estorno, pagamento.status),
                )
            await uow.commit()
        _log.info(
            "estorno_registrado",
            pagamento_id=str(pagamento.id),
            estorno_id=str(estorno.id),
            valor_centavos=estorno.valor_centavos,
            status_pagamento=pagamento.status.value,
        )
        return ResultadoEstorno(estorno=estorno, status_pagamento=pagamento.status)
