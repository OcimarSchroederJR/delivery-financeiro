from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from plataforma.circuit_breaker import CircuitBreaker, CircuitoAberto
from plataforma.cliente_http import ClienteHttp
from plataforma.correlation import HEADER_CORRELATION_ID, correlation_id_em
from plataforma.erros import ErroDependenciaIndisponivel

BASE = "http://pedidos.teste"


@pytest.fixture
async def cliente() -> AsyncIterator[ClienteHttp]:
    async with ClienteHttp("pedidos", BASE, espera_base=0, espera_maxima=0) as cliente:
        yield cliente


@respx.mock
async def test_get_ok_propaga_correlation_id_e_token(cliente: ClienteHttp) -> None:
    rota = respx.get(f"{BASE}/pedidos/1").mock(return_value=httpx.Response(200, json={"id": "1"}))
    with correlation_id_em("cid-xyz"):
        resposta = await cliente.get("/pedidos/1", token="tok")
    assert resposta.json() == {"id": "1"}
    enviada = rota.calls.last.request
    assert enviada.headers[HEADER_CORRELATION_ID] == "cid-xyz"
    assert enviada.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_404_e_devolvido_sem_retry(cliente: ClienteHttp) -> None:
    rota = respx.get(f"{BASE}/pedidos/x").mock(return_value=httpx.Response(404))
    resposta = await cliente.get("/pedidos/x")
    assert resposta.status_code == 404
    assert rota.call_count == 1


@respx.mock
async def test_get_com_5xx_faz_3_tentativas_e_vira_503(cliente: ClienteHttp) -> None:
    rota = respx.get(f"{BASE}/pedidos/1").mock(return_value=httpx.Response(502))
    with pytest.raises(ErroDependenciaIndisponivel) as erro:
        await cliente.get("/pedidos/1")
    assert rota.call_count == 3
    assert erro.value.dependencia == "pedidos"


@respx.mock
async def test_get_recupera_apos_timeout(cliente: ClienteHttp) -> None:
    rota = respx.get(f"{BASE}/pedidos/1").mock(
        side_effect=[httpx.ConnectTimeout("lento"), httpx.Response(200, json={})]
    )
    resposta = await cliente.get("/pedidos/1")
    assert resposta.status_code == 200
    assert rota.call_count == 2


@respx.mock
async def test_post_sem_idempotency_key_nao_repete(cliente: ClienteHttp) -> None:
    rota = respx.post(f"{BASE}/coisas").mock(return_value=httpx.Response(503))
    with pytest.raises(ErroDependenciaIndisponivel):
        await cliente.post("/coisas", json={})
    assert rota.call_count == 1


@respx.mock
async def test_post_com_idempotency_key_repete_e_envia_header(cliente: ClienteHttp) -> None:
    rota = respx.post(f"{BASE}/estornos").mock(
        side_effect=[httpx.Response(500), httpx.Response(201, json={"id": "e1"})]
    )
    resposta = await cliente.post("/estornos", json={}, idempotency_key="disputa-1")
    assert resposta.status_code == 201
    assert rota.call_count == 2
    assert rota.calls.last.request.headers["Idempotency-Key"] == "disputa-1"


@respx.mock
async def test_circuito_abre_e_bloqueia_sem_chamar_a_rede() -> None:
    breaker = CircuitBreaker("pedidos", limite_falhas=2)
    rota = respx.get(f"{BASE}/pedidos/1").mock(side_effect=httpx.ConnectError("recusado"))
    async with ClienteHttp(
        "pedidos", BASE, breaker=breaker, max_tentativas=1, espera_base=0
    ) as cliente:
        for _ in range(2):
            with pytest.raises(ErroDependenciaIndisponivel):
                await cliente.get("/pedidos/1")
        with pytest.raises(CircuitoAberto):
            await cliente.get("/pedidos/1")
    assert rota.call_count == 2


@respx.mock
async def test_404_nao_conta_como_falha_do_circuito() -> None:
    breaker = CircuitBreaker("pedidos", limite_falhas=1)
    respx.get(f"{BASE}/pedidos/x").mock(return_value=httpx.Response(404))
    async with ClienteHttp("pedidos", BASE, breaker=breaker) as cliente:
        await cliente.get("/pedidos/x")
        await cliente.get("/pedidos/x")
    assert breaker.estado == "fechado"


@respx.mock
async def test_loga_antes_e_depois_com_dependencia_status_e_duracao(cliente: ClienteHttp) -> None:
    respx.get(f"{BASE}/pedidos/1").mock(return_value=httpx.Response(200, json={}))
    with capture_logs() as logs:
        await cliente.get("/pedidos/1", token="segredo-nao-logar")
    antes, depois = (log for log in logs if log["event"].startswith("http_saida"))
    assert antes["event"] == "http_saida_iniciada"
    assert antes["dependencia"] == "pedidos"
    assert (antes["metodo"], antes["rota"]) == ("GET", "/pedidos/1")
    assert depois["event"] == "http_saida_concluida"
    assert depois["status"] == 200
    assert isinstance(depois["duracao_ms"], float)
    assert "segredo-nao-logar" not in str(logs)
