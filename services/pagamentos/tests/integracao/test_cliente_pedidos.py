from typing import Any

import httpx
import pytest
import respx

from pagamentos.adaptadores.clientes.pedidos import ClientePedidosHttp
from pagamentos.dominio.pedido import Pedido
from plataforma.circuit_breaker import CircuitBreaker, CircuitoAberto
from plataforma.cliente_http import ClienteHttp
from plataforma.correlation import HEADER_CORRELATION_ID, correlation_id_em
from plataforma.erros import ErroDependenciaIndisponivel

URL = "http://pedidos.teste"
PEDIDO: dict[str, Any] = {
    "id": "ped-1",
    "cliente_id": "cliente-1",
    "restaurante_id": "rest-1",
    "valor_total_centavos": 4590,
    "status": "confirmado",
    "criado_em": "2026-10-14T14:30:00Z",
}


def _cliente(limite_falhas: int = 5) -> ClienteHttp:
    return ClienteHttp(
        "pedidos",
        URL,
        espera_base=0.001,
        espera_maxima=0.002,
        breaker=CircuitBreaker("pedidos", limite_falhas=limite_falhas),
    )


async def test_pedido_encontrado_repassa_token_e_correlation_id() -> None:
    with respx.mock(base_url=URL) as rotas:
        rota = rotas.get("/pedidos/ped-1").respond(200, json=PEDIDO)
        async with _cliente() as http:
            with correlation_id_em("cid-eq3"):
                pedido = await ClientePedidosHttp(http).obter("ped-1", token="tok-1")
    assert pedido == Pedido("ped-1", "cliente-1", 4590, "confirmado")
    requisicao = rota.calls.last.request
    assert requisicao.headers["Authorization"] == "Bearer tok-1"
    assert requisicao.headers[HEADER_CORRELATION_ID] == "cid-eq3"


async def test_pedido_inexistente_devolve_none() -> None:
    with respx.mock(base_url=URL) as rotas:
        rotas.get("/pedidos/ped-x").respond(404, json={"erro": True})
        async with _cliente() as http:
            assert await ClientePedidosHttp(http).obter("ped-x", token="t") is None


async def test_pedido_id_e_escapado_na_url() -> None:
    with respx.mock(base_url=URL, assert_all_called=False) as rotas:
        rota = rotas.route().respond(404)
        async with _cliente() as http:
            await ClientePedidosHttp(http).obter("ped 1/../x", token="t")
    assert rota.calls.last.request.url.raw_path == b"/pedidos/ped%201%2F..%2Fx"


async def test_5xx_apos_retries_vira_503() -> None:
    with respx.mock(base_url=URL) as rotas:
        rota = rotas.get("/pedidos/ped-1").respond(500)
        async with _cliente() as http:
            with pytest.raises(ErroDependenciaIndisponivel) as erro:
                await ClientePedidosHttp(http).obter("ped-1", token="t")
    assert erro.value.dependencia == "pedidos"
    assert rota.call_count == 3


async def test_timeout_vira_503() -> None:
    with respx.mock(base_url=URL) as rotas:
        rotas.get("/pedidos/ped-1").mock(side_effect=httpx.ReadTimeout("lento"))
        async with _cliente() as http:
            with pytest.raises(ErroDependenciaIndisponivel):
                await ClientePedidosHttp(http).obter("ped-1", token="t")


async def test_circuito_aberto_nem_chama_a_eq3() -> None:
    with respx.mock(base_url=URL) as rotas:
        rota = rotas.get("/pedidos/ped-1").respond(503)
        async with _cliente(limite_falhas=1) as http:
            pedidos = ClientePedidosHttp(http)
            with pytest.raises(ErroDependenciaIndisponivel):
                await pedidos.obter("ped-1", token="t")
            chamadas = rota.call_count
            with pytest.raises(CircuitoAberto):
                await pedidos.obter("ped-1", token="t")
    assert rota.call_count == chamadas


@pytest.mark.parametrize("status", [401, 403, 409])
async def test_status_inesperado_vira_503_sem_retry(status: int) -> None:
    with respx.mock(base_url=URL) as rotas:
        rota = rotas.get("/pedidos/ped-1").respond(status)
        async with _cliente() as http:
            with pytest.raises(ErroDependenciaIndisponivel):
                await ClientePedidosHttp(http).obter("ped-1", token="t")
    assert rota.call_count == 1


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(200, text="nao e json"),
        httpx.Response(200, json={"id": "ped-1"}),
        httpx.Response(200, json={**PEDIDO, "valor_total_centavos": "4590"}),
    ],
)
async def test_corpo_fora_do_formato_vira_503(resposta: httpx.Response) -> None:
    with respx.mock(base_url=URL) as rotas:
        rotas.get("/pedidos/ped-1").mock(return_value=resposta)
        async with _cliente() as http:
            with pytest.raises(ErroDependenciaIndisponivel):
                await ClientePedidosHttp(http).obter("ped-1", token="t")
