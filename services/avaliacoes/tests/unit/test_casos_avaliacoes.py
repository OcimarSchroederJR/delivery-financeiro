import uuid

import pytest

from avaliacoes.aplicacao.avaliacoes import (
    ComandoRegistrarAvaliacao,
    ConsultarAvaliacoes,
    RegistrarAvaliacao,
)
from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho, Solicitante
from avaliacoes.dominio.erros import (
    AvaliacaoDuplicada,
    AvaliacaoInvalida,
    AvaliacaoNaoEncontrada,
    PedidoDeOutroCliente,
    PedidoInexistente,
    PedidoNaoEntregue,
)
from avaliacoes.testes.fakes import BancoEmMemoria, PedidosFake, RelogioFake
from plataforma.erros import ErroDependenciaIndisponivel

CLIENTE_1 = Solicitante(id="cliente-1", token="token-cliente-1")


@pytest.fixture
def registrar(
    uow: FabricaUnidadeDeTrabalho, pedidos: PedidosFake, relogio: RelogioFake
) -> RegistrarAvaliacao:
    return RegistrarAvaliacao(uow, pedidos, relogio=relogio)


async def test_registra_copia_restaurante_e_publica_evento(
    registrar: RegistrarAvaliacao, pedidos: PedidosFake, banco: BancoEmMemoria
) -> None:
    pedidos.adicionar("ped-4", restaurante_id="rest-9")
    avaliacao = await registrar.executar(
        ComandoRegistrarAvaliacao("ped-4", nota_restaurante=5, nota_entrega=None), CLIENTE_1
    )
    assert avaliacao.restaurante_id == "rest-9"
    assert avaliacao.cliente_id == "cliente-1"
    assert pedidos.tokens_recebidos == ["token-cliente-1"]
    assert banco.eventos == [
        (
            "avaliacao.registrada",
            {
                "avaliacao_id": str(avaliacao.id),
                "pedido_id": "ped-4",
                "restaurante_id": "rest-9",
                "cliente_id": "cliente-1",
                "nota_restaurante": 5,
                "nota_entrega": None,
            },
        )
    ]


async def test_pedido_inexistente(registrar: RegistrarAvaliacao) -> None:
    with pytest.raises(PedidoInexistente):
        await registrar.executar(ComandoRegistrarAvaliacao("nao-existe", 5), CLIENTE_1)


async def test_pedido_de_outro_cliente(registrar: RegistrarAvaliacao, pedidos: PedidosFake) -> None:
    pedidos.adicionar("ped-3", cliente_id="cliente-2")
    with pytest.raises(PedidoDeOutroCliente):
        await registrar.executar(ComandoRegistrarAvaliacao("ped-3", 5), CLIENTE_1)


async def test_pedido_nao_entregue(
    registrar: RegistrarAvaliacao, pedidos: PedidosFake, banco: BancoEmMemoria
) -> None:
    pedidos.adicionar("ped-1", entregue=False)
    with pytest.raises(PedidoNaoEntregue):
        await registrar.executar(ComandoRegistrarAvaliacao("ped-1", 5), CLIENTE_1)
    assert banco.eventos == []


async def test_segunda_avaliacao_do_pedido_e_duplicada_sem_novo_evento(
    registrar: RegistrarAvaliacao, pedidos: PedidosFake, banco: BancoEmMemoria
) -> None:
    pedidos.adicionar("ped-4")
    await registrar.executar(ComandoRegistrarAvaliacao("ped-4", 5), CLIENTE_1)
    with pytest.raises(AvaliacaoDuplicada):
        await registrar.executar(ComandoRegistrarAvaliacao("ped-4", 3), CLIENTE_1)
    assert banco.tipos_de_eventos() == ["avaliacao.registrada"]
    assert len(banco.avaliacoes) == 1


async def test_nota_invalida_nao_grava(
    registrar: RegistrarAvaliacao, pedidos: PedidosFake, banco: BancoEmMemoria
) -> None:
    pedidos.adicionar("ped-4")
    with pytest.raises(AvaliacaoInvalida):
        await registrar.executar(ComandoRegistrarAvaliacao("ped-4", 9), CLIENTE_1)
    assert banco.avaliacoes == {}


async def test_eq3_fora_propaga_503(registrar: RegistrarAvaliacao, pedidos: PedidosFake) -> None:
    pedidos.indisponivel = True
    with pytest.raises(ErroDependenciaIndisponivel) as erro:
        await registrar.executar(ComandoRegistrarAvaliacao("ped-4", 5), CLIENTE_1)
    assert erro.value.status_http == 503


async def test_consultas_listam_filtram_e_resumem(
    registrar: RegistrarAvaliacao,
    pedidos: PedidosFake,
    relogio: RelogioFake,
    uow: FabricaUnidadeDeTrabalho,
) -> None:
    for pedido_id, restaurante, nota, entrega in [
        ("p1", "rest-1", 5, 4),
        ("p2", "rest-1", 4, None),
        ("p3", "rest-1", 2, 3),
        ("p4", "rest-2", 1, 1),
    ]:
        pedidos.adicionar(pedido_id, restaurante_id=restaurante)
        await registrar.executar(
            ComandoRegistrarAvaliacao(pedido_id, nota, nota_entrega=entrega), CLIENTE_1
        )
        relogio.avancar(seconds=1)
    consultas = ConsultarAvaliacoes(uow)

    itens, total = await consultas.listar(
        restaurante_id="rest-1", pedido_id=None, deslocamento=0, limite=2
    )
    assert total == 3
    assert [a.pedido_id for a in itens] == ["p3", "p2"]  # mais recentes primeiro

    itens, total = await consultas.listar(
        restaurante_id=None, pedido_id="p4", deslocamento=0, limite=20
    )
    assert (total, itens[0].restaurante_id) == (1, "rest-2")
    assert (await consultas.obter(itens[0].id)).pedido_id == "p4"

    resumo = await consultas.resumir("rest-1")
    assert (resumo.media_restaurante, resumo.media_entrega, resumo.total) == (3.67, 3.5, 3)
    vazio = await consultas.resumir("rest-sem-avaliacoes")
    assert (vazio.media_restaurante, vazio.media_entrega, vazio.total) == (None, None, 0)


async def test_obter_inexistente(uow: FabricaUnidadeDeTrabalho) -> None:
    with pytest.raises(AvaliacaoNaoEncontrada):
        await ConsultarAvaliacoes(uow).obter(uuid.uuid4())
