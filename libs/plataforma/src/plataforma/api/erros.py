"""Tratadores globais de erro do FastAPI (spec §3.4 e §5).

Todo erro sai como ``{"erro": true, "mensagem", "codigo", "correlation_id"}``
mais campos extras de ``ErroAplicacao.detalhes``. 500 nunca expõe stack trace e
422 de validação nunca ecoa o valor recebido (pode ser número de cartão).
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from plataforma.correlation import HEADER_CORRELATION_ID, obter_correlation_id
from plataforma.erros import ErroAplicacao
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

CODIGOS_POR_STATUS: dict[int, str] = {
    400: "REQUISICAO_INVALIDA",
    401: "NAO_AUTENTICADO",
    403: "ACESSO_NEGADO",
    404: "RECURSO_NAO_ENCONTRADO",
    405: "METODO_NAO_PERMITIDO",
    409: "CONFLITO",
    415: "TIPO_DE_CONTEUDO_NAO_SUPORTADO",
    422: "REQUISICAO_INVALIDA",
    503: "SERVICO_INDISPONIVEL",
}


class CorpoErro(BaseModel):
    """Schema do corpo de erro (documentação OpenAPI)."""

    model_config = ConfigDict(extra="allow")

    erro: bool = True
    mensagem: str
    codigo: str
    correlation_id: str | None = None


def corpo_erro(mensagem: str, codigo: str, **extras: Any) -> dict[str, Any]:
    return {
        **extras,
        "erro": True,
        "mensagem": mensagem,
        "codigo": codigo,
        "correlation_id": obter_correlation_id(),
    }


def resposta_erro(
    status: int,
    mensagem: str,
    codigo: str,
    *,
    headers: dict[str, str] | None = None,
    **extras: Any,
) -> JSONResponse:
    cabecalhos = dict(headers or {})
    correlation_id = obter_correlation_id()
    if correlation_id is not None:
        cabecalhos[HEADER_CORRELATION_ID] = correlation_id
    return JSONResponse(
        corpo_erro(mensagem, codigo, **extras), status_code=status, headers=cabecalhos
    )


def respostas_erro(*status: int) -> dict[int | str, dict[str, Any]]:
    """Para ``responses=`` das rotas: documenta os erros no OpenAPI."""
    return {codigo: {"model": CorpoErro} for codigo in status}


async def _tratar_erro_aplicacao(_requisicao: Request, erro: Exception) -> Response:
    if not isinstance(erro, ErroAplicacao):  # pragma: no cover - registro garante o tipo
        raise erro
    nivel = _log.warning if erro.status_http >= 500 else _log.info
    nivel("erro_tratado", codigo=erro.codigo, status=erro.status_http)
    return resposta_erro(erro.status_http, erro.mensagem, erro.codigo, **erro.detalhes)


async def _tratar_http(_requisicao: Request, erro: Exception) -> Response:
    if not isinstance(erro, StarletteHTTPException):  # pragma: no cover
        raise erro
    mensagem = erro.detail if isinstance(erro.detail, str) else "Erro na requisição."
    codigo = CODIGOS_POR_STATUS.get(erro.status_code, "ERRO_HTTP")
    return resposta_erro(erro.status_code, mensagem, codigo, headers=dict(erro.headers or {}))


async def _tratar_validacao(_requisicao: Request, erro: Exception) -> Response:
    if not isinstance(erro, RequestValidationError):  # pragma: no cover
        raise erro
    detalhes = [
        {
            "campo": ".".join(str(parte) for parte in item.get("loc", ())),
            "mensagem": str(item.get("msg", "")),
        }
        for item in erro.errors()
    ]
    return resposta_erro(
        422, "Dados de entrada inválidos.", "REQUISICAO_INVALIDA", detalhes=detalhes
    )


async def _tratar_inesperado(_requisicao: Request, erro: Exception) -> Response:
    _log.error("erro_inesperado", erro=type(erro).__name__, exc_info=erro)
    return resposta_erro(500, "Erro interno do servidor.", "ERRO_INTERNO")


def registrar_tratadores_de_erro(app: FastAPI) -> None:
    app.add_exception_handler(ErroAplicacao, _tratar_erro_aplicacao)
    app.add_exception_handler(StarletteHTTPException, _tratar_http)
    app.add_exception_handler(RequestValidationError, _tratar_validacao)
    app.add_exception_handler(Exception, _tratar_inesperado)
