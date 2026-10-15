"""Filas do serviço (spec §4.2).

- ``notificacoes.eventos``: bind ``#`` em ``financeiro.eventos``.
- ``notificacoes.emails`` / ``notificacoes.webhooks``: tarefas de entrega.
- ``<fila>.retry.N``: TTL por fila; ao expirar, a mensagem volta (dead-letter
  pelo exchange padrão) para ``<fila>``.
- ``notificacoes.dlq``: esgotadas, falhas definitivas e mensagens inválidas
  (as filas principais mandam para cá o que recebe ``reject(requeue=False)``).
"""

from collections.abc import Sequence

from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.schemas.queue import ClassicQueueArgs

from notificacoes.aplicacao.tarefas import TIPO_TAREFA_EMAIL, TIPO_TAREFA_WEBHOOK
from plataforma.mensageria import EXCHANGE_EVENTOS

FILA_EVENTOS = "notificacoes.eventos"
FILA_EMAILS = "notificacoes.emails"
FILA_WEBHOOKS = "notificacoes.webhooks"
FILA_DLQ = "notificacoes.dlq"
FILAS_DE_TAREFA = {TIPO_TAREFA_EMAIL: FILA_EMAILS, TIPO_TAREFA_WEBHOOK: FILA_WEBHOOKS}


def _rejeitadas_para_dlq() -> ClassicQueueArgs:
    return {"x-dead-letter-exchange": "", "x-dead-letter-routing-key": FILA_DLQ}


def fila_eventos() -> RabbitQueue:
    return RabbitQueue(
        FILA_EVENTOS, durable=True, routing_key="#", arguments=_rejeitadas_para_dlq()
    )


def fila_de_tarefas(nome: str) -> RabbitQueue:
    return RabbitQueue(nome, durable=True, arguments=_rejeitadas_para_dlq())


def nome_fila_retry(fila: str, numero: int) -> str:
    return f"{fila}.retry.{numero}"


def filas_retry(fila: str, ttls_ms: Sequence[int]) -> list[RabbitQueue]:
    return [
        RabbitQueue(
            nome_fila_retry(fila, numero),
            durable=True,
            arguments={
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": fila,
            },
        )
        for numero, ttl in enumerate(ttls_ms, start=1)
    ]


def fila_dlq() -> RabbitQueue:
    return RabbitQueue(FILA_DLQ, durable=True)


async def declarar_topologia(broker: RabbitBroker, ttls_ms: Sequence[int]) -> None:
    """Declara tudo o que o serviço usa. Chame depois de ``connect()`` e antes de ``start()``.

    Inclui a fila ``notificacoes.eventos`` **já ligada** (bind ``#``) ao
    ``financeiro.eventos``: o relay do outbox da plataforma publica com
    ``mandatory`` e deixa pendente o evento que não tem fila ligada, então a fila
    precisa existir antes de qualquer relay (nosso ou de Pagamentos/Avaliações)
    publicar. Como é durável, depois da primeira subida ela continua lá.

    Atenção: o RabbitMQ recusa redeclarar uma fila com argumentos diferentes
    (``PRECONDITION_FAILED``). Para mudar os TTLs, apague as filas de retry antes.
    """
    await broker.declare_queue(fila_dlq())
    exchange = await broker.declare_exchange(EXCHANGE_EVENTOS)
    eventos = await broker.declare_queue(fila_eventos())
    await eventos.bind(exchange, routing_key="#")
    for fila in (FILA_EMAILS, FILA_WEBHOOKS):
        await broker.declare_queue(fila_de_tarefas(fila))
        for fila_retry in filas_retry(fila, ttls_ms):
            await broker.declare_queue(fila_retry)
