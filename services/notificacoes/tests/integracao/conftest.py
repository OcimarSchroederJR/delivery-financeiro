import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any

import aio_pika
import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.core.container import DockerContainer

from notificacoes.adaptadores.cifrador import CifradorFernet
from notificacoes.adaptadores.db.uow import fabrica_sql
from notificacoes.adaptadores.mensageria.topologia import (
    FILA_DLQ,
    FILA_EMAILS,
    FILA_EVENTOS,
    FILA_WEBHOOKS,
    nome_fila_retry,
)
from notificacoes.aplicacao.assinaturas import criar_assinatura
from notificacoes.aplicacao.solicitante import Solicitante
from notificacoes.config import Config
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.worker import executar
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import NOME_EXCHANGE_EVENTOS
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

IMAGEM_MAILPIT = "axllent/mailpit:v1.31.5"
TTLS_TESTE = (100, 100, 100, 100, 100)
URL_IDENTIDADE = "http://identidade.teste"
URL_RECEPTOR = "https://receptor.teste/webhook"
ADMIN = Solicitante(id="admin-1", admin=True)
FILAS_DO_SERVICO = (
    FILA_EVENTOS,
    FILA_EMAILS,
    FILA_WEBHOOKS,
    FILA_DLQ,
    *(nome_fila_retry(fila, n) for fila in (FILA_EMAILS, FILA_WEBHOOKS) for n in range(1, 11)),
)

Condicao = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class Mailpit:
    host: str
    porta_smtp: int
    url_api: str


