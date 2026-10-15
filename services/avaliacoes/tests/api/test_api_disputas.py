import uuid

import httpx
import pytest

from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho, FalhaDefinitiva, FalhaTransitoria
from avaliacoes.aplicacao.saga import RetentativaDeEstornos, SagaEstorno
from avaliacoes.testes.fakes import BancoEmMemoria, PagamentosFake, RelogioFake, autorizacao

CORPO = {
    "pedido_id": "ped-4",
    "motivo": "item_faltando",
    "descricao": "faltou a bebida",
    "valor_solicitado_centavos": 1000,
}


async def _abrir(api: httpx.AsyncClient, token: str, **alteracoes: object) -> httpx.Response:
    return await api.post("/v1/disputas", json={**CORPO, **alteracoes}, headers=autorizacao(token))


async def test_post_201_publica_disputa_aberta(
    api: httpx.AsyncClient, token_cliente: str, pagamentos: PagamentosFake, banco: BancoEmMemoria
) -> None:
    pagamentos.adicionar("ped-4", pagamento_id="pag-1")
    resposta = await _abrir(api, token_cliente)
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["status"] == "aberta"
    assert corpo["pagamento_id"] == "pag-1"
    assert corpo["valor_aprovado_centavos"] is None
    assert banco.tipos_de_eventos() == ["disputa.aberta"]
    assert pagamentos.tokens_listagem == [token_cliente]


@pytest.mark.parametrize(
    ("preparar", "alteracoes", "status", "codigo"),
    [
        (lambda p: None, {}, 422, "PAGAMENTO_NAO_ENCONTRADO"),
        (lambda p: p.adicionar("ped-4", status="estornado"), {}, 422, "PAGAMENTO_NAO_ENCONTRADO"),
        (
            lambda p: p.adicionar("ped-4", valor_centavos=999),
            {},
            422,
            "VALOR_EXCEDE_PAGO",
        ),
        (
            lambda p: p.adicionar("ped-4", cliente_id="cliente-2"),
            {},
            403,
            "PEDIDO_DE_OUTRO_CLIENTE",
        ),
        (lambda p: p.adicionar("ped-4"), {"motivo": "outro"}, 422, "REQUISICAO_INVALIDA"),
        (
            lambda p: p.adicionar("ped-4"),
            {"valor_solicitado_centavos": 0},
            422,
            "REQUISICAO_INVALIDA",
        ),
    ],
)
async def test_post_erros(
    api: httpx.AsyncClient,
    token_cliente: str,
    pagamentos: PagamentosFake,
    preparar: object,
    alteracoes: dict[str, object],
    status: int,
    codigo: str,
) -> None:
    preparar(pagamentos)  # type: ignore[operator]
    resposta = await _abrir(api, token_cliente, **alteracoes)
    assert resposta.status_code == status
    assert resposta.json()["codigo"] == codigo


async def test_post_segunda_disputa_409_e_pagamentos_fora_503(
    api: httpx.AsyncClient, token_cliente: str, pagamentos: PagamentosFake
) -> None:
    pagamentos.adicionar("ped-4")
    assert (await _abrir(api, token_cliente)).status_code == 201
    repetida = await _abrir(api, token_cliente)
    assert repetida.status_code == 409
    assert repetida.json()["codigo"] == "DISPUTA_JA_ABERTA"
    pagamentos.indisponivel = True
    fora = await _abrir(api, token_cliente, pedido_id="ped-5")
    assert fora.status_code == 503


async def test_post_so_cliente(
    api: httpx.AsyncClient, token_admin: str, token_servico: str
) -> None:
    assert (await _abrir(api, token_admin)).status_code == 403
    assert (await _abrir(api, token_servico)).status_code == 403


async def test_listar_e_obter_respeitam_dono(
    api: httpx.AsyncClient,
    token_cliente: str,
    token_cliente_2: str,
    token_admin: str,
    token_loja: str,
    pagamentos: PagamentosFake,
    relogio: RelogioFake,
) -> None:
    pagamentos.adicionar("ped-4", cliente_id="cliente-1")
    pagamentos.adicionar("ped-3", cliente_id="cliente-2")
    minha = (await _abrir(api, token_cliente)).json()
    relogio.avancar(seconds=1)
    dela = (await _abrir(api, token_cliente_2, pedido_id="ped-3")).json()

    listagem = (await api.get("/v1/disputas", headers=autorizacao(token_cliente))).json()
    assert [d["id"] for d in listagem["itens"]] == [minha["id"]]
    todas = (await api.get("/v1/disputas", headers=autorizacao(token_admin))).json()
    assert [d["id"] for d in todas["itens"]] == [dela["id"], minha["id"]]
    filtradas = await api.get("/v1/disputas?status=resolvida", headers=autorizacao(token_admin))
    assert filtradas.json()["total"] == 0
    invalido = await api.get("/v1/disputas?status=xyz", headers=autorizacao(token_admin))
    assert invalido.status_code == 422
    assert (await api.get("/v1/disputas", headers=autorizacao(token_loja))).status_code == 403

    alheia = await api.get(f"/v1/disputas/{dela['id']}", headers=autorizacao(token_cliente))
    assert alheia.status_code == 403
    assert alheia.json()["codigo"] == "DISPUTA_DE_OUTRO_CLIENTE"
    propria = await api.get(f"/v1/disputas/{minha['id']}", headers=autorizacao(token_cliente))
    assert propria.json() == minha
    inexistente = await api.get(f"/v1/disputas/{uuid.uuid4()}", headers=autorizacao(token_admin))
    assert inexistente.status_code == 404


