"""Mock da Equipe 1 (Identidade): JWT RS256 de teste, JWKS e perfis com e-mail."""

import secrets
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from mocks_equipes.comum import criar_app_mock, router_com_falhas
from plataforma.testes.tokens import GeradorDeTokens

PapelMock = Literal["cliente", "loja", "entregador", "admin"]


class PedidoDeToken(BaseModel):
    sub: str = Field(min_length=1, max_length=100)
    papel: PapelMock
    email: str | None = None
    nome: str | None = None
    validade_segundos: int = Field(default=3600, ge=1, le=86_400)


class Token(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - tipo do token, não segredo
    expires_in: int


class Perfil(BaseModel):
    id: str
    nome: str
    email: str
    papel: PapelMock | None = None


class AlteracaoDePerfil(BaseModel):
    nome: str | None = None
    email: str | None = None
    papel: PapelMock | None = None


def _perfil_padrao(perfil_id: str) -> Perfil:
    return Perfil(id=perfil_id, nome=f"Usuário {perfil_id}", email=f"{perfil_id}@exemplo.com")


def criar_app() -> FastAPI:
    app = criar_app_mock(
        "mock-identidade",
        "Mock Identidade (Eq. 1)",
        "Emite JWT RS256 de teste, publica o JWKS e serve perfis.",
    )
    gerador = GeradorDeTokens(kid=f"mock-identidade-{secrets.token_hex(4)}")
    perfis: dict[str, Perfil] = {}
    rotas = router_com_falhas()

    @rotas.post("/tokens", status_code=201, response_model=Token)
    async def emitir_token(pedido: PedidoDeToken) -> Token:
        atual = perfis.get(pedido.sub, _perfil_padrao(pedido.sub))
        perfis[pedido.sub] = atual.model_copy(
            update={
                "papel": pedido.papel,
                "email": pedido.email or atual.email,
                "nome": pedido.nome or atual.nome,
            }
        )
        token = gerador.emitir(pedido.sub, pedido.papel, validade_segundos=pedido.validade_segundos)
        return Token(access_token=token, expires_in=pedido.validade_segundos)

    @rotas.get("/.well-known/jwks.json")
    async def jwks() -> dict[str, object]:
        return gerador.jwks()

    @rotas.get("/perfis/{perfil_id}", response_model=Perfil)
    async def obter_perfil(perfil_id: str) -> Perfil:
        return perfis.get(perfil_id, _perfil_padrao(perfil_id))

    @rotas.put("/perfis/{perfil_id}", response_model=Perfil)
    async def alterar_perfil(perfil_id: str, alteracao: AlteracaoDePerfil) -> Perfil:
        atual = perfis.get(perfil_id, _perfil_padrao(perfil_id))
        perfis[perfil_id] = atual.model_copy(update=alteracao.model_dump(exclude_none=True))
        return perfis[perfil_id]

    app.include_router(rotas)
    return app


app = criar_app()
