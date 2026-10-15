import asyncio
import json

import aio_pika
import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from notificacoes.adaptadores.db.modelos import Base, MensagemOutbox
from notificacoes.api import criar_app
from notificacoes.config import Config
from notificacoes.worker import executar
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import EXCHANGE_EVENTOS, NOME_EXCHANGE_EVENTOS
from plataforma.outbox import gravar_no_outbox
from plataforma.testes.migracoes import diferencas_modelo_banco
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

pytestmark = pytest.mark.integracao


def _config(database_url: str, rabbitmq_url: str) -> Config:
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        database_url=database_url,
        rabbitmq_url=rabbitmq_url,
    )


async def test_migracoes_criam_outbox_e_batem_com_os_modelos(banco_migrado: str) -> None:
    engine = create_async_engine(banco_migrado)
    async with engine.connect() as conexao:
        tabelas = await conexao.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    assert {"outbox", "inbox"} <= set(tabelas)
    assert await diferencas_modelo_banco(banco_migrado, Base.metadata) == []


async def test_pronto_com_banco_e_broker_reais(banco_migrado: str, rabbitmq_url: str) -> None:
    app = criar_app(_config(banco_migrado, rabbitmq_url))
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            resposta = await http.get("/saude/pronto")
    assert resposta.status_code == 200
    assert resposta.json()["verificacoes"] == {"banco": "ok", "broker": "ok"}


async def test_worker_publica_eventos_do_outbox(banco_migrado: str, rabbitmq_url: str) -> None:
    conexao = await aio_pika.connect(rabbitmq_url)
    canal = await conexao.channel()
    exchange = await canal.declare_exchange(
        NOME_EXCHANGE_EVENTOS, aio_pika.ExchangeType.TOPIC, durable=EXCHANGE_EVENTOS.durable
    )
    fila = await canal.declare_queue(exclusive=True)
    await fila.bind(exchange, routing_key="#")

    engine = criar_engine(banco_migrado)
    envelope = EnvelopeEvento.novo("teste.publicado", {"origem": "teste"})
    async with criar_fabrica_sessoes(engine)() as sessao, sessao.begin():
        gravar_no_outbox(sessao, MensagemOutbox, envelope)
    await engine.dispose()

    parar = asyncio.Event()
    tarefa = asyncio.create_task(executar(_config(banco_migrado, rabbitmq_url), parar))
    try:
        mensagem = None
        for _ in range(50):
            mensagem = await fila.get(fail=False)
            if mensagem is not None:
                break
            await asyncio.sleep(0.1)
        assert mensagem is not None
        await mensagem.ack()
        assert json.loads(mensagem.body)["mensagem_id"] == str(envelope.mensagem_id)
    finally:
        parar.set()
        await asyncio.wait_for(tarefa, timeout=5)
        await conexao.close()
