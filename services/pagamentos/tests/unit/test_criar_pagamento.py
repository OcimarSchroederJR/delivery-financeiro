from uuid import UUID

import pytest

from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.aplicacao.criar_pagamento import ComandoCriarPagamento, CriarPagamento
from pagamentos.aplicacao.idempotencia import ReservaIdempotencia
from pagamentos.aplicacao.portas import GatewayDePagamento, ResultadoAutorizacao
from pagamentos.aplicacao.solicitante import Solicitante
from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.erros import (
    PagamentoRecusado,
    PedidoCancelado,
    PedidoDeOutroCliente,
    PedidoInexistente,
    PedidoJaPago,
    PedidoSemValor,
)
from pagamentos.dominio.eventos import dados_pagamento_aprovado, dados_pagamento_recusado
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave
from pagamentos.dominio.pagamento import MetodoPagamento, StatusPagamento
from pagamentos.dominio.pedido import Pedido
from pagamentos.testes.fakes import (
    INSTANTE,
    ApresentadorFake,
    ConsultaPedidosFake,
    EstadoFake,
    RelogioFake,
    fabrica_fake,
    pagamento_aprovado,
    pagamento_recusado,
)
from plataforma.erros import ErroDependenciaIndisponivel

ID_FIXO = UUID("00000000-0000-4000-8000-000000000001")
CLIENTE_1 = Solicitante(id="cliente-1", papel="cliente", token="tok-c1")
ADMIN = Solicitante(id="admin-1", papel="admin", token="tok-a1")
ESCOPO = "POST /v1/pagamentos"


def _cartao(final: str = "0000") -> DadosCartao:
    return DadosCartao(
        numero="411111111111" + final, titular="Fulano de Tal", validade="12/28", cvv="123"
    )


def _comando(pedido_id: str = "ped-1", final: str = "0000") -> ComandoCriarPagamento:
    return ComandoCriarPagamento(pedido_id, MetodoPagamento.CARTAO_CREDITO, _cartao(final))


def _caso(
    estado: EstadoFake,
    *,
    pedidos: ConsultaPedidosFake | None = None,
    gateway: GatewayDePagamento | None = None,
) -> CriarPagamento:
    return CriarPagamento(
        fabrica_uow=fabrica_fake(estado),
        pedidos=pedidos or ConsultaPedidosFake(),
        gateway=gateway or GatewaySimulado(),
        apresentador=ApresentadorFake(),
        relogio=RelogioFake(),
        gerar_id=lambda: ID_FIXO,
    )


class GatewayComConcorrente:
    """Durante a autorização, outra requisição aprova um pagamento do mesmo pedido."""

    def __init__(self, estado: EstadoFake) -> None:
        self._estado = estado

    async def autorizar(self, **_: object) -> ResultadoAutorizacao:
        concorrente = pagamento_aprovado(pedido_id="ped-1")
        self._estado.pagamentos[concorrente.id] = concorrente
        return ResultadoAutorizacao(aprovado=True)


async def test_aprova_pagamento_com_cartao() -> None:
    estado = EstadoFake()
    pagamento = await _caso(estado).executar(_comando(), CLIENTE_1)
    assert pagamento.id == ID_FIXO
    assert pagamento.status == StatusPagamento.APROVADO
    assert (pagamento.valor_centavos, pagamento.cliente_id) == (4590, "cliente-1")
    assert (pagamento.cartao_final, pagamento.criado_em) == ("0000", INSTANTE)
    assert estado.pagamentos == {ID_FIXO: pagamento}
    assert estado.eventos == [("pagamento.aprovado", dados_pagamento_aprovado(pagamento))]
    assert estado.commits == 1


async def test_aprova_pix_sem_cartao() -> None:
    pagamento = await _caso(EstadoFake()).executar(
        ComandoCriarPagamento("ped-1", MetodoPagamento.PIX), CLIENTE_1
    )
    assert (pagamento.metodo, pagamento.cartao_final) == (MetodoPagamento.PIX, None)


async def test_repassa_o_token_do_usuario_para_a_eq3() -> None:
    pedidos = ConsultaPedidosFake()
    await _caso(EstadoFake(), pedidos=pedidos).executar(_comando(), CLIENTE_1)
    assert pedidos.chamadas == [("ped-1", "tok-c1")]


async def test_antifraude_recusa_sem_chamar_o_gateway() -> None:
    estado = EstadoFake()
    # Final 0119 daria timeout se o gateway fosse chamado.
    with pytest.raises(PagamentoRecusado) as erro:
        await _caso(estado).executar(_comando("ped-2", final="0119"), CLIENTE_1)
    assert (erro.value.pagamento_id, erro.value.motivo) == (ID_FIXO, "analise_antifraude")
    recusado = estado.pagamentos[ID_FIXO]
    assert recusado.status == StatusPagamento.RECUSADO
    assert estado.eventos == [("pagamento.recusado", dados_pagamento_recusado(recusado))]


