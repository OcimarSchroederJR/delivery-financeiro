import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria
from plataforma.auth import EmissorTokenServico
from plataforma.envelope import EnvelopeEvento
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

Bearer = Callable[[str, str], dict[str, str]]


def _envelope(**mudancas: Any) -> dict[str, Any]:
    base = EnvelopeEvento.novo(
        "entrega.concluida",
        {"pedido_id": "ped-3", "cliente_id": "cliente-2", "entregador_id": "entregador-1"},
    )
    return {**base.para_json(), **mudancas}


async def test_aceita_evento_e_deduplica(
    api: httpx.AsyncClient, armazenamento: ArmazenamentoEmMemoria, bearer: Bearer
) -> None:
    corpo = _envelope()
    cabecalhos = bearer("mock-logistica", "entregador")
    primeira = await api.post("/v1/eventos", json=corpo, headers=cabecalhos)
    segunda = await api.post("/v1/eventos", json=corpo, headers=cabecalhos)
    assert (primeira.status_code, primeira.json()) == (
        202,
        {"mensagem_id": corpo["mensagem_id"], "status": "aceito"},
    )
    assert (segunda.status_code, segunda.json()["status"]) == (202, "duplicado")
    assert len(armazenamento.eventos_externos) == 1


@pytest.mark.parametrize("papel", ["loja", "entregador", "admin"])
async def test_papeis_que_podem_publicar(
    api: httpx.AsyncClient, bearer: Bearer, papel: str
) -> None:
    resposta = await api.post("/v1/eventos", json=_envelope(), headers=bearer("sistema-1", papel))
    assert resposta.status_code == 202


async def test_cliente_e_servico_nao_publicam(api: httpx.AsyncClient, bearer: Bearer) -> None:
    do_cliente = await api.post("/v1/eventos", json=_envelope(), headers=bearer("c1", "cliente"))
    assert (do_cliente.status_code, do_cliente.json()["codigo"]) == (403, "ACESSO_NEGADO")
    token = EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes").emitir()
    do_servico = await api.post(
        "/v1/eventos", json=_envelope(), headers={"Authorization": f"Bearer {token}"}
    )
    assert do_servico.status_code == 403


async def test_sem_token_401(api: httpx.AsyncClient) -> None:
    resposta = await api.post("/v1/eventos", json=_envelope())
    assert (resposta.status_code, resposta.json()["codigo"]) == (401, "NAO_AUTENTICADO")


async def test_eventos_tipo_reservado_403(api: httpx.AsyncClient, bearer: Bearer) -> None:
    resposta = await api.post(
        "/v1/eventos", json=_envelope(tipo="pagamento.aprovado"), headers=bearer("l1", "loja")
    )
    assert (resposta.status_code, resposta.json()["codigo"]) == (403, "TIPO_DE_EVENTO_RESERVADO")


@pytest.mark.parametrize("corpo", [b"{", b"[]", json.dumps(_envelope(mensagem_id="x")).encode()])
async def test_envelope_invalido_400(api: httpx.AsyncClient, bearer: Bearer, corpo: bytes) -> None:
    resposta = await api.post(
        "/v1/eventos",
        content=corpo,
        headers={**bearer("l1", "loja"), "Content-Type": "application/json"},
    )
    erro = resposta.json()
    assert resposta.status_code == 400
    assert (erro["erro"], erro["codigo"]) == (True, "ENVELOPE_INVALIDO")
    assert erro["correlation_id"]


async def test_envelope_grande_400(api: httpx.AsyncClient, bearer: Bearer) -> None:
    corpo = _envelope(dados={"texto": "a" * 70_000})
    resposta = await api.post("/v1/eventos", json=corpo, headers=bearer("l1", "loja"))
    assert resposta.status_code == 400


async def test_openapi_documenta_envelope_e_status(api: httpx.AsyncClient) -> None:
    operacao = (await api.get("/openapi.json")).json()["paths"]["/v1/eventos"]["post"]
    esquema = operacao["requestBody"]["content"]["application/json"]["schema"]
    assert {"mensagem_id", "tipo", "ocorrido_em", "correlation_id", "dados"} <= set(
        esquema["properties"]
    )
    assert {"202", "400", "401", "403"} <= set(operacao["responses"])
