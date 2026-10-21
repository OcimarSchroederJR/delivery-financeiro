"""Documentação AsyncAPI dos eventos do serviço.

A publicação real é feita pelo relay do outbox (worker); aqui só declaramos os
canais para gerar ``docs/asyncapi/pagamentos.json``.
"""

from faststream.rabbit import RabbitBroker

from pagamentos.adaptadores.mensageria.esquemas import EVENTOS_PUBLICADOS
from plataforma.mensageria import EXCHANGE_EVENTOS, criar_broker_especificacao


def criar_broker_documentado() -> RabbitBroker:
    broker = criar_broker_especificacao(
        "Eventos do serviço de Pagamentos (exchange financeiro.eventos; routing key = tipo)."
    )
    for tipo, evento in EVENTOS_PUBLICADOS.items():
        broker.publisher(
            routing_key=tipo,
            exchange=EXCHANGE_EVENTOS,
            title=tipo,
            description=evento.descricao,
            schema=evento.envelope,
        )
    return broker
