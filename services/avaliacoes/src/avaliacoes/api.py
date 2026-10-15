"""Entrypoint ``api``: app FastAPI do serviço de Avaliações."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from avaliacoes.adaptadores.http import rotas_avaliacoes, rotas_disputas
from avaliacoes.composicao import Dependencias, dependencias_reais
from avaliacoes.config import Config
from plataforma.api.app import criar_app_base
from plataforma.api.saude import verificacao_banco, verificacao_broker
from plataforma.auth import VerificadorDeToken, criar_verificador
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs
from plataforma.telemetria import configurar_telemetria, instrumentar_engine

TITULO = "Avaliações"
VERSAO = "0.1.0"
DESCRICAO = "Serviço de Avaliações da Equipe 5 (Financeiro e Pós)."


def criar_app(
    config: Config | None = None,
    *,
    verificador: VerificadorDeToken | None = None,
    dependencias: Dependencias | None = None,
) -> FastAPI:
    """App do serviço. Testes podem injetar ``verificador`` e ``dependencias`` (fakes)."""
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
        try:
            if dependencias is not None:
                app.state.dependencias = dependencias
                yield
            else:
                async with dependencias_reais(config, app.state.fabrica_sessoes) as reais:
                    app.state.dependencias = reais
                    yield
        finally:
            await engine.dispose()

    app = criar_app_base(
        config,
        titulo=TITULO,
        versao=VERSAO,
        descricao=DESCRICAO,
        verificacoes={
            "banco": verificacao_banco(engine),
            "broker": verificacao_broker(config.rabbitmq_url),
        },
        verificador=verificador or criar_verificador(config),
        ciclo_de_vida=ciclo_de_vida,
    )
    app.include_router(rotas_avaliacoes.router)
    app.include_router(rotas_disputas.router)
    return app


def main() -> None:  # pragma: no cover - entrypoint de processo
    uvicorn.run(
        "avaliacoes.api:criar_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - escuta dentro do container
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
        log_config=None,
    )
