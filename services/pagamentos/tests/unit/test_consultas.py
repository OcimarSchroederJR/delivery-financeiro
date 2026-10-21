from datetime import timedelta
from uuid import uuid4

import pytest

from pagamentos.aplicacao.consultas import ConsultasPagamentos
from pagamentos.aplicacao.solicitante import Solicitante
from pagamentos.dominio.erros import PagamentoNaoEncontrado
from pagamentos.dominio.pagamento import Pagamento
from pagamentos.testes.fakes import INSTANTE, EstadoFake, fabrica_fake, pagamento_aprovado

CLIENTE_1 = Solicitante(id="cliente-1", papel="cliente", token="t1")
ADMIN = Solicitante(id="admin-1", papel="admin", token="ta")
SERVICO = Solicitante(id="avaliacoes", papel="servico", token="ts")


def _semear(estado: EstadoFake) -> tuple[Pagamento, Pagamento, Pagamento]:
    antigo = pagamento_aprovado(pedido_id="ped-1", agora=INSTANTE)
    novo = pagamento_aprovado(pedido_id="ped-4", agora=INSTANTE + timedelta(minutes=5))
    alheio = pagamento_aprovado(pedido_id="ped-3", cliente_id="cliente-2")
    for pagamento in (antigo, novo, alheio):
        estado.pagamentos[pagamento.id] = pagamento
    return antigo, novo, alheio


async def test_cliente_obtem_o_proprio_pagamento() -> None:
    estado = EstadoFake()
    antigo, _, _ = _semear(estado)
    assert await ConsultasPagamentos(fabrica_fake(estado)).obter(antigo.id, CLIENTE_1) == antigo


async def test_cliente_nao_ve_pagamento_de_outro() -> None:
    estado = EstadoFake()
    _, _, alheio = _semear(estado)
    with pytest.raises(PagamentoNaoEncontrado):
        await ConsultasPagamentos(fabrica_fake(estado)).obter(alheio.id, CLIENTE_1)


async def test_admin_ve_qualquer_pagamento() -> None:
    estado = EstadoFake()
    _, _, alheio = _semear(estado)
    assert await ConsultasPagamentos(fabrica_fake(estado)).obter(alheio.id, ADMIN) == alheio


async def test_pagamento_inexistente() -> None:
    with pytest.raises(PagamentoNaoEncontrado):
        await ConsultasPagamentos(fabrica_fake(EstadoFake())).obter(uuid4(), ADMIN)


async def test_cliente_lista_so_os_seus_mais_recentes_primeiro() -> None:
    estado = EstadoFake()
    antigo, novo, _ = _semear(estado)
    itens, total = await ConsultasPagamentos(fabrica_fake(estado)).listar(
        CLIENTE_1, pedido_id=None, deslocamento=0, limite=20
    )
    assert (itens, total) == ([novo, antigo], 2)


@pytest.mark.parametrize("solicitante", [ADMIN, SERVICO])
async def test_admin_e_servico_listam_tudo_e_filtram_por_pedido(solicitante: Solicitante) -> None:
    estado = EstadoFake()
    _, _, alheio = _semear(estado)
    consultas = ConsultasPagamentos(fabrica_fake(estado))
    _, total = await consultas.listar(solicitante, pedido_id=None, deslocamento=0, limite=20)
    assert total == 3
    itens, total = await consultas.listar(solicitante, pedido_id="ped-3", deslocamento=0, limite=20)
    assert (itens, total) == ([alheio], 1)


async def test_listagem_paginada() -> None:
    estado = EstadoFake()
    antigo, _, _ = _semear(estado)
    itens, total = await ConsultasPagamentos(fabrica_fake(estado)).listar(
        CLIENTE_1, pedido_id=None, deslocamento=1, limite=1
    )
    assert (itens, total) == ([antigo], 2)


async def test_listar_estornos_do_pagamento() -> None:
    estado = EstadoFake()
    antigo, _, _ = _semear(estado)
    estorno = antigo.estornar(valor_centavos=100, motivo="m", estorno_id=uuid4(), agora=INSTANTE)
    consultas = ConsultasPagamentos(fabrica_fake(estado))
    assert await consultas.listar_estornos(antigo.id, CLIENTE_1) == [estorno]


async def test_cliente_nao_lista_estornos_de_outro() -> None:
    estado = EstadoFake()
    _, _, alheio = _semear(estado)
    with pytest.raises(PagamentoNaoEncontrado):
        await ConsultasPagamentos(fabrica_fake(estado)).listar_estornos(alheio.id, CLIENTE_1)
