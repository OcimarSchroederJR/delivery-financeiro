from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pagamentos.dominio.erros import (
    PagamentoNaoEstornavel,
    ValorDeEstornoInvalido,
    ValorExcedeSaldoEstornavel,
)
from pagamentos.dominio.pagamento import MetodoPagamento, Pagamento, StatusPagamento

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
DEPOIS = AGORA + timedelta(hours=2)


def _aprovado(valor: int = 4590) -> Pagamento:
    return Pagamento.aprovado(
        id=uuid4(),
        pedido_id="ped-1",
        cliente_id="cliente-1",
        valor_centavos=valor,
        metodo=MetodoPagamento.PIX,
        cartao_final=None,
        agora=AGORA,
    )


def test_estorno_parcial() -> None:
    pagamento = _aprovado()
    estorno_id = uuid4()
    estorno = pagamento.estornar(
        valor_centavos=1000, motivo="item faltando", estorno_id=estorno_id, agora=DEPOIS
    )
    assert estorno.id == estorno_id
    assert estorno.pagamento_id == pagamento.id
    assert (estorno.valor_centavos, estorno.motivo, estorno.criado_em) == (
        1000,
        "item faltando",
        DEPOIS,
    )
    assert pagamento.status == StatusPagamento.PARCIALMENTE_ESTORNADO
    assert pagamento.atualizado_em == DEPOIS
    assert pagamento.valor_estornado_centavos == 1000
    assert pagamento.saldo_estornavel_centavos == 3590
    assert pagamento.estornos == [estorno]


def test_estorno_do_restante_fecha_o_pagamento() -> None:
    pagamento = _aprovado()
    pagamento.estornar(valor_centavos=1000, motivo="a", estorno_id=uuid4(), agora=DEPOIS)
    pagamento.estornar(valor_centavos=3590, motivo="b", estorno_id=uuid4(), agora=DEPOIS)
    assert pagamento.status == StatusPagamento.ESTORNADO
    assert pagamento.saldo_estornavel_centavos == 0
    assert pagamento.valor_estornado_centavos == 4590


def test_estorno_total_direto() -> None:
    pagamento = _aprovado()
    pagamento.estornar(valor_centavos=4590, motivo="x", estorno_id=uuid4(), agora=DEPOIS)
    assert pagamento.status == StatusPagamento.ESTORNADO


def test_valor_ausente_estorna_o_saldo_inteiro() -> None:
    pagamento = _aprovado()
    pagamento.estornar(valor_centavos=590, motivo="a", estorno_id=uuid4(), agora=DEPOIS)
    estorno = pagamento.estornar(valor_centavos=None, motivo="b", estorno_id=uuid4(), agora=DEPOIS)
    assert estorno.valor_centavos == 4000
    assert pagamento.status == StatusPagamento.ESTORNADO


def test_valor_acima_do_saldo_e_recusado_sem_alterar_o_pagamento() -> None:
    pagamento = _aprovado()
    pagamento.estornar(valor_centavos=4000, motivo="a", estorno_id=uuid4(), agora=DEPOIS)
    with pytest.raises(ValorExcedeSaldoEstornavel) as erro:
        pagamento.estornar(valor_centavos=591, motivo="b", estorno_id=uuid4(), agora=DEPOIS)
    assert erro.value.saldo_estornavel_centavos == 590
    assert len(pagamento.estornos) == 1
    assert pagamento.status == StatusPagamento.PARCIALMENTE_ESTORNADO


@pytest.mark.parametrize("valor", [0, -10])
def test_valor_nao_positivo_e_invalido(valor: int) -> None:
    with pytest.raises(ValorDeEstornoInvalido):
        _aprovado().estornar(valor_centavos=valor, motivo="a", estorno_id=uuid4(), agora=DEPOIS)


def test_pagamento_recusado_nao_e_estornavel() -> None:
    pagamento = Pagamento.recusado(
        id=uuid4(),
        pedido_id="ped-1",
        cliente_id="cliente-1",
        valor_centavos=100,
        metodo=MetodoPagamento.PIX,
        cartao_final=None,
        motivo="saldo_insuficiente",
        agora=AGORA,
    )
    with pytest.raises(PagamentoNaoEstornavel):
        pagamento.estornar(valor_centavos=None, motivo="a", estorno_id=uuid4(), agora=DEPOIS)


def test_pagamento_totalmente_estornado_nao_e_estornavel() -> None:
    pagamento = _aprovado()
    pagamento.estornar(valor_centavos=None, motivo="a", estorno_id=uuid4(), agora=DEPOIS)
    with pytest.raises(PagamentoNaoEstornavel):
        pagamento.estornar(valor_centavos=1, motivo="b", estorno_id=uuid4(), agora=DEPOIS)
