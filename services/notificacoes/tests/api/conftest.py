from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from asgi_lifespan import LifespanManager

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria, fabrica_em_memoria
from notificacoes.api import criar_app
from notificacoes.config import Config
from plataforma.testes.tokens import GeradorDeTokens, criar_verificador_de_teste

GERADOR = GeradorDeTokens()

Bearer = Callable[[str, str], dict[str, str]]


@pytest.fixture
def armazenamento() -> ArmazenamentoEmMemoria:
    return ArmazenamentoEmMemoria()


@pytest.fixture
async def api(
    config: Config, armazenamento: ArmazenamentoEmMemoria
) -> AsyncIterator[httpx.AsyncClient]:
    """App real com UoW em memória e verificador de JWT sem rede."""
    app = criar_app(
        config,
        fabrica_uow=fabrica_em_memoria(armazenamento),
        verificador=criar_verificador_de_teste(GERADOR),
    )
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            yield http


@pytest.fixture
def bearer() -> Bearer:
    def gerar(sub: str, papel: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {GERADOR.emitir(sub, papel)}"}

    return gerar
