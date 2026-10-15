"""Fábrica do app FastAPI com tudo que é comum aos serviços."""

from collections.abc import Callable, Mapping, MutableMapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI

from plataforma.api.auth import configurar_autenticacao
from plataforma.api.correlation import MiddlewareCorrelationId
from plataforma.api.erros import registrar_tratadores_de_erro
from plataforma.api.saude import Verificacao, criar_router_saude
from plataforma.auth import VerificadorDeToken
from plataforma.config import ConfiguracaoBase

CicloDeVida = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def _ignorar_saude(scope: MutableMapping[str, Any]) -> bool:
    return "/saude/" in str(scope.get("path", ""))


def criar_app_base(
    config: ConfiguracaoBase,
    *,
    titulo: str,
    versao: str,
    descricao: str = "",
    verificacoes: Mapping[str, Verificacao] | None = None,
    verificador: VerificadorDeToken | None = None,
    ciclo_de_vida: CicloDeVida | None = None,
) -> FastAPI:
    """App com middleware de correlation id, tratadores de erro, rotas de saúde e auth.

    Construir o app não abre conexões: recursos são criados no ``ciclo_de_vida``.
    """
    app = FastAPI(
        title=titulo,
        version=versao,
        description=descricao,
        root_path=config.root_path,
        lifespan=ciclo_de_vida,
        telemetry={"logs": False, "metrics": False, "exclude": _ignorar_saude},
    )
    registrar_tratadores_de_erro(app)
    app.add_middleware(MiddlewareCorrelationId)
    app.include_router(criar_router_saude(verificacoes))
    if verificador is not None:
        configurar_autenticacao(app, verificador)
    return app
