from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from pagamentos.aplicacao.estornar_pagamento import (
    ComandoEstornar,
    EstornarPagamento,
    ResultadoEstorno,
)
from pagamentos.aplicacao.idempotencia import ReservaIdempotencia
from pagamentos.dominio.erros import (
    PagamentoNaoEncontrado,
    PagamentoNaoEstornavel,
    ValorExcedeSaldoEstornavel,
)
from pagamentos.dominio.eventos import dados_pagamento_estornado
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave
from pagamentos.dominio.pagamento import Pagamento, StatusPagamento
from pagamentos.testes.fakes import (
    INSTANTE,
    ApresentadorFake,
    EstadoFake,
    RelogioFake,
    fabrica_fake,
    pagamento_aprovado,
    pagamento_recusado,
)

ESTORNO_ID = UUID("00000000-0000-4000-8000-0000000000e1")
DEPOIS = INSTANTE + timedelta(hours=1)
ESCOPO = "POST /v1/pagamentos/x/estornos"


def _caso(estado: EstadoFake) -> EstornarPagamento:
    return EstornarPagamento(
        fabrica_uow=fabrica_fake(estado),
        apresentador=ApresentadorFake(),
        relogio=RelogioFake(DEPOIS),
        gerar_id=lambda: ESTORNO_ID,
    )


def _semear(estado: EstadoFake, pagamento: Pagamento | None = None) -> Pagamento:
    pagamento = pagamento or pagamento_aprovado()
    estado.pagamentos[pagamento.id] = pagamento
    return pagamento


def _reservar(estado: EstadoFake) -> ReservaIdempotencia:
    estado.chaves[(ESCOPO, "disputa-1")] = RegistroIdempotencia.reservar(
        escopo=ESCOPO, chave="disputa-1", hash_requisicao="h", agora=INSTANTE
    )
    return ReservaIdempotencia(ESCOPO, "disputa-1")


async def test_estorno_parcial_grava_e_publica_evento() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    resultado = await _caso(estado).executar(ComandoEstornar(pagamento.id, "item faltando", 1000))
    assert isinstance(resultado, ResultadoEstorno)
    estorno = resultado.estorno
    assert (estorno.id, estorno.valor_centavos, estorno.criado_em) == (ESTORNO_ID, 1000, DEPOIS)
    assert resultado.status_pagamento == StatusPagamento.PARCIALMENTE_ESTORNADO
    salvo = estado.pagamentos[pagamento.id]
    assert salvo.status == StatusPagamento.PARCIALMENTE_ESTORNADO
    assert (salvo.saldo_estornavel_centavos, salvo.atualizado_em) == (3590, DEPOIS)
    assert estado.eventos == [("pagamento.estornado", dados_pagamento_estornado(salvo, estorno))]
    assert estado.commits == 1


async def test_sem_valor_estorna_o_saldo_inteiro() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    resultado = await _caso(estado).executar(ComandoEstornar(pagamento.id, "disputa"))
    assert resultado.estorno.valor_centavos == 4590
    assert resultado.status_pagamento == StatusPagamento.ESTORNADO
    assert estado.pagamentos[pagamento.id].status == StatusPagamento.ESTORNADO


async def test_valor_acima_do_saldo_nao_altera_nada() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    with pytest.raises(ValorExcedeSaldoEstornavel) as erro:
        await _caso(estado).executar(ComandoEstornar(pagamento.id, "x", 5000))
    assert erro.value.saldo_estornavel_centavos == 4590
    salvo = estado.pagamentos[pagamento.id]
    assert (salvo.status, salvo.estornos) == (StatusPagamento.APROVADO, [])
    assert (estado.eventos, estado.commits) == ([], 0)


async def test_pagamento_inexistente() -> None:
    with pytest.raises(PagamentoNaoEncontrado):
        await _caso(EstadoFake()).executar(ComandoEstornar(uuid4(), "x"))


async def test_pagamento_recusado_nao_e_estornavel() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado, pagamento_recusado())
    with pytest.raises(PagamentoNaoEstornavel):
        await _caso(estado).executar(ComandoEstornar(pagamento.id, "x"))


async def test_conclui_a_chave_na_mesma_transacao() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    reserva = _reservar(estado)
    await _caso(estado).executar(ComandoEstornar(pagamento.id, "x", 1000), reserva)
    registro = estado.chaves[(ESCOPO, "disputa-1")]
    assert registro.resposta() == (
        201,
        {"id": str(ESTORNO_ID), "valor_centavos": 1000, "status": "parcialmente_estornado"},
    )


async def test_erro_de_negocio_deixa_a_chave_para_o_executor() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    reserva = _reservar(estado)
    with pytest.raises(ValorExcedeSaldoEstornavel):
        await _caso(estado).executar(ComandoEstornar(pagamento.id, "x", 9999), reserva)
    assert estado.chaves[(ESCOPO, "disputa-1")].status == StatusChave.EM_PROCESSAMENTO
