import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from plataforma.api.saude import verificacao_banco, verificacao_broker

pytestmark = pytest.mark.integracao


async def test_verificacoes_de_saude_com_infra_real(postgres_url: str, rabbitmq_url: str) -> None:
    engine = create_async_engine(postgres_url)
    try:
        await verificacao_banco(engine)()
        await verificacao_broker(rabbitmq_url)()
    finally:
        await engine.dispose()


async def test_verificacao_broker_falha_com_broker_inexistente() -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011 - qualquer falha de conexão serve
        await verificacao_broker("amqp://guest:guest@127.0.0.1:1/", timeout=1)()
