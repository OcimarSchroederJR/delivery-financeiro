"""Health checks: ``/saude/vivo`` (processo) e ``/saude/pronto`` (banco + broker)."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping

import aio_pika
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from plataforma.api.erros import resposta_erro
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

Verificacao = Callable[[], Awaitable[None]]
"""Função assíncrona que levanta exceção se a dependência não está ok."""


def verificacao_banco(engine: AsyncEngine) -> Verificacao:
    async def verificar() -> None:
        async with engine.connect() as conexao:
            await conexao.execute(text("SELECT 1"))

    return verificar


def verificacao_broker(url_amqp: str, *, timeout: float = 2.0) -> Verificacao:
    async def verificar() -> None:
        conexao = await aio_pika.connect(url_amqp, timeout=timeout)
        await conexao.close()

    return verificar


def criar_router_saude(
    verificacoes: Mapping[str, Verificacao] | None = None, *, timeout: float = 3.0
) -> APIRouter:
    checks = dict(verificacoes or {})
    router = APIRouter(prefix="/saude", tags=["saude"])

    @router.get("/vivo", summary="Liveness: o processo está de pé")
    async def vivo() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/pronto", summary="Readiness: banco e broker acessíveis")
    async def pronto() -> JSONResponse:
        resultados: dict[str, str] = {}
        for nome, verificar in checks.items():
            try:
                await asyncio.wait_for(verificar(), timeout=timeout)
                resultados[nome] = "ok"
            except Exception as erro:
                resultados[nome] = "falhou"
                _log.warning("verificacao_saude_falhou", verificacao=nome, erro=type(erro).__name__)
        if all(valor == "ok" for valor in resultados.values()):
            return JSONResponse({"status": "ok", "verificacoes": resultados})
        return resposta_erro(
            503, "Serviço não está pronto.", "SERVICO_NAO_PRONTO", verificacoes=resultados
        )

    return router
