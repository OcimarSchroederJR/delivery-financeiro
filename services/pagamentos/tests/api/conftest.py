from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager

from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.api import Substituicoes, criar_app
from pagamentos.aplicacao.portas import GatewayDePagamento
from pagamentos.config import Config
from pagamentos.testes.fakes import ConsultaPedidosFake, EstadoFake, fabrica_fake
from pagamentos.testes.requisicoes import verificador_de_teste


@pytest.fixture
def estado() -> EstadoFake:
    return EstadoFake()


@pytest.fixture
def pedidos() -> ConsultaPedidosFake:
    return ConsultaPedidosFake()


@pytest.fixture
def gateway() -> GatewayDePagamento:
    """Sobrescreva esta fixture num módulo de teste para trocar o gateway."""
    return GatewaySimulado()


@pytest.fixture
async def api(
    config: Config,
    estado: EstadoFake,
    pedidos: ConsultaPedidosFake,
    gateway: GatewayDePagamento,
) -> AsyncIterator[httpx.AsyncClient]:
    substituicoes = Substituicoes(
        verificador=verificador_de_teste(),
        pedidos=pedidos,
        gateway=gateway,
        fabrica_uow=fabrica_fake(estado),
    )
    app = criar_app(config, substituicoes)
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            yield http
