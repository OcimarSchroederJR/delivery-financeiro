import json
import uuid
from collections.abc import AsyncIterator

import aio_pika
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from plataforma.db import criar_engine, criar_fabrica_sessoes, criar_metadata
from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import NOME_EXCHANGE_EVENTOS, PublicadorRabbit, criar_broker
from plataforma.outbox import OutboxMixin, RelayOutbox, gravar_no_outbox

pytestmark = pytest.mark.integracao


class Base(DeclarativeBase):
    metadata = criar_metadata()


class MensagemOutboxRoteamento(OutboxMixin, Base):
    __tablename__ = "outbox_roteamento"


@pytest.fixture
async def fabrica(postgres_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = criar_engine(postgres_url)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.drop_all)
        await conexao.run_sync(Base.metadata.create_all)
    yield criar_fabrica_sessoes(engine)
    await engine.dispose()


@pytest.fixture
async def publicador(rabbitmq_url: str) -> AsyncIterator[PublicadorRabbit]:
    publicador = PublicadorRabbit(criar_broker(rabbitmq_url))
    await publicador.iniciar()
    yield publicador
    await publicador.encerrar()


async def test_evento_sem_fila_fica_pendente_e_sai_quando_a_fila_existe(
    fabrica: async_sessionmaker[AsyncSession], publicador: PublicadorRabbit, rabbitmq_url: str
) -> None:
    tipo = f"roteamento.teste_{uuid.uuid4().hex}"
    envelope = EnvelopeEvento.novo(tipo, {"n": 1})
    async with fabrica() as sessao, sessao.begin():
        gravar_no_outbox(sessao, MensagemOutboxRoteamento, envelope)
    relay = RelayOutbox(fabrica, MensagemOutboxRoteamento, publicador)

    assert await relay.publicar_pendentes() == 0
    async with fabrica() as sessao:
        registro = await sessao.scalar(select(MensagemOutboxRoteamento))
    assert registro is not None
    assert registro.publicado_em is None
    assert registro.tentativas == 1

    conexao = await aio_pika.connect(rabbitmq_url)
    try:
        canal = await conexao.channel()
        exchange = await canal.get_exchange(NOME_EXCHANGE_EVENTOS)
        fila = await canal.declare_queue(exclusive=True)
        await fila.bind(exchange, routing_key=tipo)

        assert await relay.publicar_pendentes() == 1
        mensagem = await fila.get(timeout=5)
        await mensagem.ack()
        assert json.loads(mensagem.body)["mensagem_id"] == str(envelope.mensagem_id)
    finally:
        await conexao.close()
