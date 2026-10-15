"""Entrypoint ``api``: app FastAPI do serviço de Pagamentos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from pagamentos.config import Config
from plataforma.api.app import criar_app_base
from plataforma.api.saude import verificacao_banco, verificacao_broker
from plataforma.auth import criar_verificador
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs
from plataforma.telemetria import configurar_telemetria, instrumentar_engine

TITULO = "Pagamentos"
VERSAO = "0.1.0"
DESCRICAO = "Serviço de Pagamentos da Equipe 5 (Financeiro e Pós)."


def criar_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    configurar_logs(config.servico, formato=config.log_formato, nivel=config.log_nivel)
    configurar_telemetria(
        config.servico,
        habilitada=config.otel_habilitado,
        endpoint_otlp=config.otel_exporter_otlp_endpoint,
    )
    engine = criar_engine(config.database_url)
    instrumentar_engine(engine)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        app.state.config = config
        app.state.fabrica_sessoes = criar_fabrica_sessoes(engine)
        yield
        await engine.dispose()

    return criar_app_base(
        config,
        titulo=TITULO,
        versao=VERSAO,
        descricao=DESCRICAO,
        verificacoes={
            "banco": verificacao_banco(engine),
            "broker": verificacao_broker(config.rabbitmq_url),
        },
        verificador=criar_verificador(config),
        ciclo_de_vida=ciclo_de_vida,
    )


def main() -> None:  # pragma: no cover - entrypoint de processo
    uvicorn.run(
        "pagamentos.api:criar_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - escuta dentro do container
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
        log_config=None,
    )
