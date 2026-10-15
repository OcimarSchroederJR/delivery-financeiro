"""Worker real (Postgres + RabbitMQ): retoma a saga pendente e publica o evento."""

import asyncio
import json
from datetime import timedelta

import aio_pika
import pytest
import respx
from pydantic import SecretStr

from avaliacoes.adaptadores.db.unidade_de_trabalho import fabrica_uow_sql
from avaliacoes.config import Config
from avaliacoes.dominio.disputa import Disputa, MotivoDisputa, StatusDisputa
from avaliacoes.worker import executar
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.mensageria import EXCHANGE_EVENTOS, NOME_EXCHANGE_EVENTOS
from plataforma.tempo import agora_utc
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

pytestmark = pytest.mark.integracao

URL_PAGAMENTOS = "http://pagamentos.teste"


async def test_worker_conclui_saga_pendente_e_publica_disputa_resolvida(
    banco_migrado: str, rabbitmq_url: str
) -> None:
    conexao = await aio_pika.connect(rabbitmq_url)
    canal = await conexao.channel()
    exchange = await canal.declare_exchange(
        NOME_EXCHANGE_EVENTOS, aio_pika.ExchangeType.TOPIC, durable=EXCHANGE_EVENTOS.durable
    )
    fila = await canal.declare_queue(exclusive=True)
    await fila.bind(exchange, routing_key="disputa.*")

    engine = criar_engine(banco_migrado)
    uow = fabrica_uow_sql(criar_fabrica_sessoes(engine))
    agora = agora_utc()
    disputa = Disputa.abrir(
        pedido_id="ped-4",
        pagamento_id="pag-1",
        cliente_id="cliente-1",
        motivo=MotivoDisputa.ITEM_FALTANDO,
        descricao=None,
        valor_solicitado_centavos=1000,
        valor_pago_centavos=3200,
        agora=agora - timedelta(minutes=1),
    )
    disputa.aprovar(
        valor_aprovado_centavos=None,
        parecer=None,
        agora=agora - timedelta(minutes=1),
        primeira_tentativa_em=agora - timedelta(seconds=1),
    )
    async with uow() as u:
        await u.disputas.adicionar(disputa)
        await u.commit()

    config = Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        database_url=banco_migrado,
        rabbitmq_url=rabbitmq_url,
        pagamentos_url=URL_PAGAMENTOS,
        worker_intervalo_segundos=0.05,
    )
    parar = asyncio.Event()
    with respx.mock(base_url=URL_PAGAMENTOS) as mock:
        estorno = mock.post("/v1/pagamentos/pag-1/estornos").respond(201, json={"id": "est-1"})
        tarefa = asyncio.create_task(executar(config, parar))
        try:
            mensagem = None
            for _ in range(100):
                mensagem = await fila.get(fail=False)
                if mensagem is not None:
                    break
                await asyncio.sleep(0.1)
            assert mensagem is not None
            await mensagem.ack()
        finally:
            parar.set()
            await asyncio.wait_for(tarefa, timeout=5)
            await conexao.close()

    envelope = json.loads(mensagem.body)
    assert envelope["tipo"] == "disputa.resolvida"
    assert envelope["dados"]["valor_estornado_centavos"] == 1000
    assert envelope["correlation_id"] == f"disputa-{disputa.id}"
    assert estorno.calls.last.request.headers["Idempotency-Key"] == f"disputa-{disputa.id}"
    async with uow() as u:
        final = await u.disputas.obter(disputa.id)
    await engine.dispose()
    assert final is not None
    assert final.status is StatusDisputa.RESOLVIDA
