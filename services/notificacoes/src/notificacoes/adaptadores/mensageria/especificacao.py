"""Documentação AsyncAPI dos eventos do serviço.

A publicação real é feita pelo relay do outbox; aqui só declaramos os canais
para gerar ``docs/asyncapi/<servico>.json``. Para cada evento publicado, registre
no broker retornado::

    broker.publisher(
        routing_key=<tipo do evento>,
        exchange=EXCHANGE_EVENTOS,
        title=<tipo do evento>,
        schema=<modelo Pydantic dos dados>,
    )
"""

from faststream.rabbit import RabbitBroker

from plataforma.mensageria import criar_broker_especificacao


def criar_broker_documentado() -> RabbitBroker:
    return criar_broker_especificacao(
        "Eventos do serviço de Notificações (exchange financeiro.eventos)."
    )
