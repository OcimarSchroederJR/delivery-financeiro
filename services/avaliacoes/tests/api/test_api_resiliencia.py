"""Cenários de resiliência da spec §9 com os adaptadores HTTP reais (respx)."""

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager

from avaliacoes.adaptadores.clientes.pagamentos import PagamentosHttp
from avaliacoes.adaptadores.clientes.pedidos import PedidosHttp
from avaliacoes.api import criar_app
from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho
from avaliacoes.aplicacao.saga import PoliticaDeRetentativa, RetentativaDeEstornos
from avaliacoes.composicao import Dependencias
from avaliacoes.config import Config
from avaliacoes.testes.fakes import BancoEmMemoria, RelogioFake, autorizacao
from plataforma.auth import EmissorTokenServico, Papel, VerificadorTokenServico
from plataforma.cliente_http import ClienteHttp
from plataforma.correlation import HEADER_CORRELATION_ID
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
    GeradorDeTokens,
    criar_verificador_de_teste,
)

URL_PEDIDOS = "http://pedidos.teste"
URL_PAGAMENTOS = "http://pagamentos.teste"
ROTA_ESTORNO = "/v1/pagamentos/pag-1/estornos"
PAGAMENTO = {
    "id": "pag-1",
    "pedido_id": "ped-4",
    "cliente_id": "cliente-1",
    "valor_centavos": 3200,
    "metodo": "pix",
    "status": "aprovado",
}


@pytest.fixture
async def deps_reais(
    uow: FabricaUnidadeDeTrabalho, relogio: RelogioFake
) -> AsyncIterator[Dependencias]:
    async with (
        ClienteHttp("pedidos", URL_PEDIDOS, espera_base=0, espera_maxima=0) as pedidos,
        ClienteHttp("pagamentos", URL_PAGAMENTOS, espera_base=0, espera_maxima=0) as pagamentos,
    ):
        yield Dependencias(
            uow=uow,
            pedidos=PedidosHttp(pedidos),
            pagamentos=PagamentosHttp(pagamentos),
            emissor_token=EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes"),
            politica=PoliticaDeRetentativa(),
            relogio=relogio,
        )


@pytest.fixture
async def api_real(
    config: Config, gerador: GeradorDeTokens, deps_reais: Dependencias
) -> AsyncIterator[httpx.AsyncClient]:
    app = criar_app(
        config, verificador=criar_verificador_de_teste(gerador), dependencias=deps_reais
    )
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            yield http


@respx.mock(base_url=URL_PEDIDOS, assert_all_called=False)
async def test_eq3_fora_responde_503_e_circuito_abre(
    respx_mock: respx.MockRouter, api_real: httpx.AsyncClient, token_cliente: str
) -> None:
    rota = respx_mock.get("/pedidos/ped-4").respond(503)
    corpo = {"pedido_id": "ped-4", "nota_restaurante": 5}
    cabecalho = {**autorizacao(token_cliente), HEADER_CORRELATION_ID: "corr-eq3"}
    for _ in range(5):
        resposta = await api_real.post("/v1/avaliacoes", json=corpo, headers=cabecalho)
        assert resposta.status_code == 503
        assert resposta.json()["dependencia"] == "pedidos"
    assert rota.calls.last.request.headers[HEADER_CORRELATION_ID] == "corr-eq3"
    chamadas = rota.call_count
    bloqueada = await api_real.post("/v1/avaliacoes", json=corpo, headers=cabecalho)
    assert bloqueada.status_code == 503
    assert rota.call_count == chamadas  # circuito aberto: nem chama a Eq. 3


@respx.mock(base_url=URL_PEDIDOS)
async def test_eq3_com_timeout_responde_503(
    respx_mock: respx.MockRouter, api_real: httpx.AsyncClient, token_cliente: str
) -> None:
    respx_mock.get("/pedidos/ped-4").mock(side_effect=httpx.ReadTimeout("lento"))
    resposta = await api_real.post(
        "/v1/avaliacoes",
        json={"pedido_id": "ped-4", "nota_restaurante": 5},
        headers=autorizacao(token_cliente),
    )
    assert resposta.status_code == 503


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_pagamentos_fora_na_saga_202_e_worker_conclui_com_token_de_servico(
    respx_mock: respx.MockRouter,
    api_real: httpx.AsyncClient,
    deps_reais: Dependencias,
    token_cliente: str,
    token_admin: str,
    banco: BancoEmMemoria,
    relogio: RelogioFake,
) -> None:
    respx_mock.get("/v1/pagamentos").respond(
        200, json={"itens": [PAGAMENTO], "pagina": 1, "tamanho": 100, "total": 1}
    )
    estorno = respx_mock.post(ROTA_ESTORNO).mock(
        side_effect=[httpx.Response(503)] * 3
        + [httpx.Response(201, json={"id": "est-9", "valor_centavos": 1000})]
    )
    aberta = await api_real.post(
        "/v1/disputas",
        json={"pedido_id": "ped-4", "motivo": "qualidade", "valor_solicitado_centavos": 1000},
        headers=autorizacao(token_cliente),
    )
    disputa_id = aberta.json()["id"]

    resposta = await api_real.patch(
        f"/v1/disputas/{disputa_id}",
        json={"status": "procedente"},
        headers=autorizacao(token_admin),
    )
    assert resposta.status_code == 202
    assert estorno.call_count == 3  # 1 tentativa da saga = 3 tentativas HTTP (retry)

    relogio.avancar(seconds=5)
    retentativa = RetentativaDeEstornos(deps_reais.uow, deps_reais.saga(), relogio=relogio)
    assert await retentativa.processar_lote() == 1

    final = await api_real.get(f"/v1/disputas/{disputa_id}", headers=autorizacao(token_admin))
    assert final.json()["status"] == "resolvida"
    assert final.json()["estorno_id"] == "est-9"
    corpos = {c.request.read() for c in estorno.calls}
    chaves = {c.request.headers["Idempotency-Key"] for c in estorno.calls}
    assert len(corpos) == 1
    assert chaves == {f"disputa-{disputa_id}"}
    token = estorno.calls.last.request.headers["Authorization"].removeprefix("Bearer ")
    usuario = await VerificadorTokenServico(SEGREDO_SERVICO_TESTE).verificar(token)
    assert usuario.papel is Papel.SERVICO
    assert banco.tipos_de_eventos() == ["disputa.aberta", "disputa.resolvida"]
