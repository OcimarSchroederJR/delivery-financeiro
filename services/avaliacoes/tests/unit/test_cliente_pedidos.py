from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from avaliacoes.adaptadores.clientes.pedidos import PedidosHttp
from avaliacoes.aplicacao.portas import PedidoExterno
from avaliacoes.dominio.erros import PedidoDeOutroCliente
from plataforma.cliente_http import ClienteHttp
from plataforma.correlation import HEADER_CORRELATION_ID, correlation_id_em
from plataforma.erros import ErroDependenciaIndisponivel

URL_PEDIDOS = "http://pedidos.teste"


@pytest.fixture
async def pedidos() -> AsyncIterator[PedidosHttp]:
    async with ClienteHttp("pedidos", URL_PEDIDOS, espera_base=0, espera_maxima=0) as cliente:
        yield PedidosHttp(cliente)


def _pedido(status: str = "entregue") -> dict[str, object]:
    return {
        "id": "ped-4",
        "cliente_id": "cliente-1",
        "restaurante_id": "rest-1",
        "valor_total_centavos": 3200,
        "status": status,
        "criado_em": "2026-10-14T12:00:00Z",
    }


@respx.mock(base_url=URL_PEDIDOS)
async def test_pedido_entregue_com_token_e_correlation(
    respx_mock: respx.MockRouter, pedidos: PedidosHttp
) -> None:
    rota = respx_mock.get("/pedidos/ped-4").respond(200, json=_pedido())
    with correlation_id_em("corr-123"):
        pedido = await pedidos.obter("ped-4", token="tok-cliente")
    assert pedido == PedidoExterno("ped-4", "cliente-1", "rest-1", entregue=True)
    requisicao = rota.calls.last.request
    assert requisicao.headers["Authorization"] == "Bearer tok-cliente"
    assert requisicao.headers[HEADER_CORRELATION_ID] == "corr-123"


@respx.mock(base_url=URL_PEDIDOS)
async def test_pedido_nao_entregue_e_inexistente(
    respx_mock: respx.MockRouter, pedidos: PedidosHttp
) -> None:
    respx_mock.get("/pedidos/ped-1").respond(200, json=_pedido("saiu_para_entrega"))
    respx_mock.get("/pedidos/nao-existe").respond(404, json={"erro": True})
    assert (await pedidos.obter("ped-1", token="t")).entregue is False  # type: ignore[union-attr]
    assert await pedidos.obter("nao-existe", token="t") is None


@respx.mock(base_url=URL_PEDIDOS)
async def test_pedido_id_e_codificado_na_rota(
    respx_mock: respx.MockRouter, pedidos: PedidosHttp
) -> None:
    rota = respx_mock.get(url__regex=r".*/pedidos/a%2F\.\.%2Fb$").respond(404)
    assert await pedidos.obter("a/../b", token="t") is None
    assert rota.called


@respx.mock(base_url=URL_PEDIDOS)
async def test_pedido_403_da_eq3_vira_403(
    respx_mock: respx.MockRouter, pedidos: PedidosHttp
) -> None:
    respx_mock.get("/pedidos/ped-3").respond(403, json={"erro": True})
    with pytest.raises(PedidoDeOutroCliente):
        await pedidos.obter("ped-3", token="t")


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(503),
        httpx.Response(401),
        httpx.Response(200, text="não é json"),
        httpx.Response(200, json={"id": "ped-4"}),
    ],
)
@respx.mock(base_url=URL_PEDIDOS)
async def test_eq3_fora_ou_resposta_ruim_vira_503(
    respx_mock: respx.MockRouter, pedidos: PedidosHttp, resposta: httpx.Response
) -> None:
    respx_mock.get("/pedidos/ped-4").mock(return_value=resposta)
    with pytest.raises(ErroDependenciaIndisponivel) as erro:
        await pedidos.obter("ped-4", token="t")
    assert erro.value.status_http == 503
    assert erro.value.detalhes == {"dependencia": "pedidos"}


@respx.mock(base_url=URL_PEDIDOS)
async def test_eq3_com_timeout_vira_503(respx_mock: respx.MockRouter, pedidos: PedidosHttp) -> None:
    rota = respx_mock.get("/pedidos/ped-4").mock(side_effect=httpx.ConnectTimeout("lento"))
    with pytest.raises(ErroDependenciaIndisponivel):
        await pedidos.obter("ped-4", token="t")
    assert rota.call_count == 3  # GET é repetido pelo ClienteHttp
