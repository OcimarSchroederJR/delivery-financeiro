"""RabbitMQ via FastStream: exchange de eventos, broker e publicador do relay."""

from typing import Any

from faststream.rabbit import Channel, ExchangeType, RabbitBroker, RabbitExchange
from faststream.rabbit.opentelemetry import RabbitTelemetryMiddleware

from plataforma.correlation import HEADER_CORRELATION_ID
from plataforma.envelope import EnvelopeEvento

NOME_EXCHANGE_EVENTOS = "financeiro.eventos"
EXCHANGE_EVENTOS = RabbitExchange(NOME_EXCHANGE_EVENTOS, type=ExchangeType.TOPIC, durable=True)
URL_BROKER_ESPECIFICACAO = "amqp://rabbitmq:5672/"


def criar_broker(url: str, *, telemetria: bool = False, **opcoes: Any) -> RabbitBroker:
    """Broker FastStream. Com ``telemetria=True``, propaga trace pelos headers AMQP.

    O canal padrão usa publisher confirms e ``on_return_raises``: uma mensagem
    ``mandatory`` sem fila ligada levanta ``DeliveryError`` em vez de sumir.
    """
    middlewares = (RabbitTelemetryMiddleware(),) if telemetria else ()
    opcoes.setdefault("default_channel", Channel(publisher_confirms=True, on_return_raises=True))
    return RabbitBroker(url, middlewares=middlewares, **opcoes)


def criar_broker_especificacao(descricao: str | None = None) -> RabbitBroker:
    """Broker só para gerar o AsyncAPI (não conecta; URL fixa, sem credenciais)."""
    return RabbitBroker(
        URL_BROKER_ESPECIFICACAO,
        specification_url=URL_BROKER_ESPECIFICACAO,
        description=descricao,
    )


class PublicadorRabbit:
    """Implementa ``plataforma.outbox.Publicador`` no exchange topic de eventos."""

    def __init__(
        self, broker: RabbitBroker, *, exchange: RabbitExchange = EXCHANGE_EVENTOS
    ) -> None:
        self._broker = broker
        self._exchange = exchange

    async def iniciar(self) -> None:
        await self._broker.connect()
        await self._broker.declare_exchange(self._exchange)

    async def publicar(self, envelope: EnvelopeEvento) -> None:
        await self._broker.publish(
            envelope.para_json(),
            exchange=self._exchange,
            routing_key=envelope.tipo,
            message_id=str(envelope.mensagem_id),
            correlation_id=envelope.correlation_id,
            headers={HEADER_CORRELATION_ID: envelope.correlation_id},
            persist=True,
            mandatory=True,
        )

    async def encerrar(self) -> None:
        await self._broker.stop()
