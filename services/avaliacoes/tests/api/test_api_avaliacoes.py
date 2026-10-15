import uuid

import httpx
import pytest

from avaliacoes.testes.fakes import BancoEmMemoria, PedidosFake, RelogioFake, autorizacao
from plataforma.correlation import HEADER_CORRELATION_ID


async def test_post_201_copia_restaurante_e_publica_evento(
    api: httpx.AsyncClient, token_cliente: str, pedidos: PedidosFake, banco: BancoEmMemoria
) -> None:
    pedidos.adicionar("ped-4", restaurante_id="rest-1")
    resposta = await api.post(
        "/v1/avaliacoes",
        json={"pedido_id": "ped-4", "nota_restaurante": 5, "comentario": "ótimo"},
        headers=autorizacao(token_cliente),
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["restaurante_id"] == "rest-1"
    assert corpo["cliente_id"] == "cliente-1"
    assert corpo["nota_entrega"] is None
    assert corpo["criado_em"] == "2026-10-14T12:00:00Z"
    assert banco.tipos_de_eventos() == ["avaliacao.registrada"]
    assert pedidos.tokens_recebidos == [token_cliente]  # repassa o token do usuário


@pytest.mark.parametrize(
    ("preparar", "status", "codigo"),
    [
        (lambda p: None, 422, "PEDIDO_INEXISTENTE"),
        (lambda p: p.adicionar("ped-4", entregue=False), 422, "PEDIDO_NAO_ENTREGUE"),
        (lambda p: p.adicionar("ped-4", cliente_id="cliente-2"), 403, "PEDIDO_DE_OUTRO_CLIENTE"),
    ],
)
async def test_post_regras_do_pedido(
    api: httpx.AsyncClient,
    token_cliente: str,
    pedidos: PedidosFake,
    preparar: object,
    status: int,
    codigo: str,
) -> None:
    preparar(pedidos)  # type: ignore[operator]
    resposta = await api.post(
        "/v1/avaliacoes",
        json={"pedido_id": "ped-4", "nota_restaurante": 5},
        headers=autorizacao(token_cliente),
    )
    assert resposta.status_code == status
    corpo = resposta.json()
    assert corpo["erro"] is True
    assert corpo["codigo"] == codigo
    assert corpo["correlation_id"] == resposta.headers[HEADER_CORRELATION_ID]


async def test_post_duplicado_409(
    api: httpx.AsyncClient, token_cliente: str, pedidos: PedidosFake
) -> None:
    pedidos.adicionar("ped-4")
    corpo = {"pedido_id": "ped-4", "nota_restaurante": 4, "nota_entrega": 5}
    assert (
        await api.post("/v1/avaliacoes", json=corpo, headers=autorizacao(token_cliente))
    ).status_code == 201
    resposta = await api.post("/v1/avaliacoes", json=corpo, headers=autorizacao(token_cliente))
    assert resposta.status_code == 409
    assert resposta.json()["codigo"] == "AVALIACAO_DUPLICADA"


async def test_post_eq3_fora_503(
    api: httpx.AsyncClient, token_cliente: str, pedidos: PedidosFake
) -> None:
    pedidos.indisponivel = True
    resposta = await api.post(
        "/v1/avaliacoes",
        json={"pedido_id": "ped-4", "nota_restaurante": 5},
        headers=autorizacao(token_cliente),
    )
    assert resposta.status_code == 503
    assert resposta.json()["codigo"] == "DEPENDENCIA_INDISPONIVEL"


@pytest.mark.parametrize(
    "corpo",
    [
        {"pedido_id": "ped-4", "nota_restaurante": 6},
        {"pedido_id": "ped-4", "nota_restaurante": 0},
        {"pedido_id": "ped-4", "nota_restaurante": "5"},
        {"pedido_id": "ped-4", "nota_restaurante": 5, "nota_entrega": 9},
        {"pedido_id": "ped-4", "nota_restaurante": 5, "comentario": "x" * 1001},
        {"pedido_id": "", "nota_restaurante": 5},
        {"nota_restaurante": 5},
        {"pedido_id": "ped-4", "nota_restaurante": 5, "cliente_id": "outro"},
    ],
)
async def test_post_corpo_invalido_422(
    api: httpx.AsyncClient, token_cliente: str, pedidos: PedidosFake, corpo: dict[str, object]
) -> None:
    pedidos.adicionar("ped-4")
    resposta = await api.post("/v1/avaliacoes", json=corpo, headers=autorizacao(token_cliente))
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "REQUISICAO_INVALIDA"


async def test_post_exige_papel_cliente(
    api: httpx.AsyncClient, token_admin: str, token_servico: str
) -> None:
    corpo = {"pedido_id": "ped-4", "nota_restaurante": 5}
    assert (await api.post("/v1/avaliacoes", json=corpo)).status_code == 401
    for token in (token_admin, token_servico):
        resposta = await api.post("/v1/avaliacoes", json=corpo, headers=autorizacao(token))
        assert resposta.status_code == 403


async def test_listar_paginado_filtrado_obter_e_resumo(
    api: httpx.AsyncClient,
    token_cliente: str,
    token_loja: str,
    pedidos: PedidosFake,
    relogio: RelogioFake,
) -> None:
    for pedido_id, restaurante, nota, entrega in [
        ("p1", "rest-1", 5, 4),
        ("p2", "rest-1", 4, None),
        ("p3", "rest-2", 1, 1),
    ]:
        pedidos.adicionar(pedido_id, restaurante_id=restaurante)
        corpo = {"pedido_id": pedido_id, "nota_restaurante": nota, "nota_entrega": entrega}
        await api.post("/v1/avaliacoes", json=corpo, headers=autorizacao(token_cliente))
        relogio.avancar(seconds=1)

    leitor = autorizacao(token_loja)  # qualquer usuário autenticado pode ler
    pagina = (
        await api.get("/v1/avaliacoes?restaurante_id=rest-1&tamanho=1&pagina=2", headers=leitor)
    ).json()
    assert (pagina["pagina"], pagina["tamanho"], pagina["total"]) == (2, 1, 2)
    assert [a["pedido_id"] for a in pagina["itens"]] == ["p1"]

    por_pedido = (await api.get("/v1/avaliacoes?pedido_id=p3", headers=leitor)).json()
    [avaliacao] = por_pedido["itens"]
    detalhe = await api.get(f"/v1/avaliacoes/{avaliacao['id']}", headers=leitor)
    assert detalhe.json() == avaliacao

    resumo = await api.get("/v1/resumos-avaliacoes/rest-1", headers=leitor)
    assert resumo.json() == {
        "restaurante_id": "rest-1",
        "media_restaurante": 4.5,
        "media_entrega": 4.0,
        "total": 2,
    }
    vazio = await api.get("/v1/resumos-avaliacoes/rest-9", headers=leitor)
    assert vazio.json() == {
        "restaurante_id": "rest-9",
        "media_restaurante": None,
        "media_entrega": None,
        "total": 0,
    }


async def test_obter_inexistente_404_e_paginacao_invalida_422(
    api: httpx.AsyncClient, token_cliente: str
) -> None:
    cabecalho = autorizacao(token_cliente)
    resposta = await api.get(f"/v1/avaliacoes/{uuid.uuid4()}", headers=cabecalho)
    assert resposta.status_code == 404
    assert resposta.json()["codigo"] == "AVALIACAO_NAO_ENCONTRADA"
    assert (await api.get("/v1/avaliacoes?tamanho=101", headers=cabecalho)).status_code == 422
    assert (await api.get("/v1/avaliacoes", headers={})).status_code == 401
