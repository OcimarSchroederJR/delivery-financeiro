from uuid import UUID, uuid4

import httpx
import pytest

from pagamentos.dominio.pagamento import Pagamento, StatusPagamento
from pagamentos.testes.fakes import EstadoFake, pagamento_aprovado, pagamento_recusado
from pagamentos.testes.requisicoes import cabecalhos


def _rota(pagamento_id: object) -> str:
    return f"/v1/pagamentos/{pagamento_id}/estornos"


def _semear(estado: EstadoFake, pagamento: Pagamento | None = None) -> Pagamento:
    pagamento = pagamento or pagamento_aprovado()
    estado.pagamentos[pagamento.id] = pagamento
    return pagamento


def _servico(chave: str) -> dict[str, str]:
    return cabecalhos("servico", "avaliacoes", chave=chave)


async def test_servico_estorna_parcialmente_com_a_chave_da_disputa(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    pagamento = _semear(estado)
    resposta = await api.post(
        _rota(pagamento.id),
        json={"valor_centavos": 1000, "motivo": "disputa procedente"},
        headers=_servico("disputa-1"),
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert set(corpo) == {"id", "pagamento_id", "valor_centavos", "motivo", "status", "criado_em"}
    assert (corpo["pagamento_id"], corpo["valor_centavos"]) == (str(pagamento.id), 1000)
    assert corpo["status"] == "parcialmente_estornado"
    assert estado.pagamentos[pagamento.id].status == StatusPagamento.PARCIALMENTE_ESTORNADO
    tipo, dados = estado.eventos[-1]
    assert tipo == "pagamento.estornado"
    assert (dados["estorno_id"], dados["valor_centavos"], dados["motivo"]) == (
        corpo["id"],
        1000,
        "disputa procedente",
    )


async def test_admin_estorna_o_saldo_inteiro_sem_valor(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    pagamento = _semear(estado)
    resposta = await api.post(
        _rota(pagamento.id),
        json={"motivo": "pedido não entregue"},
        headers=cabecalhos("admin", "admin-1", chave="k-adm"),
    )
    assert resposta.status_code == 201
    assert (resposta.json()["valor_centavos"], resposta.json()["status"]) == (4590, "estornado")
    assert estado.pagamentos[pagamento.id].status == StatusPagamento.ESTORNADO


async def test_valor_acima_do_saldo_422(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    pagamento = _semear(estado)
    resposta = await api.post(
        _rota(pagamento.id), json={"valor_centavos": 5000, "motivo": "x"}, headers=_servico("d-2")
    )
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "VALOR_EXCEDE_SALDO_ESTORNAVEL"
    assert resposta.json()["saldo_estornavel_centavos"] == 4590


async def test_pagamento_recusado_409(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    pagamento = _semear(estado, pagamento_recusado())
    resposta = await api.post(_rota(pagamento.id), json={"motivo": "x"}, headers=_servico("d-3"))
    assert resposta.status_code == 409
    assert resposta.json()["codigo"] == "PAGAMENTO_NAO_ESTORNAVEL"


async def test_pagamento_totalmente_estornado_409(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    pagamento = _semear(estado)
    await api.post(_rota(pagamento.id), json={"motivo": "a"}, headers=_servico("d-4a"))
    resposta = await api.post(_rota(pagamento.id), json={"motivo": "b"}, headers=_servico("d-4b"))
    assert resposta.status_code == 409


@pytest.mark.parametrize("identificador", [str(uuid4()), "nao-e-uuid"])
async def test_pagamento_inexistente_404(api: httpx.AsyncClient, identificador: str) -> None:
    resposta = await api.post(_rota(identificador), json={"motivo": "x"}, headers=_servico("d-5"))
    assert resposta.status_code == 404


@pytest.mark.parametrize(("papel", "sub"), [("cliente", "cliente-1"), ("loja", "loja-1")])
async def test_so_admin_e_servico_estornam(
    api: httpx.AsyncClient, estado: EstadoFake, papel: str, sub: str
) -> None:
    pagamento = _semear(estado)
    resposta = await api.post(
        _rota(pagamento.id), json={"motivo": "x"}, headers=cabecalhos(papel, sub, chave="k")
    )
    assert resposta.status_code == 403


async def test_sem_idempotency_key_400(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    pagamento = _semear(estado)
    resposta = await api.post(
        _rota(pagamento.id), json={"motivo": "x"}, headers=cabecalhos("admin", "admin-1")
    )
    assert resposta.status_code == 400
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_AUSENTE"


async def test_repeticao_do_estorno_nao_estorna_duas_vezes(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    pagamento = _semear(estado)
    corpo = {"valor_centavos": 1000, "motivo": "disputa procedente"}
    primeira = await api.post(_rota(pagamento.id), json=corpo, headers=_servico("disputa-7"))
    segunda = await api.post(_rota(pagamento.id), json=corpo, headers=_servico("disputa-7"))
    assert (primeira.status_code, segunda.status_code) == (201, 201)
    assert segunda.json() == primeira.json()
    assert segunda.headers["Idempotency-Replayed"] == "true"
    assert len(estado.pagamentos[pagamento.id].estornos) == 1
    assert [tipo for tipo, _ in estado.eventos] == ["pagamento.estornado"]


async def test_mesma_chave_com_corpo_diferente_422(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    pagamento = _semear(estado)
    await api.post(
        _rota(pagamento.id), json={"valor_centavos": 100, "motivo": "a"}, headers=_servico("d-8")
    )
    resposta = await api.post(
        _rota(pagamento.id), json={"valor_centavos": 200, "motivo": "a"}, headers=_servico("d-8")
    )
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_REUTILIZADA"


async def test_mesma_chave_em_outro_pagamento_e_independente(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    primeiro = _semear(estado)
    segundo = _semear(estado, pagamento_aprovado(pedido_id="ped-4"))
    corpo = {"motivo": "x"}
    a = await api.post(_rota(primeiro.id), json=corpo, headers=_servico("disputa-9"))
    b = await api.post(_rota(segundo.id), json=corpo, headers=_servico("disputa-9"))
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.parametrize(
    "corpo",
    [
        {"valor_centavos": 0, "motivo": "x"},
        {"valor_centavos": "100", "motivo": "x"},
        {"valor_centavos": 10.5, "motivo": "x"},
        {"valor_centavos": True, "motivo": "x"},
        {"motivo": "   "},
        {"valor_centavos": 100},
        {"valor_centavos": 100, "motivo": "x", "extra": 1},
    ],
)
async def test_corpo_invalido_422(
    api: httpx.AsyncClient, estado: EstadoFake, corpo: dict[str, object]
) -> None:
    pagamento = _semear(estado)
    resposta = await api.post(_rota(pagamento.id), json=corpo, headers=_servico("d-10"))
    assert resposta.status_code == 422
    assert estado.pagamentos[pagamento.id].estornos == []


async def test_lista_estornos_do_pagamento(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    pagamento = _semear(estado)
    for chave in ("d-11a", "d-11b"):
        await api.post(
            _rota(pagamento.id),
            json={"valor_centavos": 100, "motivo": chave},
            headers=_servico(chave),
        )
    corpo = (await api.get(_rota(pagamento.id), headers=cabecalhos())).json()
    assert corpo["total"] == 2
    assert [item["motivo"] for item in corpo["itens"]] == ["d-11a", "d-11b"]
    assert all(UUID(item["pagamento_id"]) == pagamento.id for item in corpo["itens"])


async def test_cliente_nao_lista_estornos_de_outro(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    alheio = _semear(estado, pagamento_aprovado(pedido_id="ped-3", cliente_id="cliente-2"))
    resposta = await api.get(_rota(alheio.id), headers=cabecalhos())
    assert resposta.status_code == 404


async def test_servico_nao_lista_estornos(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    pagamento = _semear(estado)
    resposta = await api.get(_rota(pagamento.id), headers=cabecalhos("servico", "avaliacoes"))
    assert resposta.status_code == 403


async def test_openapi_documenta_idempotency_key_no_estorno(api: httpx.AsyncClient) -> None:
    caminhos = (await api.get("/openapi.json")).json()["paths"]
    operacao = caminhos["/v1/pagamentos/{pagamento_id}/estornos"]["post"]
    assert ("Idempotency-Key", "header") in {(p["name"], p["in"]) for p in operacao["parameters"]}
    assert {"201", "400", "404", "409", "422"} <= set(operacao["responses"])
