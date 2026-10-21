"""Entrypoint ``worker``: relays dos dois outboxes e consumidores das 3 filas."""

import asyncio

from notificacoes.adaptadores.cifrador import CifradorFernet
from notificacoes.adaptadores.clientes.perfis import ClientePerfisHttp
from notificacoes.adaptadores.clientes.webhook import EntregadorHttpx
from notificacoes.adaptadores.db.modelos import MensagemOutbox, TarefaSaida
from notificacoes.adaptadores.db.uow import fabrica_sql
from notificacoes.adaptadores.email_smtp import EnviadorSmtp
from notificacoes.adaptadores.mensageria.consumidores import Processadores, registrar_consumidores
from notificacoes.adaptadores.mensageria.publicadores import (
    EncaminhadorDeFalhas,
    PublicadorDeTarefas,
)
from notificacoes.adaptadores.mensageria.topologia import declarar_topologia
from notificacoes.aplicacao.distribuicao import DistribuirEvento
from notificacoes.aplicacao.entrega_webhook import EntregarWebhook
from notificacoes.aplicacao.envio_email import EnviarEmail
from notificacoes.config import Config
from plataforma.cliente_http import ClienteHttp
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs, obter_logger
from plataforma.mensageria import PublicadorRabbit, criar_broker
from plataforma.outbox import RelayOutbox
from plataforma.processo import executar_ate_sinal
from plataforma.telemetria import configurar_telemetria, instrumentar_engine

_log = obter_logger(__name__)


async def executar(config: Config, parar: asyncio.Event) -> None:
    engine = criar_engine(config.database_url)
    instrumentar_engine(engine)
    fabrica_sessoes = criar_fabrica_sessoes(engine)
    fabrica_uow = fabrica_sql(
        fabrica_sessoes, CifradorFernet.de_segredo(config.segredo_de_cifragem())
    )
    credencial = (
        config.identidade_credencial.get_secret_value() if config.identidade_credencial else None
    )
    perfis = ClientePerfisHttp(
        ClienteHttp("identidade", config.identidade_url, timeout=config.timeout_http()),
        credencial=credencial,
        ttl_segundos=config.perfis_cache_ttl_segundos,
    )
    entregador = EntregadorHttpx(timeout_segundos=config.webhook_timeout_segundos)
    enviador = EnviadorSmtp(
        host=config.smtp_host,
        porta=config.smtp_porta,
        remetente=config.smtp_remetente,
        timeout_segundos=config.smtp_timeout_segundos,
    )

    broker_publicacao = criar_broker(config.rabbitmq_url, telemetria=config.otel_habilitado)
    publicador_eventos = PublicadorRabbit(broker_publicacao)
    broker_consumo = criar_broker(
        config.rabbitmq_url, telemetria=config.otel_habilitado, graceful_timeout=10.0
    )
    registrar_consumidores(
        broker_consumo,
        Processadores(
            distribuir=DistribuirEvento(fabrica_uow, email_admin=config.email_admin).executar,
            enviar_email=EnviarEmail(
                fabrica_uow, perfis, enviador, max_retentativas=config.max_retentativas
            ).executar,
            entregar_webhook=EntregarWebhook(
                fabrica_uow, entregador, max_retentativas=config.max_retentativas
            ).executar,
        ),
        EncaminhadorDeFalhas(broker_consumo),
        pausa_em_erro=config.consumidor_pausa_em_erro_segundos,
    )
    relays = (
        RelayOutbox(fabrica_sessoes, MensagemOutbox, publicador_eventos),
        RelayOutbox(fabrica_sessoes, TarefaSaida, PublicadorDeTarefas(broker_publicacao)),
    )
    try:
        await publicador_eventos.iniciar()
        await broker_consumo.connect()
        await declarar_topologia(broker_consumo, config.fila_retry_ttls_ms)
        await broker_consumo.start()
        _log.info("consumidores_iniciados", retentativas=config.max_retentativas)
        await asyncio.gather(
            *(relay.executar(parar, intervalo=config.relay_intervalo_segundos) for relay in relays)
        )
    finally:
        await broker_consumo.stop()
        await publicador_eventos.encerrar()
        await perfis.fechar()
        await entregador.fechar()
        await engine.dispose()
        _log.info("worker_encerrado")


def main() -> None:  # pragma: no cover - entrypoint de processo
    config = Config()
    configurar_logs(config.servico, formato=config.log_formato, nivel=config.log_nivel)
    configurar_telemetria(
        config.servico,
        habilitada=config.otel_habilitado,
        endpoint_otlp=config.otel_exporter_otlp_endpoint,
    )
    asyncio.run(executar_ate_sinal(lambda parar: executar(config, parar)))
