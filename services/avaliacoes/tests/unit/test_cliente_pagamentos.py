from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from avaliacoes.adaptadores.clientes.pagamentos import PagamentosHttp
from avaliacoes.aplicacao.portas import (
    EstornoRealizado,
    FalhaDefinitiva,
    FalhaTransitoria,
    PagamentoExterno,
)
from plataforma.cliente_http import ClienteHttp
from plataforma.erros import ErroDependenciaIndisponivel

URL_PAGAMENTOS = "http://pagamentos.teste"
ROTA_ESTORNO = "/v1/pagamentos/pag-1/estornos"


@pytest.fixture
async def pagamentos() -> AsyncIterator[PagamentosHttp]:
    async with ClienteHttp("pagamentos", URL_PAGAMENTOS, espera_base=0, espera_maxima=0) as cliente:
        yield PagamentosHttp(cliente)


def _pagamento(id_: str, status: str, pedido_id: str = "ped-4") -> dict[str, object]:
    return {
        "id": id_,
        "pedido_id": pedido_id,
        "cliente_id": "cliente-1",
        "valor_centavos": 3200,
        "metodo": "pix",
        "status": status,
    }


# --- Pagamentos: listagem ----------------------------------------------------


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_lista_pagamentos_do_pedido_com_token_do_usuario(
    respx_mock: respx.MockRouter, pagamentos: PagamentosHttp
) -> None:
    rota = respx_mock.get("/v1/pagamentos").respond(
        200,
        json={
            "itens": [_pagamento("pag-0", "recusado"), _pagamento("pag-1", "aprovado")],
            "pagina": 1,
            "tamanho": 100,
            "total": 2,
        },
    )
    resultado = await pagamentos.listar_por_pedido("ped-4", token="tok-cliente")
    assert [p.id for p in resultado] == ["pag-0", "pag-1"]
    assert resultado[1] == PagamentoExterno("pag-1", "ped-4", "cliente-1", 3200, "aprovado")
    requisicao = rota.calls.last.request
    assert dict(requisicao.url.params) == {"pedido_id": "ped-4", "pagina": "1", "tamanho": "100"}
    assert requisicao.headers["Authorization"] == "Bearer tok-cliente"


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_listagem_percorre_paginas_e_ignora_outro_pedido(
    respx_mock: respx.MockRouter, pagamentos: PagamentosHttp
) -> None:
    pagina_1 = [_pagamento(f"pag-{i}", "recusado") for i in range(99)]
    pagina_1.append(_pagamento("pag-outro", "aprovado", pedido_id="ped-9"))
    rota = respx_mock.get("/v1/pagamentos").mock(
        side_effect=[
            httpx.Response(
                200, json={"itens": pagina_1, "pagina": 1, "tamanho": 100, "total": 101}
            ),
            httpx.Response(
                200,
                json={
                    "itens": [_pagamento("pag-ok", "aprovado")],
                    "pagina": 2,
                    "tamanho": 100,
                    "total": 101,
                },
            ),
        ]
    )
    resultado = await pagamentos.listar_por_pedido("ped-4", token="t")
    assert rota.call_count == 2
    assert len(resultado) == 100
    assert resultado[-1].id == "pag-ok"


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_listagem_fora_do_contrato_vira_503(
    respx_mock: respx.MockRouter, pagamentos: PagamentosHttp
) -> None:
    """§4.1 não prevê 403 na listagem (ela só mostra os pagamentos do próprio cliente)."""
    respx_mock.get("/v1/pagamentos", params={"pedido_id": "ped-3"}).respond(403)
    respx_mock.get("/v1/pagamentos", params={"pedido_id": "ped-4"}).respond(503)
    respx_mock.get("/v1/pagamentos", params={"pedido_id": "ped-5"}).respond(200, json={"x": 1})
    with pytest.raises(ErroDependenciaIndisponivel):
        await pagamentos.listar_por_pedido("ped-3", token="t")
    with pytest.raises(ErroDependenciaIndisponivel):
        await pagamentos.listar_por_pedido("ped-4", token="t")
    with pytest.raises(ErroDependenciaIndisponivel):
        await pagamentos.listar_por_pedido("ped-5", token="t")


