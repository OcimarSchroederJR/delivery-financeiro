"""Consumidores FastStream com ack manual (spec §3.3, §4.2 e §5).

Com ``AckPolicy.MANUAL`` uma exceção que escapa do handler deixa a mensagem
presa sem ack (verificado). Por isso cada handler termina sempre em
exatamente uma ação: ``ack`` (depois do commit, ou depois de republicar na
fila de retry ou na DLQ), ``reject(requeue=False)`` (malformada → DLQ) ou
``nack(requeue=True)`` (só quando nem a republicação funcionou: broker fora).

Exceção inesperada (bug, dado que o banco recusa, banco fora) não volta para
a fila com ``requeue``: isso repetiria uma mensagem envenenada para sempre. Ela
vai para ``<fila>.retry.N`` com o contador ``x-falhas-inesperadas`` e, passado
o limite (uma por fila de retry), para a DLQ.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from faststream import AckPolicy
from faststream.rabbit import Channel, RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError

from notificacoes.adaptadores.mensageria.topologia import (
    FILA_EMAILS,
    FILA_EVENTOS,
    FILA_WEBHOOKS,
    HEADER_FALHAS_INESPERADAS,
    fila_de_tarefas,
    fila_eventos,
)
from notificacoes.aplicacao.tarefas import Desfecho, Tarefa, TipoDesfecho
from plataforma.correlation import HEADER_CORRELATION_ID, correlation_id_em
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger
from plataforma.mensageria import EXCHANGE_EVENTOS

_log = obter_logger(__name__)

ProcessadorDeEvento = Callable[[EnvelopeEvento], Awaitable[object]]
ProcessadorDeTarefa = Callable[[Tarefa], Awaitable[Desfecho]]


class Confirmacao(Protocol):
    async def ack(self) -> None: ...

    async def nack(self, *, requeue: bool = True) -> None: ...

    async def reject(self, *, requeue: bool = False) -> None: ...


class Encaminhador(Protocol):
    async def reagendar(
        self, fila: str, numero: int, corpo: bytes, cabecalhos: Mapping[str, Any]
    ) -> None: ...

    async def enviar_para_dlq(
        self, fila: str, corpo: bytes, cabecalhos: Mapping[str, Any], motivo: str
    ) -> None: ...


def _correlation_dos_cabecalhos(cabecalhos: Mapping[str, Any]) -> str | None:
    valor = cabecalhos.get(HEADER_CORRELATION_ID)
    return None if valor is None else str(valor)


def _falhas_anteriores(cabecalhos: Mapping[str, Any]) -> int:
    valor = cabecalhos.get(HEADER_FALHAS_INESPERADAS)
    return valor if isinstance(valor, int) and valor > 0 else 0


async def _tratar_falha_inesperada(
    erro: Exception,
    corpo: bytes,
    cabecalhos: Mapping[str, Any],
    confirmacao: Confirmacao,
    encaminhador: Encaminhador,
    *,
    fila: str,
    max_falhas: int,
    pausa_em_erro: float,
) -> None:
    """Retry com TTL até ``max_falhas``; depois, DLQ. Nunca ``requeue`` infinito."""
    falhas = _falhas_anteriores(cabecalhos) + 1
    try:
        if falhas <= max_falhas:
            await encaminhador.reagendar(
                fila, falhas, corpo, {**cabecalhos, HEADER_FALHAS_INESPERADAS: falhas}
            )
            _log.warning(
                "mensagem_reagendada_apos_erro",
                fila=fila,
                falhas=falhas,
                erro=type(erro).__name__,
            )
        else:
            motivo = f"Falha inesperada repetida {falhas} vezes: {type(erro).__name__}"
            await encaminhador.enviar_para_dlq(fila, corpo, cabecalhos, motivo)
            _log.error("mensagem_enviada_para_dlq", fila=fila, motivo=motivo)
    except Exception:
        _log.exception("republicacao_falhou", fila=fila)
        await asyncio.sleep(pausa_em_erro)
        await confirmacao.nack(requeue=True)
        return
    await confirmacao.ack()


async def tratar_evento(
    corpo: bytes,
    cabecalhos: Mapping[str, Any],
    confirmacao: Confirmacao,
    processar: ProcessadorDeEvento,
    encaminhador: Encaminhador,
    *,
    max_falhas: int,
    pausa_em_erro: float = 1.0,
) -> None:
    try:
        envelope = EnvelopeEvento.model_validate_json(corpo)
    except ValidationError:
        with correlation_id_em(_correlation_dos_cabecalhos(cabecalhos)):
            _log.warning("evento_invalido_descartado", fila=FILA_EVENTOS)
        await confirmacao.reject(requeue=False)
        return
    with correlation_id_em(envelope.correlation_id):
        try:
            await processar(envelope)
        except Exception as erro:
            _log.exception(
                "processamento_de_evento_falhou",
                tipo=envelope.tipo,
                mensagem_id=str(envelope.mensagem_id),
            )
            await _tratar_falha_inesperada(
                erro,
                corpo,
                cabecalhos,
                confirmacao,
                encaminhador,
                fila=FILA_EVENTOS,
                max_falhas=max_falhas,
                pausa_em_erro=pausa_em_erro,
            )
            return
        await confirmacao.ack()


async def tratar_tarefa(
    corpo: bytes,
    cabecalhos: Mapping[str, Any],
    confirmacao: Confirmacao,
    processar: ProcessadorDeTarefa,
    encaminhador: Encaminhador,
    *,
    fila: str,
    max_falhas: int,
    pausa_em_erro: float = 1.0,
) -> None:
    try:
        tarefa = Tarefa.de_envelope(EnvelopeEvento.model_validate_json(corpo))
    except ValueError:  # ValidationError é ValueError
        with correlation_id_em(_correlation_dos_cabecalhos(cabecalhos)):
            _log.warning("tarefa_invalida_descartada", fila=fila)
        await confirmacao.reject(requeue=False)
        return
    with correlation_id_em(tarefa.evento.correlation_id):
        try:
            desfecho = await processar(tarefa)
        except Exception as erro:
            _log.exception(
                "processamento_de_tarefa_falhou",
                fila=fila,
                notificacao_id=str(tarefa.notificacao_id),
            )
            await _tratar_falha_inesperada(
                erro,
                corpo,
                cabecalhos,
                confirmacao,
                encaminhador,
                fila=fila,
                max_falhas=max_falhas,
                pausa_em_erro=pausa_em_erro,
            )
            return
        try:
            if desfecho.tipo is TipoDesfecho.REPETIR and desfecho.retentativa is not None:
                await encaminhador.reagendar(fila, desfecho.retentativa, corpo, cabecalhos)
                _log.info(
                    "tarefa_reagendada",
                    fila=fila,
                    retentativa=desfecho.retentativa,
                    notificacao_id=str(tarefa.notificacao_id),
                )
            elif desfecho.tipo is TipoDesfecho.DESISTIR:
                await encaminhador.enviar_para_dlq(
                    fila, corpo, cabecalhos, desfecho.motivo or "falha"
                )
                _log.warning(
                    "tarefa_enviada_para_dlq",
                    fila=fila,
                    notificacao_id=str(tarefa.notificacao_id),
                    motivo=desfecho.motivo,
                )
        except Exception:
            # O efeito já foi gravado; só a republicação falhou (broker fora).
            _log.exception(
                "republicacao_de_tarefa_falhou",
                fila=fila,
                notificacao_id=str(tarefa.notificacao_id),
            )
            await asyncio.sleep(pausa_em_erro)
            await confirmacao.nack(requeue=True)
            return
        await confirmacao.ack()


@dataclass(frozen=True, slots=True)
class Processadores:
    distribuir: ProcessadorDeEvento
    enviar_email: ProcessadorDeTarefa
    entregar_webhook: ProcessadorDeTarefa


def registrar_consumidores(
    broker: RabbitBroker,
    processadores: Processadores,
    encaminhador: Encaminhador,
    *,
    max_falhas: int,
    prefetch: int,
    pausa_em_erro: float = 1.0,
) -> None:
    """Cada fila tem canal próprio com ``prefetch``: até ``prefetch`` mensagens em
    paralelo por fila (um webhook lento não segura os outros) e nunca um número
    ilimitado (o que esgotaria as conexões do banco)."""

    def canal() -> Channel:
        return Channel(prefetch_count=prefetch)

    @broker.subscriber(
        fila_eventos(),
        EXCHANGE_EVENTOS,
        channel=canal(),
        ack_policy=AckPolicy.MANUAL,
        title=FILA_EVENTOS,
    )
    async def consumir_evento(mensagem: RabbitMessage) -> None:
        await tratar_evento(
            bytes(mensagem.body),
            mensagem.headers,
            mensagem,
            processadores.distribuir,
            encaminhador,
            max_falhas=max_falhas,
            pausa_em_erro=pausa_em_erro,
        )

    @broker.subscriber(
        fila_de_tarefas(FILA_EMAILS),
        channel=canal(),
        ack_policy=AckPolicy.MANUAL,
        title=FILA_EMAILS,
    )
    async def consumir_email(mensagem: RabbitMessage) -> None:
        await tratar_tarefa(
            bytes(mensagem.body),
            mensagem.headers,
            mensagem,
            processadores.enviar_email,
            encaminhador,
            fila=FILA_EMAILS,
            max_falhas=max_falhas,
            pausa_em_erro=pausa_em_erro,
        )

    @broker.subscriber(
        fila_de_tarefas(FILA_WEBHOOKS),
        channel=canal(),
        ack_policy=AckPolicy.MANUAL,
        title=FILA_WEBHOOKS,
    )
    async def consumir_webhook(mensagem: RabbitMessage) -> None:
        await tratar_tarefa(
            bytes(mensagem.body),
            mensagem.headers,
            mensagem,
            processadores.entregar_webhook,
            encaminhador,
            fila=FILA_WEBHOOKS,
            max_falhas=max_falhas,
            pausa_em_erro=pausa_em_erro,
        )
