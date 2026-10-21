"""Correlation ID: contextvar, normalização e hook para httpx (spec §3.4, §6)."""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

import httpx

HEADER_CORRELATION_ID = "X-Correlation-ID"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_FORMATO_VALIDO = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def novo_correlation_id() -> str:
    return str(uuid.uuid4())


def obter_correlation_id() -> str | None:
    return _correlation_id.get()


def definir_correlation_id(valor: str | None) -> Token[str | None]:
    return _correlation_id.set(valor)


def normalizar_correlation_id(valor: str | None) -> str:
    """Aceita o valor recebido se for seguro para log; senão gera um novo."""
    if valor is not None and _FORMATO_VALIDO.fullmatch(valor):
        return valor
    return novo_correlation_id()


@contextmanager
def correlation_id_em(valor: str | None) -> Iterator[str]:
    """Define o correlation id durante o bloco (uso em workers e consumidores)."""
    efetivo = normalizar_correlation_id(valor)
    token = _correlation_id.set(efetivo)
    try:
        yield efetivo
    finally:
        _correlation_id.reset(token)


async def hook_httpx_correlation(requisicao: httpx.Request) -> None:
    """Event hook de request do httpx: propaga o correlation id atual."""
    valor = _correlation_id.get()
    if valor is not None and HEADER_CORRELATION_ID not in requisicao.headers:
        requisicao.headers[HEADER_CORRELATION_ID] = valor
