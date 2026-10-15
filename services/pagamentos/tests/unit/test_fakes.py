import asyncio
from datetime import timedelta

import pytest

from pagamentos.aplicacao.portas import ResultadoAutorizacao
from pagamentos.dominio.erros import IdempotencyEmProcessamento, PedidoJaPago
from pagamentos.dominio.idempotencia import RegistroIdempotencia
from pagamentos.dominio.pagamento import MetodoPagamento
from pagamentos.testes.fakes import (
    INSTANTE,
    ConsultaPedidosFake,
    EstadoFake,
    GatewayComBarreira,
    RelogioFake,
    UnidadeDeTrabalhoFake,
    pagamento_aprovado,
    pagamento_recusado,
)
from plataforma.erros import ErroDependenciaIndisponivel


async def test_unidade_de_trabalho_sem_commit_desfaz_tudo() -> None:
    estado = EstadoFake()
    existente = pagamento_aprovado(pedido_id="ped-4")
    estado.pagamentos[existente.id] = existente
    async with UnidadeDeTrabalhoFake(estado) as uow:
        await uow.pagamentos.adicionar(pagamento_aprovado())
        uow.eventos.registrar("pagamento.aprovado", {"x": 1})
        obtido = await uow.pagamentos.obter(existente.id)
        assert obtido is not None
        obtido.estornar(valor_centavos=None, motivo="m", estorno_id=existente.id, agora=INSTANTE)
    assert list(estado.pagamentos) == [existente.id]
    assert estado.pagamentos[existente.id].estornos == []
    assert estado.eventos == []
    assert estado.commits == 0


async def test_unidade_de_trabalho_com_commit_mantem() -> None:
    estado = EstadoFake()
    pagamento = pagamento_aprovado()
    async with UnidadeDeTrabalhoFake(estado) as uow:
        await uow.pagamentos.adicionar(pagamento)
        uow.eventos.registrar("pagamento.aprovado", {"x": 1})
        await uow.commit()
    assert estado.pagamentos == {pagamento.id: pagamento}
    assert estado.eventos == [("pagamento.aprovado", {"x": 1})]
    assert estado.commits == 1


async def test_repositorio_fake_emula_um_efetivado_por_pedido() -> None:
    estado = EstadoFake()
    async with UnidadeDeTrabalhoFake(estado) as uow:
        await uow.pagamentos.adicionar(pagamento_recusado(pedido_id="ped-1"))
        await uow.pagamentos.adicionar(pagamento_recusado(pedido_id="ped-1"))
        await uow.pagamentos.adicionar(pagamento_aprovado(pedido_id="ped-1"))
        assert await uow.pagamentos.existe_efetivado("ped-1")
        with pytest.raises(PedidoJaPago):
            await uow.pagamentos.adicionar(pagamento_aprovado(pedido_id="ped-1"))


async def test_repositorio_fake_lista_com_filtros_ordem_e_total() -> None:
    estado = EstadoFake()
    antigo = pagamento_aprovado(pedido_id="ped-1", agora=INSTANTE)
    novo = pagamento_aprovado(pedido_id="ped-4", agora=INSTANTE + timedelta(minutes=1))
    alheio = pagamento_aprovado(pedido_id="ped-3", cliente_id="cliente-2")
    for pagamento in (antigo, novo, alheio):
        estado.pagamentos[pagamento.id] = pagamento
    async with UnidadeDeTrabalhoFake(estado) as uow:
        itens, total = await uow.pagamentos.listar(
            pedido_id=None, cliente_id="cliente-1", deslocamento=0, limite=10
        )
        assert (itens, total) == ([novo, antigo], 2)
        itens, total = await uow.pagamentos.listar(
            pedido_id="ped-3", cliente_id=None, deslocamento=0, limite=10
        )
        assert (itens, total) == ([alheio], 1)


async def test_chaves_fake_emulam_constraint_unica() -> None:
    estado = EstadoFake()
    registro = RegistroIdempotencia.reservar(
        escopo="e", chave="k", hash_requisicao="h", agora=INSTANTE
    )
    async with UnidadeDeTrabalhoFake(estado) as uow:
        await uow.chaves_idempotencia.reservar(registro)
        with pytest.raises(IdempotencyEmProcessamento):
            await uow.chaves_idempotencia.reservar(registro)


async def test_consulta_pedidos_fake() -> None:
    pedidos = ConsultaPedidosFake()
    pedido = await pedidos.obter("ped-1", token="tok")
    assert pedido is not None
    assert (pedido.cliente_id, pedido.valor_total_centavos) == ("cliente-1", 4590)
    assert await pedidos.obter("nao-existe", token="tok") is None
    assert pedidos.chamadas == [("ped-1", "tok"), ("nao-existe", "tok")]
    pedidos.fora = True
    with pytest.raises(ErroDependenciaIndisponivel):
        await pedidos.obter("ped-1", token="tok")


def test_relogio_fake_avanca() -> None:
    relogio = RelogioFake()
    assert relogio() == INSTANTE
    relogio.avancar(timedelta(seconds=61))
    assert relogio() == INSTANTE + timedelta(seconds=61)


async def test_gateway_com_barreira_segura_ate_liberar() -> None:
    gateway = GatewayComBarreira(esperadas=1)
    tarefa = asyncio.create_task(
        gateway.autorizar(metodo=MetodoPagamento.PIX, valor_centavos=10, cartao=None)
    )
    await gateway.aguardar_entradas()
    assert not tarefa.done()
    gateway.liberar.set()
    assert await tarefa == ResultadoAutorizacao(aprovado=True)
