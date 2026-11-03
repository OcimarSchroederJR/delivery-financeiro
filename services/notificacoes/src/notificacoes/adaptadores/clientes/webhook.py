"""Entrega HTTP dos webhooks (spec §4.2: sucesso = 2xx em até 5 s).

Cliente próprio (não o ``ClienteHttp``): a URL muda por assinatura, não há
retry interno (o retry é das filas com TTL) nem circuit breaker único (um
inscrito fora não pode bloquear os outros). Redirecionamentos não são
seguidos. O limite de 5 s vale para a chamada inteira (``asyncio.timeout``).

Fora de ``local``/``teste`` (``permitir_rede_interna=False``) o host é resolvido
antes da chamada; se **qualquer** IP resolvido for interno, a entrega é
recusada. A conexão vai para o IP validado (``Host`` e SNI com o nome original),
sem uma segunda resolução que um DNS rebinding pudesse trocar.
"""

import asyncio
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from notificacoes.aplicacao.portas import ResultadoEntrega
from notificacoes.dominio.url_webhook import IpQualquer, ip_bloqueado, ip_do_host
from plataforma.correlation import hook_httpx_correlation
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

AGENTE = "financeiro-eq5-notificacoes/0.1"
DEPENDENCIA = "webhook"


Resolvedor = Callable[[str, int], Awaitable[list[str]]]


async def resolver_dns(host: str, porta: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]).split("%", 1)[0] for info in infos))


class DestinoBloqueado(Exception):
    """O host do webhook é (ou resolve para) um IP interno."""


def _rota_para_log(url: str) -> str:
    """Só esquema e host: path, query e porta podem carregar tokens do receptor."""
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.hostname or ''}"


class EntregadorHttpx:
    """Implementa ``EntregadorDeWebhook``."""

    def __init__(
        self,
        *,
        timeout_segundos: float = 5.0,
        permitir_rede_interna: bool = False,
        resolver: Resolvedor = resolver_dns,
        transporte: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_segundos
        self._permitir_rede_interna = permitir_rede_interna
        self._resolver = resolver
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
                destino, extras, extensoes = await self._destino(url)
                resposta = await self._cliente.post(
                    destino,
                    content=corpo,
                    headers={**cabecalhos, **extras},
                    extensions=extensoes,
                )
            status = resposta.status_code
        except TimeoutError:
            erro = f"Tempo esgotado ({self._timeout:g} s)."
        except DestinoBloqueado as falha:
            erro = str(falha)
        except OSError as falha:
            erro = f"Falha de DNS ({type(falha).__name__})."
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

    async def _destino(self, url: str) -> tuple[str, dict[str, str], dict[str, str]]:
        """URL a chamar, headers e extensões extras (IP fixado fora de ambiente local)."""
        if self._permitir_rede_interna:
            return url, {}, {}
        original = httpx.URL(url)
        host = original.host
        literal = ip_do_host(host)
        if literal is not None:
            ips: list[IpQualquer] = [literal]
        else:
            resolvidos = await self._resolver(host, original.port or _porta_padrao(original))
            ips = [ip for texto in resolvidos if (ip := ip_do_host(texto)) is not None]
        if not ips or any(ip_bloqueado(ip) for ip in ips):
            raise DestinoBloqueado("Destino bloqueado: o host resolve para um IP interno.")
        if literal is not None:
            return url, {}, {}
        fixado = original.copy_with(host=str(ips[0]))
        return str(fixado), {"Host": original.netloc.decode()}, {"sni_hostname": host}

    async def fechar(self) -> None:
        await self._cliente.aclose()


def _porta_padrao(url: httpx.URL) -> int:
    return 443 if url.scheme == "https" else 80
