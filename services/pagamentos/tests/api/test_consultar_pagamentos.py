from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from pagamentos.dominio.pagamento import Pagamento
from pagamentos.testes.fakes import INSTANTE, EstadoFake, pagamento_aprovado
from pagamentos.testes.requisicoes import cabecalhos

ROTA = "/v1/pagamentos"


def _semear(estado: EstadoFake, **campos: object) -> Pagamento:
    pagamento = pagamento_aprovado(**campos)
    estado.pagamentos[pagamento.id] = pagamento
    return pagamento


async def test_cliente_obtem_o_proprio_pagamento(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    pagamento = _semear(estado)
    resposta = await api.get(f"{ROTA}/{pagamento.id}", headers=cabecalhos())
    assert resposta.status_code == 200
    assert resposta.json() == {
        "id": str(pagamento.id),
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "metodo": "pix",
        "status": "aprovado",
        "motivo_recusa": None,
        "cartao_final": None,
        "valor_estornado_centavos": 0,
        "saldo_estornavel_centavos": 4590,
        "criado_em": "2026-10-14T14:30:00Z",
        "atualizado_em": "2026-10-14T14:30:00Z",
    }


async def test_pagamento_de_outro_cliente_e_404(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    alheio = _semear(estado, pedido_id="ped-3", cliente_id="cliente-2")
    resposta = await api.get(f"{ROTA}/{alheio.id}", headers=cabecalhos())
    assert resposta.status_code == 404
    assert resposta.json()["codigo"] == "PAGAMENTO_NAO_ENCONTRADO"


async def test_admin_obtem_qualquer_pagamento(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    alheio = _semear(estado, pedido_id="ped-3", cliente_id="cliente-2")
    resposta = await api.get(f"{ROTA}/{alheio.id}", headers=cabecalhos("admin", "admin-1"))
    assert resposta.status_code == 200


@pytest.mark.parametrize("identificador", [str(uuid4()), "nao-e-uuid"])
async def test_pagamento_inexistente_e_404(api: httpx.AsyncClient, identificador: str) -> None:
    resposta = await api.get(f"{ROTA}/{identificador}", headers=cabecalhos("admin", "admin-1"))
    assert resposta.status_code == 404


@pytest.mark.parametrize(("papel", "sub"), [("servico", "avaliacoes"), ("loja", "loja-1")])
async def test_detalhe_nao_e_para_servico_nem_loja(
    api: httpx.AsyncClient, estado: EstadoFake, papel: str, sub: str
) -> None:
    pagamento = _semear(estado)
    resposta = await api.get(f"{ROTA}/{pagamento.id}", headers=cabecalhos(papel, sub))
    assert resposta.status_code == 403


async def test_cliente_lista_so_os_seus_mais_recentes_primeiro(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    antigo = _semear(estado, pedido_id="ped-1", agora=INSTANTE)
    novo = _semear(estado, pedido_id="ped-4", agora=INSTANTE + timedelta(minutes=5))
    _semear(estado, pedido_id="ped-3", cliente_id="cliente-2")
    corpo = (await api.get(ROTA, headers=cabecalhos())).json()
    assert [item["id"] for item in corpo["itens"]] == [str(novo.id), str(antigo.id)]
    assert (corpo["pagina"], corpo["tamanho"], corpo["total"]) == (1, 20, 2)


async def test_admin_lista_todos(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    _semear(estado)
    _semear(estado, pedido_id="ped-3", cliente_id="cliente-2")
    corpo = (await api.get(ROTA, headers=cabecalhos("admin", "admin-1"))).json()
    assert corpo["total"] == 2


async def test_servico_consulta_por_pedido_como_avaliacoes(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    _semear(estado)
    alvo = _semear(estado, pedido_id="ped-3", cliente_id="cliente-2", valor_centavos=2590)
    resposta = await api.get(
        ROTA, params={"pedido_id": "ped-3"}, headers=cabecalhos("servico", "avaliacoes")
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 1
    item = corpo["itens"][0]
    assert (item["id"], item["status"], item["valor_centavos"]) == (str(alvo.id), "aprovado", 2590)
    assert item["saldo_estornavel_centavos"] == 2590


async def test_paginacao(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    for minutos, pedido_id in enumerate(("ped-1", "ped-2", "ped-4")):
        _semear(estado, pedido_id=pedido_id, agora=INSTANTE + timedelta(minutes=minutos))
    corpo = (await api.get(ROTA, params={"pagina": 2, "tamanho": 2}, headers=cabecalhos())).json()
    assert (len(corpo["itens"]), corpo["pagina"], corpo["tamanho"], corpo["total"]) == (1, 2, 2, 3)
    assert corpo["itens"][0]["pedido_id"] == "ped-1"


@pytest.mark.parametrize("params", [{"tamanho": 101}, {"pagina": 0}, {"pedido_id": "../x"}])
async def test_parametros_invalidos_422(api: httpx.AsyncClient, params: dict[str, object]) -> None:
    resposta = await api.get(ROTA, params=params, headers=cabecalhos())
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "REQUISICAO_INVALIDA"


async def test_entregador_nao_lista(api: httpx.AsyncClient) -> None:
    resposta = await api.get(ROTA, headers=cabecalhos("entregador", "e-1"))
    assert resposta.status_code == 403
