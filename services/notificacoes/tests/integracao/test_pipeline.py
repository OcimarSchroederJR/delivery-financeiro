import json
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager

from notificacoes.adaptadores.mensageria.topologia import FILA_EVENTOS, declarar_topologia
from notificacoes.api import criar_app
from notificacoes.config import Config
from notificacoes.dominio.assinatura_hmac import assinatura_valida
from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import criar_broker
from plataforma.testes.tokens import GeradorDeTokens, criar_verificador_de_teste

pytestmark = pytest.mark.integracao

URL_IDENTIDADE = "http://identidade.teste"
URL_RECEPTOR = "https://receptor.teste/webhook"
APROVADO = {
    "pagamento_id": "pag-1",
    "pedido_id": "ped-1",
    "cliente_id": "cliente-1",
    "valor_centavos": 4590,
    "metodo": "pix",
}
PERFIL_1 = {"id": "cliente-1", "nome": "Ana", "email": "cliente-1@exemplo.com", "papel": "cliente"}

Consulta = Callable[..., Awaitable[list[Any]]]
Esperar = Callable[..., Awaitable[None]]


async def test_declarar_topologia_liga_a_fila_de_eventos_ao_exchange(
    rabbitmq_url: str, publicar_evento: Callable[[EnvelopeEvento], Awaitable[None]]
) -> None:
    broker = criar_broker(rabbitmq_url)
    await broker.connect()
    try:
        await declarar_topologia(broker, (100, 100, 100, 100, 100))
    finally:
        await broker.stop()
    envelope = EnvelopeEvento.novo("pedido.criado", {"pedido_id": "ped-9"})
    await publicar_evento(envelope)
    conexao = await aio_pika.connect(rabbitmq_url)
    try:
        canal = await conexao.channel()
        fila = await canal.declare_queue(FILA_EVENTOS, passive=True)
        mensagem = await fila.get(timeout=5)
        await mensagem.ack()
    finally:
        await conexao.close()
    assert json.loads(mensagem.body)["mensagem_id"] == str(envelope.mensagem_id)


async def test_pagamento_aprovado_gera_email_e_webhook_assinado(
    worker: None,
    externos: respx.MockRouter,
    assinar: Callable[..., Awaitable[Any]],
    publicar_evento: Callable[[EnvelopeEvento], Awaitable[None]],
    esperar_ate: Esperar,
    emails_para: Callable[[str], Awaitable[list[dict[str, Any]]]],
    consultar: Consulta,
) -> None:
    externos.get(f"{URL_IDENTIDADE}/perfis/cliente-1").mock(
        return_value=httpx.Response(200, json=PERFIL_1)
    )
    receptor = externos.post(URL_RECEPTOR).mock(return_value=httpx.Response(204))
    assinatura = await assinar(["pagamento.*"])
    envelope = EnvelopeEvento.novo("pagamento.aprovado", APROVADO)

    await publicar_evento(envelope)

    async def tudo_enviado() -> bool:
        linhas = await consultar(
            "SELECT canal, status FROM notificacoes WHERE mensagem_id_origem = :id ORDER BY canal",
            id=envelope.mensagem_id,
        )
        return linhas == [("email", "enviada"), ("webhook", "enviada")]

    await esperar_ate(tudo_enviado)
    [email] = await emails_para("cliente-1@exemplo.com")
    assert email["Subject"] == "Pagamento aprovado - pedido ped-1"

    requisicao = receptor.calls.last.request
    assert json.loads(requisicao.content) == envelope.para_json()
    timestamp = int(requisicao.headers["X-Assinatura-Timestamp"])
    assert assinatura_valida(
        assinatura.segredo,
        timestamp,
        requisicao.content,
        requisicao.headers["X-Assinatura"],
        agora=timestamp,
    )
    assert requisicao.headers["X-Evento-Id"] == str(envelope.mensagem_id)
    assert requisicao.headers["X-Evento-Tipo"] == "pagamento.aprovado"
    assert requisicao.headers["X-Correlation-ID"] == envelope.correlation_id
    entregas = await consultar(
        "SELECT tentativa, status_http FROM entregas_webhook WHERE assinatura_id = :id",
        id=assinatura.id,
    )
    assert entregas == [(1, 204)]


async def test_entrega_concluida_via_post_eventos_vira_email(
    config_worker: Config,
    worker: None,
    externos: respx.MockRouter,
    esperar_ate: Esperar,
    emails_para: Callable[[str], Awaitable[list[dict[str, Any]]]],
) -> None:
    """Fluxo da Eq. 4: POST /v1/eventos → outbox → financeiro.eventos → e-mail."""
    externos.get(f"{URL_IDENTIDADE}/perfis/cliente-2").mock(
        return_value=httpx.Response(200, json={"id": "cliente-2", "email": "cliente-2@exemplo.com"})
    )
    gerador = GeradorDeTokens()
    app = criar_app(config_worker, verificador=criar_verificador_de_teste(gerador))
    envelope = EnvelopeEvento.novo(
        "entrega.concluida",
        {
            "pedido_id": "ped-3",
            "cliente_id": "cliente-2",
            "entregador_id": "entregador-1",
            "concluida_em": "2026-10-14T15:00:00Z",
        },
    )
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            resposta = await http.post(
                "/v1/eventos",
                json=envelope.para_json(),
                headers={
                    "Authorization": f"Bearer {gerador.emitir('mock-logistica', 'entregador')}"
                },
            )
    assert resposta.json() == {"mensagem_id": str(envelope.mensagem_id), "status": "aceito"}

    async def chegou() -> bool:
        return len(await emails_para("cliente-2@exemplo.com")) == 1

    await esperar_ate(chegou)
    [email] = await emails_para("cliente-2@exemplo.com")
    assert email["Subject"] == "Pedido ped-3 entregue"


async def test_evento_sem_template_nem_assinatura_so_passa_pela_inbox(
    worker: None,
    publicar_evento: Callable[[EnvelopeEvento], Awaitable[None]],
    esperar_ate: Esperar,
    consultar: Consulta,
) -> None:
    envelope = EnvelopeEvento.novo("pedido.criado", {"pedido_id": "ped-9"})
    await publicar_evento(envelope)

    async def na_inbox() -> bool:
        return bool(
            await consultar("SELECT 1 FROM inbox WHERE mensagem_id = :id", id=envelope.mensagem_id)
        )

    await esperar_ate(na_inbox)
    assert await consultar("SELECT id FROM notificacoes") == []
