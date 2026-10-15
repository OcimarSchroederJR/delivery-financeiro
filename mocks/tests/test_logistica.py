import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager

from mocks_equipes.logistica import criar_app
from plataforma.envelope import EnvelopeEvento

NOTIFICACOES = "http://notificacoes.teste"
IDENTIDADE = "http://identidade.teste"


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    app = criar_app(notificacoes_url=NOTIFICACOES, identidade_url=IDENTIDADE, papel="admin")
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://logistica") as cliente:
            yield cliente


@pytest.fixture
def externos() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as roteador:
        roteador.route(host="logistica").pass_through()
        yield roteador


async def test_conclusao_envia_envelope_para_notificacoes(
    http: httpx.AsyncClient, externos: respx.MockRouter
) -> None:
    token = externos.post(f"{IDENTIDADE}/tokens").mock(
        return_value=httpx.Response(201, json={"access_token": "tok-123"})
    )
    eventos = externos.post(f"{NOTIFICACOES}/v1/eventos").mock(return_value=httpx.Response(202))
    resposta = await http.post("/entregas/ped-3/concluir", json={"cliente_id": "cliente-2"})
    assert resposta.status_code == 202
    assert resposta.json()["status_notificacoes"] == 202
    pedido_token = json.loads(token.calls.last.request.content)
    assert pedido_token == {"sub": "mock-logistica", "papel": "admin"}
    enviada = eventos.calls.last.request
    assert enviada.headers["Authorization"] == "Bearer tok-123"
    envelope = EnvelopeEvento.model_validate_json(enviada.content)
    assert envelope.tipo == "entrega.concluida"
    assert envelope.dados["pedido_id"] == "ped-3"
    assert envelope.dados["cliente_id"] == "cliente-2"


async def test_notificacoes_fora_vira_503(
    http: httpx.AsyncClient, externos: respx.MockRouter
) -> None:
    externos.post(f"{IDENTIDADE}/tokens").mock(
        return_value=httpx.Response(201, json={"access_token": "t"})
    )
    externos.post(f"{NOTIFICACOES}/v1/eventos").mock(side_effect=httpx.ConnectError("fora"))
    resposta = await http.post("/entregas/ped-3/concluir")
    assert resposta.status_code == 503
    assert resposta.json()["codigo"] == "DEPENDENCIA_INDISPONIVEL"


async def test_identidade_recusa_token_vira_503(
    http: httpx.AsyncClient, externos: respx.MockRouter
) -> None:
    externos.post(f"{IDENTIDADE}/tokens").mock(return_value=httpx.Response(422))
    resposta = await http.post("/entregas/ped-3/concluir")
    assert resposta.status_code == 503
