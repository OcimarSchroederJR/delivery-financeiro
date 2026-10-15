"""Execução idempotente de operações com efeito financeiro (spec §4.1, regra 6).

1. Valida o header (400 se ausente ou fora do formato).
2. Reserva a chave em transação própria, protegida pela PK (escopo, chave):
   concorrente -> 409; corpo diferente -> 422; concluída -> devolve a resposta gravada.
3. Executa a operação. Quem muda estado conclui a chave **na mesma transação**
   do efeito (ver ``ReservaIdempotencia``).
4. Erro 4xx: grava a resposta de erro. 5xx ou exceção inesperada: remove a chave,
   e o cliente pode repetir com a mesma chave, **desde que o efeito não tenha sido
   commitado**: se a operação já concluiu a chave (efeito gravado) e falhou depois,
   a chave fica e a repetição devolve a resposta gravada, sem refazer o efeito.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pagamentos.aplicacao.portas import Apresentador, FabricaUnidadeDeTrabalho, Relogio
from pagamentos.dominio.erros import IdempotencyEmProcessamento, IdempotencyKeyReutilizada
from pagamentos.dominio.idempotencia import (
    VALIDADE,
    Decisao,
    RegistroIdempotencia,
    calcular_hash,
    validar_chave,
)
from plataforma.erros import ErroAplicacao
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReservaIdempotencia:
    """Chave reservada. A operação a conclui com ``uow.chaves_idempotencia.concluir``."""

    escopo: str
    chave: str


@dataclass(frozen=True, slots=True)
class RespostaGravada:
    status: int
    corpo: dict[str, Any]


class ExecutorIdempotente:
    def __init__(
        self,
        fabrica_uow: FabricaUnidadeDeTrabalho,
        apresentador: Apresentador,
        *,
        chave_hash: bytes,
        relogio: Relogio = agora_utc,
    ) -> None:
        self._fabrica_uow = fabrica_uow
        self._apresentador = apresentador
        self._chave_hash = chave_hash
        self._relogio = relogio

    async def executar[T](
        self,
        *,
        chave: str | None,
        escopo: str,
        dados: Mapping[str, Any],
        operacao: Callable[[ReservaIdempotencia], Awaitable[T]],
    ) -> T | RespostaGravada:
        reserva = ReservaIdempotencia(escopo=escopo, chave=validar_chave(chave))
        gravada = await self._reservar(reserva, calcular_hash(dados, chave=self._chave_hash))
        if gravada is not None:
            _log.info(
                "idempotencia_resposta_repetida",
                escopo=escopo,
                chave=reserva.chave,
                status=gravada.status,
            )
            return gravada
        try:
            return await operacao(reserva)
        except ErroAplicacao as erro:
            if erro.status_http >= 500:
                await self._liberar(reserva)
            else:
                await self._concluir_com_erro(reserva, erro)
            raise
        except Exception:
            await self._liberar(reserva)
            raise

    async def _reservar(
        self, reserva: ReservaIdempotencia, hash_requisicao: str
    ) -> RespostaGravada | None:
        agora = self._relogio()
        nova = RegistroIdempotencia.reservar(
            escopo=reserva.escopo, chave=reserva.chave, hash_requisicao=hash_requisicao, agora=agora
        )
        async with self._fabrica_uow() as uow:
            existente = await uow.chaves_idempotencia.obter(
                reserva.escopo, reserva.chave, para_atualizar=True
            )
            if existente is None:
                await uow.chaves_idempotencia.reservar(nova)
            else:
                decisao = existente.decidir(hash_requisicao, agora)
                if decisao is Decisao.REPETIR_RESPOSTA:
                    status, corpo = existente.resposta()
                    return RespostaGravada(status=status, corpo=corpo)
                if decisao is Decisao.CORPO_DIFERENTE:
                    raise IdempotencyKeyReutilizada()
                if decisao is Decisao.EM_PROCESSAMENTO:
                    raise IdempotencyEmProcessamento()
                await uow.chaves_idempotencia.substituir(nova)
            await uow.commit()
        return None

    async def _concluir_com_erro(self, reserva: ReservaIdempotencia, erro: ErroAplicacao) -> None:
        try:
            async with self._fabrica_uow() as uow:
                await uow.chaves_idempotencia.concluir(
                    reserva.escopo,
                    reserva.chave,
                    status_resposta=erro.status_http,
                    corpo_resposta=self._apresentador.erro(erro),
                )
                await uow.commit()
        except Exception:
            # A chave fica em processamento e é reassumida depois de 60 s.
            _log.warning(
                "idempotencia_conclusao_falhou", escopo=reserva.escopo, chave=reserva.chave
            )

    async def _liberar(self, reserva: ReservaIdempotencia) -> None:
        try:
            async with self._fabrica_uow() as uow:
                # Só remove se ainda estiver em processamento (efeito não commitado).
                await uow.chaves_idempotencia.remover(reserva.escopo, reserva.chave)
                await uow.commit()
        except Exception:
            _log.warning(
                "idempotencia_liberacao_falhou", escopo=reserva.escopo, chave=reserva.chave
            )


async def remover_chaves_expiradas(
    fabrica_uow: FabricaUnidadeDeTrabalho, *, agora: datetime
) -> int:
    """Apaga as chaves com mais de 24 h (``VALIDADE``). Usado pelo worker."""
    async with fabrica_uow() as uow:
        removidas = await uow.chaves_idempotencia.remover_expiradas(agora - VALIDADE)
        await uow.commit()
    return removidas
