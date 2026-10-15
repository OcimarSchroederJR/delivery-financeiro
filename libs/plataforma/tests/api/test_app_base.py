from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import SecretStr

from plataforma.api.app import criar_app_base
from plataforma.api.auth import UsuarioAtual, exigir_papeis
from plataforma.api.paginacao import Pagina, Paginacao
from plataforma.auth import EmissorTokenServico, Papel, Usuario
from plataforma.config import ConfiguracaoBase
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
    GeradorDeTokens,
    criar_verificador_de_teste,
)

GERADOR = GeradorDeTokens()


def _app() -> FastAPI:
    config = ConfiguracaoBase(
        servico="teste", token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE)
    )
    app = criar_app_base(
        config, titulo="Teste", versao="0.0.1", verificador=criar_verificador_de_teste(GERADOR)
    )

    @app.get("/v1/eu")
    async def eu(usuario: UsuarioAtual) -> dict[str, str]:
        return {"id": usuario.id, "papel": usuario.papel}

    @app.get("/v1/so-admin-ou-servico")
    async def restrito(
        usuario: Annotated[Usuario, Depends(exigir_papeis(Papel.ADMIN, Papel.SERVICO))],
    ) -> dict[str, str]:
        return {"papel": usuario.papel}

    @app.get("/v1/itens")
    async def itens(paginacao: Paginacao) -> Pagina[int]:
        todos = list(range(57))
        fatia = todos[paginacao.deslocamento : paginacao.deslocamento + paginacao.tamanho]
        return Pagina[int].criar(fatia, paginacao, total=len(todos))

    return app


@pytest.fixture
async def cliente() -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
        yield http


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token_servico() -> str:
    return EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes").emitir()


async def test_app_base_tem_saude_e_formato_de_erro(cliente: httpx.AsyncClient) -> None:
    assert (await cliente.get("/saude/vivo")).status_code == 200
    resposta = await cliente.get("/nao-existe")
    assert resposta.json()["erro"] is True
    assert resposta.headers["X-Correlation-ID"]


async def test_sem_token_401(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/v1/eu")
    assert resposta.status_code == 401
    assert resposta.json()["codigo"] == "NAO_AUTENTICADO"


async def test_token_invalido_401(cliente: httpx.AsyncClient) -> None:
    assert (await cliente.get("/v1/eu", headers=_bearer("lixo"))).status_code == 401


async def test_usuario_atual_com_token_da_eq1(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/v1/eu", headers=_bearer(GERADOR.emitir("c1", "cliente")))
    assert resposta.status_code == 200
    assert resposta.json() == {"id": "c1", "papel": "cliente"}


async def test_usuario_atual_recusa_token_de_servico(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/v1/eu", headers=_bearer(_token_servico()))
    assert resposta.status_code == 403
    assert resposta.json()["codigo"] == "ACESSO_NEGADO"


async def test_exigir_papeis(cliente: httpx.AsyncClient) -> None:
    rota = "/v1/so-admin-ou-servico"
    admin = GERADOR.emitir("a1", "admin")
    cliente_final = GERADOR.emitir("c1", "cliente")
    assert (await cliente.get(rota, headers=_bearer(_token_servico()))).status_code == 200
    assert (await cliente.get(rota, headers=_bearer(admin))).status_code == 200
    assert (await cliente.get(rota, headers=_bearer(cliente_final))).status_code == 403


async def test_paginacao_padrao(cliente: httpx.AsyncClient) -> None:
    corpo = (await cliente.get("/v1/itens")).json()
    assert (corpo["pagina"], corpo["tamanho"], corpo["total"]) == (1, 20, 57)
    assert corpo["itens"] == list(range(20))


async def test_paginacao_ultima_pagina(cliente: httpx.AsyncClient) -> None:
    corpo = (await cliente.get("/v1/itens", params={"pagina": 3, "tamanho": 20})).json()
    assert corpo["itens"] == list(range(40, 57))


@pytest.mark.parametrize("params", [{"tamanho": 101}, {"tamanho": 0}, {"pagina": 0}])
async def test_paginacao_fora_dos_limites(
    cliente: httpx.AsyncClient, params: dict[str, int]
) -> None:
    resposta = await cliente.get("/v1/itens", params=params)
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "REQUISICAO_INVALIDA"


async def test_openapi_documenta_bearer(cliente: httpx.AsyncClient) -> None:
    esquema = (await cliente.get("/openapi.json")).json()
    assert "HTTPBearer" in esquema["components"]["securitySchemes"]
