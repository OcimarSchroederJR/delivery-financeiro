"""Entrypoint ``worker``: relay do outbox e retentativa da saga de estorno."""

import asyncio
import contextlib

from avaliacoes.adaptadores.db.modelos import MensagemOutbox
from avaliacoes.aplicacao.saga import RetentativaDeEstornos
from avaliacoes.composicao import dependencias_reais
from avaliacoes.config import Config
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs, obter_logger
from plataforma.mensageria import PublicadorRabbit, criar_broker
from plataforma.outbox import RelayOutbox
from plataforma.processo import executar_ate_sinal
from plataforma.telemetria import configurar_telemetria, instrumentar_engine

_log = obter_logger(__name__)


async def executar_retentativas(
    retentativa: RetentativaDeEstornos, parar: asyncio.Event, *, intervalo: float = 1.0
) -> None:
    """Laço da saga: processa lotes; quando não há nada vencido, espera ``intervalo``."""
    _log.info("retentativa_estornos_iniciada")
    while not parar.is_set():
        try:
            processadas = await retentativa.processar_lote()
        except Exception:
            _log.exception("retentativa_estornos_falhou")
            processadas = 0
        if processadas == 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(parar.wait(), timeout=intervalo)
    _log.info("retentativa_estornos_encerrada")


async def executar(config: Config, parar: asyncio.Event) -> None:
    engine = criar_engine(config.database_url)
    instrumentar_engine(engine)
    fabrica = criar_fabrica_sessoes(engine)
    publicador = PublicadorRabbit(
        criar_broker(config.rabbitmq_url, telemetria=config.otel_habilitado)
    )
    await publicador.iniciar()
    relay = RelayOutbox(fabrica, MensagemOutbox, publicador)
    try:
        async with dependencias_reais(config, fabrica) as deps:
            retentativa = RetentativaDeEstornos(
                deps.uow, deps.saga(), tamanho_lote=config.worker_tamanho_lote
            )
            async with asyncio.TaskGroup() as grupo:
                grupo.create_task(relay.executar(parar))
                grupo.create_task(
                    executar_retentativas(
                        retentativa, parar, intervalo=config.worker_intervalo_segundos
                    )
                )
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
