"""Adapter do nosso serviço de Pagamentos (contrato da spec §4.1).

- ``GET /v1/pagamentos?pedido_id=`` (paginado ``{itens, pagina, tamanho, total}``);
- ``POST /v1/pagamentos/{id}/estornos`` com ``Idempotency-Key``: 201 = sucesso;
  timeout/5xx/circuito aberto = falha transitória; 409 ``IDEMPOTENCY_EM_PROCESSAMENTO``
  = transitória (a mesma chave ainda está sendo processada); outros 4xx = definitiva.
"""

from typing import Any
from urllib.parse import quote

import httpx

from avaliacoes.aplicacao.portas import (
    EstornoRealizado,
    FalhaDefinitiva,
    FalhaTransitoria,
    PagamentoExterno,
    ResultadoEstorno,
)
from plataforma.circuit_breaker import CircuitoAberto
from plataforma.cliente_http import ClienteHttp
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

TAMANHO_PAGINA = 100
MAXIMO_PAGINAS = 10
CODIGOS_TRANSITORIOS = frozenset({"IDEMPOTENCY_EM_PROCESSAMENTO"})


def _pagamento(item: dict[str, Any]) -> PagamentoExterno:
    return PagamentoExterno(
        id=str(item["id"]),
        pedido_id=str(item["pedido_id"]),
        cliente_id=str(item["cliente_id"]),
        valor_centavos=int(item["valor_centavos"]),
        status=str(item["status"]),
    )


def _codigo_erro(resposta: httpx.Response) -> str | None:
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    codigo = corpo.get("codigo") if isinstance(corpo, dict) else None
    return str(codigo) if codigo else None


class PagamentosHttp:
    def __init__(self, cliente: ClienteHttp) -> None:
        self._cliente = cliente

    async def listar_por_pedido(self, pedido_id: str, *, token: str) -> list[PagamentoExterno]:
        pagamentos: list[PagamentoExterno] = []
        for pagina in range(1, MAXIMO_PAGINAS + 1):
            resposta = await self._cliente.get(
                "/v1/pagamentos",
                token=token,
                params={"pedido_id": pedido_id, "pagina": pagina, "tamanho": TAMANHO_PAGINA},
            )
            if resposta.status_code != 200:  # a listagem não tem erro no contrato (§4.1)
                _log.warning("pagamentos_resposta_inesperada", status=resposta.status_code)
                raise ErroDependenciaIndisponivel("pagamentos")
            try:
                corpo = resposta.json()
                itens = [_pagamento(item) for item in corpo["itens"]]
                total = int(corpo["total"])
            except (ValueError, KeyError, TypeError) as erro:
                raise ErroDependenciaIndisponivel(
                    "pagamentos", "Resposta inválida do serviço de Pagamentos."
                ) from erro
            pagamentos.extend(p for p in itens if p.pedido_id == pedido_id)
            if not itens or pagina * TAMANHO_PAGINA >= total:
                break
        return pagamentos

    async def estornar(
        self,
        pagamento_id: str,
        *,
        valor_centavos: int,
        motivo: str,
        chave_idempotencia: str,
        token: str,
    ) -> ResultadoEstorno:
        try:
            resposta = await self._cliente.post(
                f"/v1/pagamentos/{quote(pagamento_id, safe='')}/estornos",
                json={"valor_centavos": valor_centavos, "motivo": motivo},
                token=token,
                idempotency_key=chave_idempotencia,
            )
        except CircuitoAberto:
            return FalhaTransitoria("CIRCUITO_ABERTO")
        except ErroDependenciaIndisponivel as erro:  # timeout, rede, 5xx após retries
            return FalhaTransitoria(erro.codigo)
        if resposta.status_code in (200, 201):
            try:
                return EstornoRealizado(estorno_id=str(resposta.json()["id"]))
            except (ValueError, KeyError, TypeError):
                return FalhaTransitoria("RESPOSTA_INVALIDA")
        codigo = _codigo_erro(resposta)
        if codigo in CODIGOS_TRANSITORIOS:
            return FalhaTransitoria(codigo)
        return FalhaDefinitiva(codigo or f"HTTP_{resposta.status_code}")
