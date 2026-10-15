"""Mock da Equipe 4 (Logística): dispara ``entrega.concluida`` para Notificações."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, status
from pydantic import BaseModel

from mocks_equipes.comum import criar_app_mock, router_com_falhas
from plataforma.cliente_http import ClienteHttp
from plataforma.envelope import EnvelopeEvento
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.tempo import agora_utc, para_iso_utc


class DadosConclusao(BaseModel):
    cliente_id: str = "cliente-1"
    entregador_id: str = "entregador-1"


class ResultadoDisparo(BaseModel):
    status_notificacoes: int
    envelope: dict[str, Any]


def criar_app(
    *,
    notificacoes_url: str | None = None,
    identidade_url: str | None = None,
    papel: str | None = None,
) -> FastAPI:
    url_notificacoes = notificacoes_url or os.environ.get(
        "NOTIFICACOES_URL", "http://localhost:8014"
    )
    url_identidade = identidade_url or os.environ.get("IDENTIDADE_URL", "http://localhost:8001")
    papel_token = papel or os.environ.get("MOCK_LOGISTICA_PAPEL", "entregador")
    clientes: dict[str, ClienteHttp] = {}

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
        clientes["identidade"] = ClienteHttp("identidade", url_identidade)
        clientes["notificacoes"] = ClienteHttp("notificacoes", url_notificacoes)
        yield
        for cliente in clientes.values():
            await cliente.fechar()

    app = criar_app_mock(
        "mock-logistica",
        "Mock Logística (Eq. 4)",
        "Dispara o evento entrega.concluida para POST /v1/eventos de Notificações.",
        ciclo_de_vida=ciclo_de_vida,
    )
    rotas = router_com_falhas()

    @rotas.post(
        "/entregas/{pedido_id}/concluir",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=ResultadoDisparo,
    )
    async def concluir(pedido_id: str, dados: DadosConclusao | None = None) -> ResultadoDisparo:
        dados = dados or DadosConclusao()
        envelope = EnvelopeEvento.novo(
            "entrega.concluida",
            {
                "pedido_id": pedido_id,
                "cliente_id": dados.cliente_id,
                "entregador_id": dados.entregador_id,
                "concluida_em": para_iso_utc(agora_utc()),
            },
        )
        resposta_token = await clientes["identidade"].post(
            "/tokens", json={"sub": "mock-logistica", "papel": papel_token}
        )
        if resposta_token.status_code != status.HTTP_201_CREATED:
            raise ErroDependenciaIndisponivel("identidade")
        token = resposta_token.json()["access_token"]
        resposta = await clientes["notificacoes"].post(
            "/v1/eventos", json=envelope.para_json(), token=token
        )
        return ResultadoDisparo(
            status_notificacoes=resposta.status_code, envelope=envelope.para_json()
        )

    app.include_router(rotas)
    return app


app = criar_app()