@pytest.fixture(autouse=True)
async def limpar_filas(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Apaga as filas do serviço ao fim de cada teste que usou o RabbitMQ.

    Necessário porque o RabbitMQ recusa redeclarar fila com outros argumentos
    (os testes usam TTL de 100 ms; o ``test_infra_real`` usa os padrões).
    """
    yield
    if "rabbitmq_url" not in request.fixturenames:
        return
    conexao = await aio_pika.connect(request.getfixturevalue("rabbitmq_url"))
    try:
        for nome in FILAS_DO_SERVICO:
            canal = await conexao.channel()
            with contextlib.suppress(aio_pika.exceptions.AMQPError):
                await canal.queue_delete(nome)
            with contextlib.suppress(aio_pika.exceptions.AMQPError):
                await canal.close()
    finally:
        await conexao.close()


@pytest.fixture(scope="session")
def mailpit() -> Iterator[Mailpit]:
    """Mailpit real (SMTP 1025 + API 8025) em portas aleatórias."""
    with DockerContainer(IMAGEM_MAILPIT).with_exposed_ports(1025, 8025) as container:
        host = container.get_container_host_ip()
        servidor = Mailpit(
            host=host,
            porta_smtp=int(container.get_exposed_port(1025)),
            url_api=f"http://{host}:{container.get_exposed_port(8025)}",
        )
        for _ in range(100):
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{servidor.url_api}/readyz", timeout=1).status_code == 200:
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("O Mailpit não ficou pronto.")
        yield servidor


@pytest.fixture
def externos(mailpit: Mailpit) -> Iterator[respx.MockRouter]:
    """HTTP de saída simulado (Perfis e receptores); o Mailpit passa direto."""
    with respx.mock(assert_all_called=False) as roteador:
        roteador.route(url__startswith=mailpit.url_api).pass_through()
        yield roteador


@pytest.fixture
def emails_para(
    mailpit: Mailpit, externos: respx.MockRouter
) -> Callable[[str], Awaitable[list[dict[str, Any]]]]:
    httpx.delete(f"{mailpit.url_api}/api/v1/messages", timeout=5).raise_for_status()

    async def buscar(endereco: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=mailpit.url_api, timeout=5) as http:
            resposta = await http.get("/api/v1/search", params={"query": f"to:{endereco}"})
        resposta.raise_for_status()
        mensagens: list[dict[str, Any]] = resposta.json()["messages"]
        return mensagens

    return buscar


@pytest.fixture
def config_worker(banco_migrado: str, rabbitmq_url: str, mailpit: Mailpit) -> Config:
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        ambiente="teste",
        database_url=banco_migrado,
        rabbitmq_url=rabbitmq_url,
        identidade_url=URL_IDENTIDADE,
        smtp_host=mailpit.host,
        smtp_porta=mailpit.porta_smtp,
        fila_retry_ttls_ms=TTLS_TESTE,
        relay_intervalo_segundos=0.05,
        consumidor_pausa_em_erro_segundos=0.05,
    )


async def _aguardar_consumidores(url: str, tarefa: asyncio.Task[None]) -> None:
    conexao = await aio_pika.connect(url)
    try:
        for _ in range(200):
            if tarefa.done():
                tarefa.result()  # propaga o erro de subida do worker
            canal = await conexao.channel()
            try:
                fila = await canal.declare_queue(FILA_WEBHOOKS, passive=True)
                if fila.declaration_result.consumer_count > 0:
                    return
            except aio_pika.exceptions.AMQPError:
                pass  # a fila ainda não existe
            finally:
                with contextlib.suppress(aio_pika.exceptions.AMQPError):
                    await canal.close()
            await asyncio.sleep(0.1)
        raise AssertionError("O worker não iniciou os consumidores a tempo.")
    finally:
        await conexao.close()


@pytest.fixture
async def worker(config_worker: Config, externos: respx.MockRouter) -> AsyncIterator[None]:
    """Worker real rodando no mesmo loop (respx intercepta o HTTP de saída)."""
    parar = asyncio.Event()
    tarefa = asyncio.create_task(executar(config_worker, parar))
    try:
        await _aguardar_consumidores(config_worker.rabbitmq_url, tarefa)
        yield
    finally:
        parar.set()
        await asyncio.wait_for(tarefa, timeout=30)


@pytest.fixture
def esperar_ate() -> Callable[..., Awaitable[None]]:
    async def esperar(condicao: Condicao, prazo_segundos: float = 20.0) -> None:
        limite = time.monotonic() + prazo_segundos
        while not await condicao():
            if time.monotonic() > limite:
                raise AssertionError("A condição não foi atingida a tempo.")
            await asyncio.sleep(0.1)

    return esperar


@pytest.fixture
def publicar_evento(rabbitmq_url: str) -> Callable[[EnvelopeEvento], Awaitable[None]]:
    """Publica como Pagamentos/Avaliações publicariam (exchange topic, routing key = tipo)."""

    async def publicar(envelope: EnvelopeEvento) -> None:
        conexao = await aio_pika.connect(rabbitmq_url)
        try:
            canal = await conexao.channel()
            exchange = await canal.declare_exchange(
                NOME_EXCHANGE_EVENTOS, aio_pika.ExchangeType.TOPIC, durable=True
            )
            await exchange.publish(
                aio_pika.Message(
                    json.dumps(envelope.para_json()).encode(),
                    message_id=str(envelope.mensagem_id),
                    headers={"X-Correlation-ID": envelope.correlation_id},
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=envelope.tipo,
            )
        finally:
            await conexao.close()

    return publicar


@pytest.fixture
async def consultar(banco_migrado: str) -> AsyncIterator[Callable[..., Awaitable[list[Any]]]]:
    engine = create_async_engine(banco_migrado)

    async def executar_sql(sql: str, **parametros: Any) -> list[Any]:
        async with engine.connect() as conexao:
            return [tuple(linha) for linha in (await conexao.execute(text(sql), parametros)).all()]

    yield executar_sql
    await engine.dispose()


@pytest.fixture
async def assinar(
    config_worker: Config,
) -> AsyncIterator[Callable[..., Awaitable[AssinaturaWebhook]]]:
    engine = criar_engine(config_worker.database_url)
    fabrica = fabrica_sql(
        criar_fabrica_sessoes(engine),
        CifradorFernet.de_segredo(config_worker.segredo_de_cifragem()),
    )

    async def criar(eventos: list[str], *, url: str = URL_RECEPTOR) -> AssinaturaWebhook:
        return await criar_assinatura(
            fabrica(), ADMIN, url=url, eventos=eventos, politica=config_worker.politica_de_url()
        )

    yield criar
    await engine.dispose()