async def test_saldo_insuficiente_recusa_e_persiste_a_tentativa() -> None:
    estado = EstadoFake()
    with pytest.raises(PagamentoRecusado) as erro:
        await _caso(estado).executar(_comando(final="0002"), CLIENTE_1)
    assert erro.value.motivo == "saldo_insuficiente"
    assert estado.pagamentos[ID_FIXO].motivo_recusa == "saldo_insuficiente"
    assert [tipo for tipo, _ in estado.eventos] == ["pagamento.recusado"]


async def test_timeout_do_gateway_nao_persiste_nada() -> None:
    estado = EstadoFake()
    with pytest.raises(ErroDependenciaIndisponivel) as erro:
        await _caso(estado).executar(_comando(final="0119"), CLIENTE_1)
    assert erro.value.dependencia == "gateway"
    assert (estado.pagamentos, estado.eventos) == ({}, [])


async def test_eq3_fora_vira_dependencia_indisponivel() -> None:
    pedidos = ConsultaPedidosFake()
    pedidos.fora = True
    with pytest.raises(ErroDependenciaIndisponivel):
        await _caso(EstadoFake(), pedidos=pedidos).executar(_comando(), CLIENTE_1)


async def test_pedido_inexistente() -> None:
    with pytest.raises(PedidoInexistente):
        await _caso(EstadoFake()).executar(_comando("ped-x"), CLIENTE_1)


async def test_cliente_nao_paga_pedido_de_outro_cliente() -> None:
    with pytest.raises(PedidoDeOutroCliente):
        await _caso(EstadoFake()).executar(_comando("ped-3"), CLIENTE_1)


async def test_admin_paga_pedido_de_qualquer_cliente() -> None:
    pagamento = await _caso(EstadoFake()).executar(_comando("ped-3"), ADMIN)
    assert pagamento.cliente_id == "cliente-2"


async def test_pedido_cancelado() -> None:
    pedidos = ConsultaPedidosFake()
    pedidos.adicionar(Pedido("ped-c", "cliente-1", 100, "cancelado"))
    with pytest.raises(PedidoCancelado):
        await _caso(EstadoFake(), pedidos=pedidos).executar(_comando("ped-c"), CLIENTE_1)


async def test_pedido_sem_valor() -> None:
    pedidos = ConsultaPedidosFake()
    pedidos.adicionar(Pedido("ped-z", "cliente-1", 0, "confirmado"))
    with pytest.raises(PedidoSemValor):
        await _caso(EstadoFake(), pedidos=pedidos).executar(_comando("ped-z"), CLIENTE_1)


async def test_pedido_ja_pago_nem_chama_o_gateway() -> None:
    estado = EstadoFake()
    existente = pagamento_aprovado(pedido_id="ped-1")
    estado.pagamentos[existente.id] = existente
    with pytest.raises(PedidoJaPago):
        await _caso(estado).executar(_comando(final="0119"), CLIENTE_1)


async def test_recusa_anterior_nao_impede_novo_pagamento() -> None:
    estado = EstadoFake()
    anterior = pagamento_recusado(pedido_id="ped-1")
    estado.pagamentos[anterior.id] = anterior
    pagamento = await _caso(estado).executar(_comando(), CLIENTE_1)
    assert pagamento.status == StatusPagamento.APROVADO


async def test_corrida_com_outro_pagamento_vira_pedido_ja_pago() -> None:
    estado = EstadoFake()
    with pytest.raises(PedidoJaPago):
        await _caso(estado, gateway=GatewayComConcorrente(estado)).executar(_comando(), CLIENTE_1)
    assert sum(p.efetivado for p in estado.pagamentos.values()) == 1
    assert ID_FIXO not in estado.pagamentos
    assert estado.eventos == []


async def test_conclui_a_chave_na_mesma_transacao() -> None:
    estado = EstadoFake()
    estado.chaves[(ESCOPO, "k-1")] = RegistroIdempotencia.reservar(
        escopo=ESCOPO, chave="k-1", hash_requisicao="h", agora=INSTANTE
    )
    await _caso(estado).executar(_comando(), CLIENTE_1, ReservaIdempotencia(ESCOPO, "k-1"))
    registro = estado.chaves[(ESCOPO, "k-1")]
    assert registro.status == StatusChave.CONCLUIDA
    assert registro.resposta() == (201, {"id": str(ID_FIXO), "status": "aprovado"})
    assert estado.commits == 1


async def test_recusa_grava_409_na_chave() -> None:
    estado = EstadoFake()
    estado.chaves[(ESCOPO, "k-1")] = RegistroIdempotencia.reservar(
        escopo=ESCOPO, chave="k-1", hash_requisicao="h", agora=INSTANTE
    )
    with pytest.raises(PagamentoRecusado):
        await _caso(estado).executar(
            _comando(final="0002"), CLIENTE_1, ReservaIdempotencia(ESCOPO, "k-1")
        )
    status, corpo = estado.chaves[(ESCOPO, "k-1")].resposta()
    assert status == 409
    assert (corpo["codigo"], corpo["pagamento_id"]) == ("PAGAMENTO_RECUSADO", str(ID_FIXO))


def test_comando_de_cartao_exige_os_dados_do_cartao() -> None:
    with pytest.raises(ValueError, match="cartão"):
        ComandoCriarPagamento("ped-1", MetodoPagamento.CARTAO_CREDITO)
