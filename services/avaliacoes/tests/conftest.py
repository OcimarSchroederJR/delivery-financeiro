from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from avaliacoes.api import criar_app
from avaliacoes.config import Config
from plataforma.testes.fixtures import postgres_url, rabbitmq_url  # noqa: F401
from plataforma.testes.migracoes import desfazer, migrar
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

DIRETORIO_SERVICO = Path(__file__).resolve().parents[1]
ALEMBIC_INI = DIRETORIO_SERVICO / "alembic.ini"
RAIZ_REPOSITORIO = DIRETORIO_SERVICO.parents[1]
INFRA_INEXISTENTE = {
    "database_url": "postgresql+asyncpg://x:x@127.0.0.1:1/x",
    "rabbitmq_url": "amqp://guest:guest@127.0.0.1:1/",
}


@pytest.fixture
def config() -> Config:
    """Config de teste sem infraestrutura real (portas fechadas)."""
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        ambiente="teste",
        **INFRA_INEXISTENTE,
    )


@pytest.fixture
async def cliente(config: Config) -> AsyncIterator[httpx.AsyncClient]:
    app = criar_app(config)
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            yield http


@pytest.fixture
def banco_migrado(postgres_url: str) -> Iterator[str]:  # noqa: F811
    """Banco real com ``alembic upgrade head``; desfaz tudo ao final."""
    migrar(ALEMBIC_INI, postgres_url)
    yield postgres_url
    desfazer(ALEMBIC_INI, postgres_url)
