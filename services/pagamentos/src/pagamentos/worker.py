"""Entrypoint ``worker``: relay do outbox e limpeza das chaves de idempotência expiradas."""

import asyncio
import contextlib

from pagamentos.adaptadores.db.modelos import MensagemOutbox
from pagamentos.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql
from pagamentos.aplicacao.idempotencia import remover_chaves_expiradas
from pagamentos.aplicacao.portas import FabricaUnidadeDeTrabalho, Relogio, UnidadeDeTrabalho
from pagamentos.config import Config
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs, obter_logger
from plataforma.mensageria import PublicadorRabbit, criar_broker
from plataforma.outbox import RelayOutbox
from plataforma.processo import executar_ate_sinal
from plataforma.telemetria import configurar_telemetria, instrumentar_engine
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


async def limpar_periodicamente(
    fabrica_uow: FabricaUnidadeDeTrabalho,
    parar: asyncio.Event,
    *,
    intervalo: float,
    relogio: Relogio = agora_utc,
) -> None:
    while not parar.is_set():
        try:
            removidas = await remover_chaves_expiradas(fabrica_uow, agora=relogio())
            if removidas:
                _log.info("chaves_idempotencia_expiradas_removidas", quantidade=removidas)
        except Exception:
            _log.exception("limpeza_chaves_idempotencia_falhou")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(parar.wait(), timeout=intervalo)


async def executar(config: Config, parar: asyncio.Event) -> None:
    engine = criar_engine(config.database_url)
    instrumentar_engine(engine)
    fabrica_sessoes = criar_fabrica_sessoes(engine)

    def fabrica_uow() -> UnidadeDeTrabalho:
        return UnidadeDeTrabalhoSql(fabrica_sessoes)

    publicador = PublicadorRabbit(
        criar_broker(config.rabbitmq_url, telemetria=config.otel_habilitado)
    )
    await publicador.iniciar()
    relay = RelayOutbox(fabrica_sessoes, MensagemOutbox, publicador)
    try:
        async with asyncio.TaskGroup() as grupo:
            grupo.create_task(relay.executar(parar))
            grupo.create_task(
                limpar_periodicamente(
                    fabrica_uow, parar, intervalo=config.idempotencia_limpeza_intervalo_segundos
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
