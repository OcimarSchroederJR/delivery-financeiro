"""Middleware ASGI de correlation id e log de requisição recebida."""

import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from plataforma.correlation import (
    HEADER_CORRELATION_ID,
    definir_correlation_id,
    normalizar_correlation_id,
)
from plataforma.logs import obter_logger

_log = obter_logger(__name__)


class MiddlewareCorrelationId:
    """Lê ``X-Correlation-ID`` (ou gera), guarda no contextvar e devolve no header.

    Registra uma linha ``requisicao_http`` por requisição (exceto ``/saude/*``).
    """

    def __init__(
        self, app: ASGIApp, *, prefixos_silenciosos: tuple[str, ...] = ("/saude",)
    ) -> None:
        self.app = app
        self._silenciosos = prefixos_silenciosos

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = normalizar_correlation_id(Headers(scope=scope).get(HEADER_CORRELATION_ID))
        definir_correlation_id(correlation_id)
        inicio = time.perf_counter()
        status = 500

        async def enviar(mensagem: Message) -> None:
            nonlocal status
            if mensagem["type"] == "http.response.start":
                status = mensagem["status"]
                cabecalhos = MutableHeaders(scope=mensagem)
                if HEADER_CORRELATION_ID not in cabecalhos:
                    cabecalhos.append(HEADER_CORRELATION_ID, correlation_id)
            await send(mensagem)

        try:
            await self.app(scope, receive, enviar)
        finally:
            caminho: str = scope["path"]
            if not any(prefixo in caminho for prefixo in self._silenciosos):
                _log.info(
                    "requisicao_http",
                    metodo=scope["method"],
                    rota=caminho,
                    status=status,
                    duracao_ms=round((time.perf_counter() - inicio) * 1000, 1),
                )
