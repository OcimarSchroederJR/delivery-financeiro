"""Entrega HTTP dos webhooks (spec §4.2: sucesso = 2xx em até 5 s).

Cliente próprio (não o ``ClienteHttp``): a URL muda por assinatura, não há
retry interno (o retry é das filas com TTL) nem circuit breaker único (um
inscrito fora não pode bloquear os outros). Redirecionamentos não são
seguidos. O limite de 5 s vale para a chamada inteira (``asyncio.timeout``).
"""

import asyncio
import time
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from notificacoes.aplicacao.portas import ResultadoEntrega
from plataforma.correlation import hook_httpx_correlation
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

AGENTE = "financeiro-eq5-notificacoes/0.1"
DEPENDENCIA = "webhook"


def _rota_para_log(url: str) -> str:
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc}{partes.path}"


class EntregadorHttpx:
    """Implementa ``EntregadorDeWebhook``."""

    def __init__(
        self,
        *,
        timeout_segundos: float = 5.0,
        transporte: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_segundos
        self._cliente = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_segundos),
            follow_redirects=False,
            transport=transporte,
            headers={"User-Agent": AGENTE},
            event_hooks={"request": [hook_httpx_correlation]},
        )

    async def entregar(
        self, url: str, corpo: bytes, cabecalhos: Mapping[str, str]
    ) -> ResultadoEntrega:
        rota = _rota_para_log(url)
        _log.info("http_saida_iniciada", dependencia=DEPENDENCIA, metodo="POST", rota=rota)
        inicio = time.perf_counter()
        erro: str | None = None
        status: int | None = None
        try:
            async with asyncio.timeout(self._timeout):
                resposta = await self._cliente.post(url, content=corpo, headers=dict(cabecalhos))
            status = resposta.status_code
        except TimeoutError:
            erro = f"Tempo esgotado ({self._timeout:g} s)."
        except (httpx.HTTPError, httpx.InvalidURL) as falha:
            erro = type(falha).__name__
        duracao_ms = int((time.perf_counter() - inicio) * 1000)
        if erro is not None:
            _log.warning(
                "http_saida_falhou",
                dependencia=DEPENDENCIA,
                metodo="POST",
                rota=rota,
                erro=erro,
                duracao_ms=duracao_ms,
            )
            return ResultadoEntrega(status_http=None, duracao_ms=duracao_ms, erro=erro)
        _log.info(
            "http_saida_concluida",
            dependencia=DEPENDENCIA,
            metodo="POST",
            rota=rota,
            status=status,
            duracao_ms=duracao_ms,
        )
        return ResultadoEntrega(status_http=status, duracao_ms=duracao_ms)

    async def fechar(self) -> None:
        await self._cliente.aclose()
