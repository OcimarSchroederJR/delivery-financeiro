"""Documentação AsyncAPI: o que Notificações consome, publica e reenfileira.

Só gera ``docs/asyncapi/notificacoes.json``; o consumo real está em
``consumidores.py`` e a publicação real é feita pelos relays dos outboxes.
"""

import uuid
from typing import Literal

from faststream.rabbit import RabbitBroker
from pydantic import BaseModel

from notificacoes.adaptadores.mensageria.topologia import (
    FILA_DLQ,
    FILA_EMAILS,
    FILA_EVENTOS,
    FILA_WEBHOOKS,
    fila_de_tarefas,
    fila_dlq,
    fila_eventos,
    filas_retry,
)
from notificacoes.config import TTLS_RETRY_PADRAO_MS
from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import EXCHANGE_EVENTOS, criar_broker_especificacao
from plataforma.tempo import DataHoraUTC


class DadosTarefa(BaseModel):
    notificacao_id: uuid.UUID
    evento: EnvelopeEvento


class EnvelopeTarefa(BaseModel):
    """Envelope interno de tarefa (``tarefa.email`` ou ``tarefa.webhook``)."""

    mensagem_id: uuid.UUID
    tipo: Literal["tarefa.email", "tarefa.webhook"]
    versao: int = 1
    ocorrido_em: DataHoraUTC
    correlation_id: str
    dados: DadosTarefa


def criar_broker_documentado() -> RabbitBroker:
    broker = criar_broker_especificacao(
        "Notificações: consome todos os eventos de financeiro.eventos (bind #), envia "
        "e-mails e webhooks assinados com HMAC, com retry por TTL (1 s, 5 s, 30 s, 2 min, "
        "10 min) e DLQ, e republica os eventos externos recebidos em POST /v1/eventos."
    )

    @broker.subscriber(
        fila_eventos(),
        EXCHANGE_EVENTOS,
        title=FILA_EVENTOS,
        description="Todos os eventos (bind #). Inbox por mensagem_id; ack depois do commit. "
        "Mensagem inválida vai para notificacoes.dlq.",
    )
    async def consumir_eventos(envelope: EnvelopeEvento) -> None: ...

    @broker.subscriber(
        fila_de_tarefas(FILA_EMAILS),
        title=FILA_EMAILS,
        description="Tarefas de e-mail: busca o perfil na Eq. 1 (cache de 5 min) e envia por SMTP.",
    )
    async def consumir_emails(tarefa: EnvelopeTarefa) -> None: ...

    @broker.subscriber(
        fila_de_tarefas(FILA_WEBHOOKS),
        title=FILA_WEBHOOKS,
        description="Tarefas de webhook: POST com X-Assinatura, X-Assinatura-Timestamp, "
        "X-Evento-Id e X-Evento-Tipo; sucesso = 2xx em até 5 s.",
    )
    async def consumir_webhooks(tarefa: EnvelopeTarefa) -> None: ...

    broker.publisher(
        routing_key="{tipo}",
        exchange=EXCHANGE_EVENTOS,
        title="financeiro.eventos (eventos externos)",
        schema=EnvelopeEvento,
        description="Eventos recebidos em POST /v1/eventos (ex.: pedido.*, entrega.*), "
        "republicados pelo outbox com routing key = tipo.",
    )
    for fila in (FILA_EMAILS, FILA_WEBHOOKS):
        for numero, (fila_retry, ttl) in enumerate(
            zip(filas_retry(fila, TTLS_RETRY_PADRAO_MS), TTLS_RETRY_PADRAO_MS, strict=True),
            start=1,
        ):
            broker.publisher(
                queue=fila_retry,
                title=fila_retry.name,
                schema=EnvelopeTarefa,
                description=(
                    f"Retentativa {numero}: TTL de {ttl} ms; ao expirar, volta para {fila}."
                ),
            )
    broker.publisher(
        queue=fila_dlq(),
        title=FILA_DLQ,
        schema=EnvelopeTarefa,
        description="Tarefas que esgotaram as 5 retentativas ou falharam de forma definitiva "
        "(headers x-fila-origem e x-motivo) e mensagens inválidas.",
    )
    return broker
