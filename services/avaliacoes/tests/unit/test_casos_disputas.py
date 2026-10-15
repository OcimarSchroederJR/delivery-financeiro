import uuid

import pytest

from avaliacoes.aplicacao.disputas import AbrirDisputa, ComandoAbrirDisputa, ConsultarDisputas
from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho, Solicitante
from avaliacoes.dominio.disputa import MotivoDisputa, StatusDisputa
from avaliacoes.dominio.erros import (
    DisputaDeOutroCliente,
    DisputaJaAberta,
    DisputaNaoEncontrada,
    PagamentoNaoEncontrado,
    PedidoDeOutroCliente,
    ValorExcedePago,
)
from avaliacoes.testes.fakes import BancoEmMemoria, PagamentosFake, RelogioFake
from plataforma.erros import ErroDependenciaIndisponivel

CLIENTE_1 = Solicitante(id="cliente-1", token="token-cliente-1")
CLIENTE_2 = Solicitante(id="cliente-2", token="token-cliente-2")
ADMIN = Solicitante(id="admin-1", token="token-admin", admin=True)


def _comando(pedido_id: str = "ped-4", valor: int = 1000) -> ComandoAbrirDisputa:
    return ComandoAbrirDisputa(
        pedido_id=pedido_id,
        motivo=MotivoDisputa.ITEM_FALTANDO,
        valor_solicitado_centavos=valor,
        descricao="faltou a bebida",
    )


@pytest.fixture
def abrir(
    uow: FabricaUnidadeDeTrabalho, pagamentos: PagamentosFake, relogio: RelogioFake
) -> AbrirDisputa:
    return AbrirDisputa(uow, pagamentos, relogio=relogio)


async def test_abre_disputa_com_o_pagamento_aprovado_e_publica_evento(
    abrir: AbrirDisputa, pagamentos: PagamentosFake, banco: BancoEmMemoria
) -> None:
    pagamentos.adicionar("ped-4", status="recusado", pagamento_id="pag-recusado")
    pagamentos.adicionar("ped-4", status="aprovado", pagamento_id="pag-ok")
    disputa = await abrir.executar(_comando(), CLIENTE_1)
    assert disputa.pagamento_id == "pag-ok"
    assert disputa.status is StatusDisputa.ABERTA
    assert pagamentos.tokens_listagem == ["token-cliente-1"]
    assert banco.eventos == [
        (
            "disputa.aberta",
            {
                "disputa_id": str(disputa.id),
                "pedido_id": "ped-4",
                "cliente_id": "cliente-1",
                "motivo": "item_faltando",
                "valor_solicitado_centavos": 1000,
            },
        )
    ]


async def test_aceita_pagamento_parcialmente_estornado(
    abrir: AbrirDisputa, pagamentos: PagamentosFake
) -> None:
    pagamentos.adicionar("ped-4", status="parcialmente_estornado")
    assert (await abrir.executar(_comando(), CLIENTE_1)).status is StatusDisputa.ABERTA


@pytest.mark.parametrize("status", ["recusado", "estornado"])
async def test_sem_pagamento_contestavel(
    abrir: AbrirDisputa, pagamentos: PagamentosFake, status: str
) -> None:
    pagamentos.adicionar("ped-4", status=status)
    with pytest.raises(PagamentoNaoEncontrado) as erro:
        await abrir.executar(_comando(), CLIENTE_1)
    assert erro.value.status_http == 422


async def test_pedido_sem_pagamentos(abrir: AbrirDisputa) -> None:
    with pytest.raises(PagamentoNaoEncontrado):
        await abrir.executar(_comando("ped-sem-pagamento"), CLIENTE_1)


async def test_pagamento_de_outro_cliente(abrir: AbrirDisputa, pagamentos: PagamentosFake) -> None:
    pagamentos.adicionar("ped-3", cliente_id="cliente-2")
    with pytest.raises(PedidoDeOutroCliente):
        await abrir.executar(_comando("ped-3"), CLIENTE_1)


async def test_valor_acima_do_pago(abrir: AbrirDisputa, pagamentos: PagamentosFake) -> None:
    pagamentos.adicionar("ped-4", valor_centavos=3200)
    with pytest.raises(ValorExcedePago):
        await abrir.executar(_comando(valor=3201), CLIENTE_1)


async def test_uma_disputa_nao_terminal_por_pedido(
    abrir: AbrirDisputa, pagamentos: PagamentosFake, banco: BancoEmMemoria
) -> None:
    pagamentos.adicionar("ped-4")
    primeira = await abrir.executar(_comando(), CLIENTE_1)
    with pytest.raises(DisputaJaAberta) as erro:
        await abrir.executar(_comando(), CLIENTE_1)
    assert erro.value.status_http == 409
    banco.disputas[primeira.id].status = StatusDisputa.IMPROCEDENTE
    segunda = await abrir.executar(_comando(), CLIENTE_1)
    assert segunda.id != primeira.id


async def test_pagamentos_fora_propaga_503(abrir: AbrirDisputa, pagamentos: PagamentosFake) -> None:
    pagamentos.indisponivel = True
    with pytest.raises(ErroDependenciaIndisponivel):
        await abrir.executar(_comando(), CLIENTE_1)


async def test_consultas_respeitam_o_dono(
    abrir: AbrirDisputa,
    pagamentos: PagamentosFake,
    uow: FabricaUnidadeDeTrabalho,
    relogio: RelogioFake,
) -> None:
    pagamentos.adicionar("ped-4", cliente_id="cliente-1")
    pagamentos.adicionar("ped-3", cliente_id="cliente-2")
    do_cliente_1 = await abrir.executar(_comando("ped-4"), CLIENTE_1)
    relogio.avancar(seconds=1)
    do_cliente_2 = await abrir.executar(_comando("ped-3"), CLIENTE_2)
    consultas = ConsultarDisputas(uow)

    itens, total = await consultas.listar(
        status=None, solicitante=CLIENTE_1, deslocamento=0, limite=20
    )
    assert (total, [d.id for d in itens]) == (1, [do_cliente_1.id])
    itens, total = await consultas.listar(status=None, solicitante=ADMIN, deslocamento=0, limite=20)
    assert [d.id for d in itens] == [do_cliente_2.id, do_cliente_1.id]
    itens, total = await consultas.listar(
        status=StatusDisputa.RESOLVIDA, solicitante=ADMIN, deslocamento=0, limite=20
    )
    assert total == 0

    assert (await consultas.obter(do_cliente_1.id, CLIENTE_1)).id == do_cliente_1.id
    assert (await consultas.obter(do_cliente_1.id, ADMIN)).id == do_cliente_1.id
    with pytest.raises(DisputaDeOutroCliente):
        await consultas.obter(do_cliente_2.id, CLIENTE_1)
    with pytest.raises(DisputaNaoEncontrada):
        await consultas.obter(uuid.uuid4(), ADMIN)