# --- Pagamentos: estorno -----------------------------------------------------


async def _estornar(pagamentos: PagamentosHttp) -> object:
    return await pagamentos.estornar(
        "pag-1",
        valor_centavos=1000,
        motivo="Disputa d-1 procedente (item_faltando).",
        chave_idempotencia="disputa-d-1",
        token="tok-servico",
    )


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_estorno_201_com_chave_e_token_de_servico(
    respx_mock: respx.MockRouter, pagamentos: PagamentosHttp
) -> None:
    rota = respx_mock.post(ROTA_ESTORNO).respond(201, json={"id": "est-1", "valor_centavos": 1000})
    assert await _estornar(pagamentos) == EstornoRealizado("est-1")
    requisicao = rota.calls.last.request
    assert requisicao.headers["Idempotency-Key"] == "disputa-d-1"
    assert requisicao.headers["Authorization"] == "Bearer tok-servico"
    assert requisicao.read() == (
        b'{"valor_centavos":1000,"motivo":"Disputa d-1 procedente (item_faltando)."}'
    )


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        (
            httpx.Response(409, json={"erro": True, "codigo": "PAGAMENTO_NAO_ESTORNAVEL"}),
            FalhaDefinitiva("PAGAMENTO_NAO_ESTORNAVEL"),
        ),
        (
            httpx.Response(422, json={"erro": True, "codigo": "VALOR_EXCEDE_SALDO_ESTORNAVEL"}),
            FalhaDefinitiva("VALOR_EXCEDE_SALDO_ESTORNAVEL"),
        ),
        (httpx.Response(404, json={"erro": True}), FalhaDefinitiva("HTTP_404")),
        (httpx.Response(403, text="proibido"), FalhaDefinitiva("HTTP_403")),
        (
            httpx.Response(409, json={"erro": True, "codigo": "IDEMPOTENCY_EM_PROCESSAMENTO"}),
            FalhaTransitoria("IDEMPOTENCY_EM_PROCESSAMENTO"),
        ),
        (httpx.Response(201, json={"sem": "id"}), FalhaTransitoria("RESPOSTA_INVALIDA")),
        (httpx.Response(503), FalhaTransitoria("DEPENDENCIA_INDISPONIVEL")),
    ],
)
@respx.mock(base_url=URL_PAGAMENTOS)
async def test_estorno_classifica_as_falhas(
    respx_mock: respx.MockRouter,
    pagamentos: PagamentosHttp,
    resposta: httpx.Response,
    esperado: object,
) -> None:
    respx_mock.post(ROTA_ESTORNO).mock(return_value=resposta)
    assert await _estornar(pagamentos) == esperado


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_estorno_com_timeout_e_repetido_com_a_mesma_chave_e_vira_transitoria(
    respx_mock: respx.MockRouter, pagamentos: PagamentosHttp
) -> None:
    rota = respx_mock.post(ROTA_ESTORNO).mock(side_effect=httpx.ReadTimeout("lento"))
    assert await _estornar(pagamentos) == FalhaTransitoria("DEPENDENCIA_INDISPONIVEL")
    assert rota.call_count == 3
    assert {c.request.headers["Idempotency-Key"] for c in rota.calls} == {"disputa-d-1"}


@respx.mock(base_url=URL_PAGAMENTOS)
async def test_circuito_aberto_vira_transitoria_sem_chamar(
    respx_mock: respx.MockRouter, pagamentos: PagamentosHttp
) -> None:
    rota = respx_mock.post(ROTA_ESTORNO).respond(503)
    for _ in range(5):
        await _estornar(pagamentos)
    chamadas = rota.call_count
    assert await _estornar(pagamentos) == FalhaTransitoria("CIRCUITO_ABERTO")
    assert rota.call_count == chamadas
