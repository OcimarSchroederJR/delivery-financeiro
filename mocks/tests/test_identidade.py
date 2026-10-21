from collections.abc import AsyncIterator

import httpx
import pytest

from mocks_equipes.identidade import criar_app
from plataforma.auth import Papel, VerificadorJwks


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=criar_app())
    async with httpx.AsyncClient(transport=transporte, base_url="http://identidade") as cliente:
        yield cliente


async def test_token_emitido_e_validado_pelo_jwks(http: httpx.AsyncClient) -> None:
    resposta = await http.post("/tokens", json={"sub": "cliente-1", "papel": "cliente"})
    assert resposta.status_code == 201
    token = resposta.json()["access_token"]
    verificador = VerificadorJwks("http://identidade/.well-known/jwks.json", cliente=http)
    usuario = await verificador.verificar(token)
    assert (usuario.id, usuario.papel) == ("cliente-1", Papel.CLIENTE)


async def test_papel_servico_nao_pode_ser_emitido(http: httpx.AsyncClient) -> None:
    resposta = await http.post("/tokens", json={"sub": "x", "papel": "servico"})
    assert resposta.status_code == 422
    assert resposta.json()["erro"] is True


async def test_perfil_padrao_e_atualizado_pelo_token(http: httpx.AsyncClient) -> None:
    assert (await http.get("/perfis/cliente-9")).json()["email"] == "cliente-9@exemplo.com"
    await http.post(
        "/tokens", json={"sub": "cliente-9", "papel": "cliente", "email": "nove@teste.com"}
    )
    perfil = (await http.get("/perfis/cliente-9")).json()
    assert perfil == {
        "id": "cliente-9",
        "nome": "Usuário cliente-9",
        "email": "nove@teste.com",
        "papel": "cliente",
    }


async def test_put_perfil(http: httpx.AsyncClient) -> None:
    resposta = await http.put("/perfis/loja-1", json={"email": "loja@teste.com", "papel": "loja"})
    assert resposta.json()["email"] == "loja@teste.com"


async def test_falha_simulada(http: httpx.AsyncClient) -> None:
    await http.put("/_controle/falha", json={"modo": "erro"})
    resposta = await http.get("/perfis/x")
    assert resposta.status_code == 503
    assert resposta.json()["codigo"] == "DEPENDENCIA_INDISPONIVEL"
    assert (await http.get("/saude/vivo")).status_code == 200
    await http.put("/_controle/falha", json={"modo": "normal"})
    assert (await http.get("/perfis/x")).status_code == 200


async def test_lentidao_simulada(http: httpx.AsyncClient) -> None:
    await http.put("/_controle/falha", json={"modo": "lento", "segundos": 0.01})
    assert (await http.get("/.well-known/jwks.json")).status_code == 200
