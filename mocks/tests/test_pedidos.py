from collections.abc import AsyncIterator

import httpx
import pytest

from mocks_equipes.pedidos import criar_app


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=criar_app())
    async with httpx.AsyncClient(transport=transporte, base_url="http://pedidos") as cliente:
        yield cliente


async def test_pedido_semeado(http: httpx.AsyncClient) -> None:
    corpo = (await http.get("/pedidos/ped-1")).json()
    assert corpo["cliente_id"] == "cliente-1"
    assert corpo["restaurante_id"] == "rest-1"
    assert corpo["valor_total_centavos"] == 4590
    assert corpo["status"] == "confirmado"
    assert corpo["criado_em"].endswith("Z")


async def test_pedido_inexistente_404_no_formato_padrao(http: httpx.AsyncClient) -> None:
    resposta = await http.get("/pedidos/nao-existe")
    assert resposta.status_code == 404
    assert resposta.json()["codigo"] == "PEDIDO_NAO_ENCONTRADO"


async def test_put_cria_e_depois_substitui(http: httpx.AsyncClient) -> None:
    dados = {"cliente_id": "c9", "restaurante_id": "r9", "valor_total_centavos": 100}
    assert (await http.put("/pedidos/novo", json=dados)).status_code == 201
    resposta = await http.put("/pedidos/novo", json={**dados, "status": "entregue"})
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "entregue"


async def test_patch_altera_status(http: httpx.AsyncClient) -> None:
    resposta = await http.patch("/pedidos/ped-1", json={"status": "entregue"})
    assert resposta.json()["status"] == "entregue"
    assert (await http.patch("/pedidos/x", json={"status": "entregue"})).status_code == 404


async def test_listar(http: httpx.AsyncClient) -> None:
    assert len((await http.get("/pedidos")).json()) == 4


async def test_valor_negativo_rejeitado(http: httpx.AsyncClient) -> None:
    dados = {"cliente_id": "c", "restaurante_id": "r", "valor_total_centavos": -1}
    assert (await http.put("/pedidos/x", json=dados)).status_code == 422