@pytest.fixture
async def disputa_id(api: httpx.AsyncClient, token_cliente: str, pagamentos: PagamentosFake) -> str:
    pagamentos.adicionar("ped-4", pagamento_id="pag-1")
    return str((await _abrir(api, token_cliente)).json()["id"])


async def _decidir(
    api: httpx.AsyncClient, token: str, disputa_id: str, **corpo: object
) -> httpx.Response:
    return await api.patch(f"/v1/disputas/{disputa_id}", json=corpo, headers=autorizacao(token))


async def test_patch_procedente_200_resolvida(
    api: httpx.AsyncClient, token_admin: str, disputa_id: str, banco: BancoEmMemoria
) -> None:
    resposta = await _decidir(api, token_admin, disputa_id, status="procedente", parecer="ok")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "resolvida"
    assert corpo["valor_aprovado_centavos"] == 1000  # padrão: o solicitado
    assert corpo["estorno_id"] == "est-1"
    assert banco.eventos[-1][0] == "disputa.resolvida"
    assert banco.eventos[-1][1]["valor_estornado_centavos"] == 1000


async def test_patch_improcedente_200(
    api: httpx.AsyncClient, token_admin: str, disputa_id: str, banco: BancoEmMemoria
) -> None:
    resposta = await _decidir(api, token_admin, disputa_id, status="improcedente")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "improcedente"
    assert banco.eventos[-1][1]["decisao"] == "improcedente"
    assert banco.eventos[-1][1]["valor_estornado_centavos"] == 0


async def test_patch_pagamentos_fora_202_e_worker_conclui(
    api: httpx.AsyncClient,
    token_admin: str,
    disputa_id: str,
    pagamentos: PagamentosFake,
    uow: FabricaUnidadeDeTrabalho,
    saga: SagaEstorno,
    relogio: RelogioFake,
) -> None:
    """Spec §9: Pagamentos fora durante a saga → 202 e conclusão posterior."""
    pagamentos.programar_estorno(FalhaTransitoria("DEPENDENCIA_INDISPONIVEL"))
    resposta = await _decidir(api, token_admin, disputa_id, status="procedente")
    assert resposta.status_code == 202
    assert resposta.json()["status"] == "estorno_pendente"

    relogio.avancar(seconds=5)
    assert await RetentativaDeEstornos(uow, saga, relogio=relogio).processar_lote() == 1
    final = await api.get(f"/v1/disputas/{disputa_id}", headers=autorizacao(token_admin))
    assert final.json()["status"] == "resolvida"
    assert final.json()["tentativas_estorno"] == 2


async def test_patch_falha_definitiva_200_estorno_falhou(
    api: httpx.AsyncClient,
    token_admin: str,
    disputa_id: str,
    pagamentos: PagamentosFake,
    banco: BancoEmMemoria,
) -> None:
    pagamentos.programar_estorno(FalhaDefinitiva("PAGAMENTO_NAO_ESTORNAVEL"))
    resposta = await _decidir(api, token_admin, disputa_id, status="procedente")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "estorno_falhou"
    assert resposta.json()["motivo_falha_estorno"] == "PAGAMENTO_NAO_ESTORNAVEL"
    assert banco.eventos[-1][0] == "disputa.estorno_falhou"


async def test_patch_regras(
    api: httpx.AsyncClient,
    token_admin: str,
    token_cliente: str,
    disputa_id: str,
) -> None:
    assert (await _decidir(api, token_cliente, disputa_id, status="procedente")).status_code == 403
    acima = await _decidir(
        api, token_admin, disputa_id, status="procedente", valor_aprovado_centavos=1001
    )
    assert (acima.status_code, acima.json()["codigo"]) == (422, "VALOR_APROVADO_INVALIDO")
    invalido = await _decidir(api, token_admin, disputa_id, status="resolvida")
    assert invalido.status_code == 422
    assert (await _decidir(api, token_admin, disputa_id, status="improcedente")).status_code == 200
    de_novo = await _decidir(api, token_admin, disputa_id, status="procedente")
    assert (de_novo.status_code, de_novo.json()["codigo"]) == (409, "TRANSICAO_INVALIDA")
    inexistente = await _decidir(api, token_admin, str(uuid.uuid4()), status="procedente")
    assert inexistente.status_code == 404
