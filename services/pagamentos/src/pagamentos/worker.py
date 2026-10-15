"""Entrypoint ``worker``: relay do outbox do serviço de Pagamentos."""

import asyncio

from pagamentos.adaptadores.db.modelos import MensagemOutbox
from pagamentos.config import Config
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs
from plataforma.mensageria import PublicadorRabbit, criar_broker
from plataforma.outbox import RelayOutbox
from plataforma.processo import executar_ate_sinal
from plataforma.telemetria import configurar_telemetria, instrumentar_engine


async def executar(config: Config, parar: asyncio.Event) -> None:
    engine = criar_engine(config.database_url)
    instrumentar_engine(engine)
    publicador = PublicadorRabbit(
        criar_broker(config.rabbitmq_url, telemetria=config.otel_habilitado)
    )
    await publicador.iniciar()
    relay = RelayOutbox(criar_fabrica_sessoes(engine), MensagemOutbox, publicador)
    try:
        await relay.executar(parar)
    finally:
        await publicador.encerrar()
        await engine.dispose()


def main() -> None:  # pragma: no cover - entrypoint de processo
    config = Config()
    configurar_logs(config.servico, formato=config.log_formato, nivel=config.log_nivel)
    configurar_telemetria(
        config.servico,
        habilitada=config.otel_habilitado,
        endpoint_otlp=config.otel_exporter_otlp_endpoint,
    )
    asyncio.run(executar_ate_sinal(lambda parar: executar(config, parar)))
