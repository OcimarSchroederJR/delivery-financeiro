"""Cliente HTTP base para outras equipes (spec §5 e §6).

- timeout em toda tentativa e um prazo total (padrão 8 s) por chamada lógica, que
  corta os retries;
- retry (tenacity, backoff exponencial com jitter) só em GET/HEAD/OPTIONS e em
  requisições com ``Idempotency-Key``; nunca em 4xx;
- circuit breaker por dependência envolvendo a chamada lógica (com retries);
- uma linha de log antes e outra depois de cada tentativa;
- correlation id propagado e ``traceparent`` via instrumentação do httpx.

Respostas < 500 são devolvidas ao chamador (o adapter decide o que 404/409 significam).
Timeout, erro de rede, outro erro do httpx (ex.: corpo corrompido), 5xx após retries
ou prazo total esgotado viram ``ErroDependenciaIndisponivel`` (503); circuito aberto
levanta ``CircuitoAberto``.
"""

import asyncio
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from plataforma.circuit_breaker import CircuitBreaker, CircuitoAberto
from plataforma.correlation import hook_httpx_correlation
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})
TIMEOUT_PADRAO = httpx.Timeout(3.0, connect=1.0)
PRAZO_TOTAL_PADRAO = 8.0


class _RespostaDeErroDoServidor(Exception):
    def __init__(self, resposta: httpx.Response) -> None:
        self.resposta = resposta
        super().__init__(f"HTTP {resposta.status_code}")


def _e_falha_da_dependencia(erro: Exception) -> bool:
    return isinstance(erro, httpx.HTTPError | _RespostaDeErroDoServidor | TimeoutError)


class ClienteHttp:
    def __init__(
        self,
        dependencia: str,
        url_base: str,
        *,
        timeout: httpx.Timeout = TIMEOUT_PADRAO,
        prazo_total: float | None = PRAZO_TOTAL_PADRAO,
        breaker: CircuitBreaker | None = None,
        max_tentativas: int = 3,
        espera_base: float = 0.2,
        espera_maxima: float = 2.0,
        transporte: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.dependencia = dependencia
        self.breaker = breaker or CircuitBreaker(dependencia)
        self.prazo_total = prazo_total
        self._max_tentativas = max_tentativas
        self._espera_base = espera_base
        self._espera_maxima = espera_maxima
        self._cliente = httpx.AsyncClient(
            base_url=url_base,
            timeout=timeout,
            transport=transporte,
            event_hooks={"request": [hook_httpx_correlation]},
        )

    async def requisitar(
        self,
        metodo: str,
        rota: str,
        *,
        token: str | None = None,
        idempotency_key: str | None = None,
        json: Any = None,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        metodo = metodo.upper()
        cabecalhos = dict(headers or {})
        if token is not None:
            cabecalhos["Authorization"] = f"Bearer {token}"
        if idempotency_key is not None:
            cabecalhos["Idempotency-Key"] = idempotency_key
        repetivel = metodo in METODOS_SEGUROS or idempotency_key is not None
        tentativas = self._max_tentativas if repetivel else 1

        async def chamar_com_prazo() -> httpx.Response:
            async with asyncio.timeout(self.prazo_total):
                return await chamar_com_retry()

        async def chamar_com_retry() -> httpx.Response:
            async for tentativa in AsyncRetrying(
                stop=stop_after_attempt(tentativas),
                wait=wait_random_exponential(multiplier=self._espera_base, max=self._espera_maxima),
                retry=retry_if_exception_type((httpx.TransportError, _RespostaDeErroDoServidor)),
                reraise=True,
            ):
                with tentativa:
                    resposta = await self._enviar(
                        metodo,
                        rota,
                        numero=tentativa.retry_state.attempt_number,
                        json=json,
                        params=params,
                        headers=cabecalhos,
                    )
                    if resposta.status_code >= 500:
                        raise _RespostaDeErroDoServidor(resposta)
                    return resposta
            raise RuntimeError("tenacity encerrou sem resultado")  # pragma: no cover

        try:
            return await self.breaker.executar(chamar_com_prazo, e_falha=_e_falha_da_dependencia)
        except CircuitoAberto:
            _log.warning(
                "http_saida_bloqueada",
                dependencia=self.dependencia,
                metodo=metodo,
                rota=rota,
            )
            raise
        except TimeoutError as erro:
            _log.warning(
                "http_saida_prazo_esgotado",
                dependencia=self.dependencia,
                metodo=metodo,
                rota=rota,
                prazo_total=self.prazo_total,
            )
            raise ErroDependenciaIndisponivel(self.dependencia) from erro
        except (httpx.HTTPError, _RespostaDeErroDoServidor) as erro:
            raise ErroDependenciaIndisponivel(self.dependencia) from erro

    async def _enviar(
        self,
        metodo: str,
        rota: str,
        *,
        numero: int,
        json: Any,
        params: Mapping[str, str | int] | None,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        _log.info(
            "http_saida_iniciada",
            dependencia=self.dependencia,
            metodo=metodo,
            rota=rota,
            tentativa=numero,
        )
        inicio = time.perf_counter()
        try:
            resposta = await self._cliente.request(
                metodo, rota, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as erro:
            _log.warning(
                "http_saida_falhou",
                dependencia=self.dependencia,
                metodo=metodo,
                rota=rota,
                tentativa=numero,
                erro=type(erro).__name__,
                duracao_ms=round((time.perf_counter() - inicio) * 1000, 1),
            )
            raise
        _log.info(
            "http_saida_concluida",
            dependencia=self.dependencia,
            metodo=metodo,
            rota=rota,
            tentativa=numero,
            status=resposta.status_code,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 1),
        )
        return resposta

    async def get(
        self,
        rota: str,
        *,
        token: str | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> httpx.Response:
        return await self.requisitar("GET", rota, token=token, params=params)

    async def post(
        self,
        rota: str,
        *,
        json: Any = None,
        token: str | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        return await self.requisitar(
            "POST", rota, json=json, token=token, idempotency_key=idempotency_key
        )

    async def fechar(self) -> None:
        await self._cliente.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        await self.fechar()
