"""Peças comuns aos mocks: app base e injeção de falhas controlável."""

import asyncio
import os
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, Field

from plataforma.api.app import CicloDeVida
from plataforma.api.correlation import MiddlewareCorrelationId
from plataforma.api.erros import registrar_tratadores_de_erro
from plataforma.api.saude import criar_router_saude
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import configurar_logs


class ModoFalha(StrEnum):
    NORMAL = "normal"
    ERRO = "erro"
    LENTO = "lento"


class ConfigFalha(BaseModel):
    modo: ModoFalha = ModoFalha.NORMAL
    segundos: float = Field(default=5.0, ge=0, le=60)


async def aplicar_falha(requisicao: Request) -> None:
    """Dependência das rotas de negócio dos mocks: simula queda ou lentidão."""
    falha: ConfigFalha = requisicao.app.state.falha
    if falha.modo is ModoFalha.ERRO:
        raise ErroDependenciaIndisponivel(requisicao.app.title, "Falha simulada pelo mock.")
    if falha.modo is ModoFalha.LENTO:
        await asyncio.sleep(falha.segundos)


def router_com_falhas() -> APIRouter:
    return APIRouter(dependencies=[Depends(aplicar_falha)])


def criar_app_mock(
    nome: str, titulo: str, descricao: str, *, ciclo_de_vida: CicloDeVida | None = None
) -> FastAPI:
    formato: Literal["json", "console"] = (
        "json" if os.environ.get("LOG_FORMATO", "console") == "json" else "console"
    )
    configurar_logs(nome, formato=formato)
    app = FastAPI(title=titulo, description=descricao, version="1.0.0", lifespan=ciclo_de_vida)
    app.state.falha = ConfigFalha()
    registrar_tratadores_de_erro(app)
    app.add_middleware(MiddlewareCorrelationId)
    app.include_router(criar_router_saude())

    @app.put("/_controle/falha", tags=["controle"], summary="Liga/desliga falha simulada")
    async def definir_falha(falha: ConfigFalha) -> ConfigFalha:
        app.state.falha = falha
        return falha

    return app
