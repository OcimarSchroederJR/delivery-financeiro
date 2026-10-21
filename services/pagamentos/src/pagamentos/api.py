"""Entrypoint ``api``: app FastAPI do serviço de Pagamentos."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import uvicorn
from fastapi import FastAPI

from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.adaptadores.clientes.pedidos import ClientePedidosHttp
from pagamentos.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql
from pagamentos.adaptadores.http.apresentador import ApresentadorHttp
from pagamentos.adaptadores.http.rotas import router
from pagamentos.aplicacao.portas import (
    ConsultaPedidos,
    FabricaUnidadeDeTrabalho,
    GatewayDePagamento,
    UnidadeDeTrabalho,
)
from pagamentos.composicao import montar_casos_de_uso
from pagamentos.config import Config
from plataforma.api.app import criar_app_base
from plataforma.api.saude import verificacao_banco, verificacao_broker
from plataforma.auth import VerificadorDeToken, criar_verificador
from plataforma.cliente_http import ClienteHttp
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.logs import configurar_logs
from plataforma.telemetria import configurar_telemetria, instrumentar_engine

TITULO = "Pagamentos"
VERSAO = "0.2.0"
DESCRICAO = (
    "Serviço de Pagamentos da Equipe 5 (Financeiro e Pós): autorização de pagamentos "
    "de pedidos, estornos e eventos pagamento.aprovado|recusado|estornado."
)


@dataclass(frozen=True, slots=True)
class Substituicoes:
    """Pontos de injeção para testes. ``None`` = implementação real."""

    verificador: VerificadorDeToken | None = None
    pedidos: ConsultaPedidos | None = None
    transporte_pedidos: httpx.AsyncBaseTransport | None = None
    gateway: GatewayDePagamento | None = None
    fabrica_uow: FabricaUnidadeDeTrabalho | None = None


def criar_app(config: Config | None = None, substituicoes: Substituicoes | None = None) -> FastAPI:
    config = config or Config()
    trocas = substituicoes or Substituicoes()
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
        fabrica_sessoes = criar_fabrica_sessoes(engine)
        cliente_pedidos = ClienteHttp(
            "pedidos",
            config.pedidos_url,
            timeout=config.timeout_http(),
            transporte=trocas.transporte_pedidos,
        )

        def fabrica_sql() -> UnidadeDeTrabalho:
            return UnidadeDeTrabalhoSql(fabrica_sessoes)

        app.state.config = config
        app.state.fabrica_sessoes = fabrica_sessoes
        app.state.casos_de_uso = montar_casos_de_uso(
            fabrica_uow=trocas.fabrica_uow or fabrica_sql,
            pedidos=trocas.pedidos or ClientePedidosHttp(cliente_pedidos),
            gateway=trocas.gateway
            or GatewaySimulado(atraso_timeout=config.gateway_atraso_timeout_segundos),
            apresentador=ApresentadorHttp(),
            segredo=config.token_servico_segredo.get_secret_value(),
        )
        try:
            yield
        finally:
            await cliente_pedidos.fechar()
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
        verificador=trocas.verificador or criar_verificador(config),
        ciclo_de_vida=ciclo_de_vida,
    )
    app.include_router(router)
    return app


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
