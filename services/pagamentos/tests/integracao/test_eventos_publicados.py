import asyncio
import json
from typing import Any

import aio_pika
import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.adaptadores.mensageria.esquemas import EVENTOS_PUBLICADOS
from pagamentos.api import Substituicoes, criar_app
from pagamentos.config import Config
from pagamentos.testes.fakes import ConsultaPedidosFake
from pagamentos.testes.requisicoes import cabecalhos, corpo_pix, verificador_de_teste
from pagamentos.worker import executar
from plataforma.mensageria import EXCHANGE_EVENTOS, NOME_EXCHANGE_EVENTOS
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

pytestmark = pytest.mark.integracao

BROKER_FORA = "amqp://guest:guest@127.0.0.1:1/"


def _config(database_url: str, rabbitmq_url: str) -> Config:
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        ambiente="teste",
        database_url=database_url,
        rabbitmq_url=rabbitmq_url,
    )


async def _pendentes(url: str) -> int:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conexao:
            consulta = text("SELECT count(*) FROM outbox WHERE publicado_em IS NULL")
            return int((await conexao.execute(consulta)).scalar_one())
    finally:
        await engine.dispose()


async def test_worker_publica_os_eventos_de_pagamento_com_os_dados_da_spec(
    banco_migrado: str, rabbitmq_url: str
) -> None:
    conexao = await aio_pika.connect(rabbitmq_url)
    canal = await conexao.channel()
    exchange = await canal.declare_exchange(
        NOME_EXCHANGE_EVENTOS, aio_pika.ExchangeType.TOPIC, durable=EXCHANGE_EVENTOS.durable
    )
    fila = await canal.declare_queue(exclusive=True)
    await fila.bind(exchange, routing_key="pagamento.*")

    # A API roda com o broker inacessível: ela não depende dele (spec §5); o outbox acumula.
    app = criar_app(
        _config(banco_migrado, BROKER_FORA),
        Substituicoes(
            verificador=verificador_de_teste(),
            pedidos=ConsultaPedidosFake(),
            gateway=GatewaySimulado(),
        ),
    )
    async with (
        LifespanManager(app) as gerenciador,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gerenciador.app), base_url="http://teste"
        ) as http,
    ):
        aprovado = (
            await http.post(
                "/v1/pagamentos", json=corpo_pix("ped-1"), headers=cabecalhos(chave="e-1")
            )
        ).json()
        recusado = await http.post(
            "/v1/pagamentos", json=corpo_pix("ped-2"), headers=cabecalhos(chave="e-2")
        )
        assert recusado.status_code == 409
        estorno = (
            await http.post(
                f"/v1/pagamentos/{aprovado['id']}/estornos",
                json={"valor_centavos": 590, "motivo": "item faltando"},
                headers=cabecalhos("servico", "avaliacoes", chave="disputa-1"),
            )
        ).json()
    assert await _pendentes(banco_migrado) == 3

    parar = asyncio.Event()
    tarefa = asyncio.create_task(executar(_config(banco_migrado, rabbitmq_url), parar))
    mensagens: list[dict[str, Any]] = []
    try:
        for _ in range(100):
            mensagem = await fila.get(fail=False)
            if mensagem is None:
                await asyncio.sleep(0.1)
                continue
            await mensagem.ack()
            mensagens.append(json.loads(mensagem.body))
            if len(mensagens) == 3:
                break
    finally:
        parar.set()
        await asyncio.wait_for(tarefa, timeout=5)
        await conexao.close()

    assert [m["tipo"] for m in mensagens] == [
        "pagamento.aprovado",
        "pagamento.recusado",
        "pagamento.estornado",
    ]
    for mensagem in mensagens:
        EVENTOS_PUBLICADOS[mensagem["tipo"]].envelope.model_validate(mensagem)
    assert mensagens[0]["dados"]["pagamento_id"] == aprovado["id"]
    assert mensagens[1]["dados"]["motivo"] == "analise_antifraude"
    assert (mensagens[2]["dados"]["estorno_id"], mensagens[2]["dados"]["valor_centavos"]) == (
        estorno["id"],
        590,
    )
    assert await _pendentes(banco_migrado) == 0
