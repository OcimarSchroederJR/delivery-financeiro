import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
import httpx
import pytest
import respx
from structlog.testing import capture_logs

from notificacoes.adaptadores.mensageria.topologia import FILA_DLQ
from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import NOME_EXCHANGE_EVENTOS

pytestmark = pytest.mark.integracao

URL_IDENTIDADE = "http://identidade.teste"
URL_RECEPTOR = "https://receptor.teste/webhook"
PERFIL_1 = {"id": "cliente-1", "nome": "Ana", "email": "cliente-1@exemplo.com"}
APROVADO = {
    "pagamento_id": "pag-1",
    "pedido_id": "ped-1",
    "cliente_id": "cliente-1",
    "valor_centavos": 4590,
    "metodo": "pix",
}
RECUSADO = {
    "pagamento_id": "pag-2",
    "pedido_id": "ped-1",
    "cliente_id": "cliente-1",
    "valor_centavos": 4590,
    "motivo": "saldo_insuficiente",
}

Consulta = Callable[..., Awaitable[list[Any]]]
Esperar = Callable[..., Awaitable[None]]
Publicar = Callable[[EnvelopeEvento], Awaitable[None]]


async def _mensagens_na_dlq(canal: aio_pika.abc.AbstractChannel) -> int:
    fila = await canal.declare_queue(FILA_DLQ, passive=True)
    return int(fila.declaration_result.message_count or 0)


async def test_mensagem_duplicada_nao_reenvia(
    worker: None,
    externos: respx.MockRouter,
    assinar: Callable[..., Awaitable[Any]],
    publicar_evento: Publicar,
    esperar_ate: Esperar,
    emails_para: Callable[[str], Awaitable[list[dict[str, Any]]]],
    consultar: Consulta,
) -> None:
    externos.get(f"{URL_IDENTIDADE}/perfis/cliente-1").mock(
        return_value=httpx.Response(200, json=PERFIL_1)
    )
    receptor = externos.post(URL_RECEPTOR).mock(return_value=httpx.Response(204))
    await assinar(["pagamento.*"])
    envelope = EnvelopeEvento.novo("pagamento.aprovado", APROVADO)

    with capture_logs() as logs:
        await publicar_evento(envelope)
        await publicar_evento(envelope)

        async def duplicata_detectada() -> bool:
            return any(
                log.get("event") == "evento_consumido" and log.get("inbox") == "duplicada"
                for log in logs
            )

        async def tudo_enviado() -> bool:
            linhas = await consultar("SELECT status FROM notificacoes")
            return linhas == [("enviada",), ("enviada",)]

        await esperar_ate(duplicata_detectada)
        await esperar_ate(tudo_enviado)
    await asyncio.sleep(0.5)  # dá tempo de um eventual reenvio indevido aparecer

    assert receptor.call_count == 1
    assert len(await emails_para("cliente-1@exemplo.com")) == 1
    assert await consultar("SELECT count(*) FROM notificacoes") == [(2,)]


async def test_webhook_falhando_ate_a_dlq(
    worker: None,
    externos: respx.MockRouter,
    assinar: Callable[..., Awaitable[Any]],
    publicar_evento: Publicar,
    esperar_ate: Esperar,
    consultar: Consulta,
    rabbitmq_url: str,
) -> None:
    externos.get(f"{URL_IDENTIDADE}/perfis/cliente-1").mock(
        return_value=httpx.Response(200, json=PERFIL_1)
    )
    receptor = externos.post(URL_RECEPTOR).mock(return_value=httpx.Response(500))
    assinatura = await assinar(["pagamento.*"])
    envelope = EnvelopeEvento.novo("pagamento.recusado", RECUSADO)

    await publicar_evento(envelope)

    async def webhook_falhou() -> bool:
        linhas = await consultar(
            "SELECT status, tentativas FROM notificacoes WHERE canal = 'webhook'"
        )
        return linhas == [("falhou", 6)]

    await esperar_ate(webhook_falhou, prazo_segundos=30)
    entregas = await consultar(
        "SELECT tentativa, status_http FROM entregas_webhook "
        "WHERE assinatura_id = :id ORDER BY tentativa",
        id=assinatura.id,
    )
    assert entregas == [(numero, 500) for numero in range(1, 7)]
    assert receptor.call_count == 6

    conexao = await aio_pika.connect(rabbitmq_url)
    try:
        canal = await conexao.channel()

        async def na_dlq() -> bool:
            return await _mensagens_na_dlq(canal) >= 1

        await esperar_ate(na_dlq)
        dlq = await canal.declare_queue(FILA_DLQ, passive=True)
        mensagem = await dlq.get(timeout=5)
        await mensagem.ack()
    finally:
        await conexao.close()
    assert mensagem.headers["x-fila-origem"] == "notificacoes.webhooks"
    assert mensagem.headers["x-motivo"] == "HTTP 500"
    corpo = json.loads(mensagem.body)
    assert corpo["tipo"] == "tarefa.webhook"
    assert corpo["dados"]["evento"]["mensagem_id"] == str(envelope.mensagem_id)


async def test_identidade_fora_nao_perde_o_email(
    worker: None,
    externos: respx.MockRouter,
    publicar_evento: Publicar,
    esperar_ate: Esperar,
    emails_para: Callable[[str], Awaitable[list[dict[str, Any]]]],
    consultar: Consulta,
) -> None:
    # 1ª tentativa: as 3 chamadas internas do ClienteHttp falham → retry.1 (100 ms)
    perfis = externos.get(f"{URL_IDENTIDADE}/perfis/cliente-1").mock(
        side_effect=[httpx.ConnectError("fora")] * 3 + [httpx.Response(200, json=PERFIL_1)]
    )
    envelope = EnvelopeEvento.novo("pagamento.aprovado", APROVADO)
    await publicar_evento(envelope)

    async def enviado() -> bool:
        linhas = await consultar("SELECT status FROM notificacoes WHERE canal = 'email'")
        return linhas == [("enviada",)]

    await esperar_ate(enviado)
    [(tentativas, ultimo_erro)] = await consultar(
        "SELECT tentativas, ultimo_erro FROM notificacoes WHERE canal = 'email'"
    )
    assert tentativas == 2
    assert ultimo_erro.startswith("ErroDependenciaIndisponivel")
    assert perfis.call_count == 4
    assert len(await emails_para("cliente-1@exemplo.com")) == 1


async def test_mensagem_invalida_vai_para_a_dlq(
    worker: None, rabbitmq_url: str, esperar_ate: Esperar
) -> None:
    conexao = await aio_pika.connect(rabbitmq_url)
    try:
        canal = await conexao.channel()
        exchange = await canal.get_exchange(NOME_EXCHANGE_EVENTOS)
        await exchange.publish(aio_pika.Message(b"nao-e-json"), routing_key="lixo.qualquer")

        async def na_dlq() -> bool:
            return await _mensagens_na_dlq(canal) == 1

        await esperar_ate(na_dlq)
    finally:
        await conexao.close()
