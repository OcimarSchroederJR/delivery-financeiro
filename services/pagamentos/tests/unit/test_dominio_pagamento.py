from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.erros import (
    IdempotencyEmProcessamento,
    IdempotencyKeyAusente,
    PagamentoRecusado,
    PedidoDeOutroCliente,
    PedidoJaPago,
    ValorExcedeSaldoEstornavel,
)
from pagamentos.dominio.pagamento import (
    LIMITE_ANTIFRAUDE_CENTAVOS,
    MOTIVO_SALDO_INSUFICIENTE,
    MetodoPagamento,
    Pagamento,
    StatusPagamento,
    exige_analise_antifraude,
)
from pagamentos.dominio.pedido import Pedido

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)


def _aprovado(**extras: Any) -> Pagamento:
    dados: dict[str, Any] = {
        "id": uuid4(),
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "metodo": MetodoPagamento.CARTAO_CREDITO,
        "cartao_final": "0000",
        "agora": AGORA,
    }
    return Pagamento.aprovado(**(dados | extras))


def test_pagamento_aprovado_nasce_efetivado_com_saldo_total() -> None:
    pagamento = _aprovado()
    assert pagamento.status == StatusPagamento.APROVADO
    assert pagamento.motivo_recusa is None
    assert pagamento.criado_em == pagamento.atualizado_em == AGORA
    assert pagamento.efetivado
    assert pagamento.estornos == []
    assert pagamento.valor_estornado_centavos == 0
    assert pagamento.saldo_estornavel_centavos == 4590


def test_pagamento_recusado_guarda_motivo_e_nao_tem_saldo() -> None:
    pagamento = Pagamento.recusado(
        id=uuid4(),
        pedido_id="ped-1",
        cliente_id="cliente-1",
        valor_centavos=4590,
        metodo=MetodoPagamento.CARTAO_CREDITO,
        cartao_final="0002",
        motivo=MOTIVO_SALDO_INSUFICIENTE,
        agora=AGORA,
    )
    assert pagamento.status == StatusPagamento.RECUSADO
    assert pagamento.motivo_recusa == "saldo_insuficiente"
    assert not pagamento.efetivado
    assert pagamento.saldo_estornavel_centavos == 0


def test_pix_nao_tem_cartao_final() -> None:
    pagamento = _aprovado(metodo=MetodoPagamento.PIX, cartao_final=None)
    assert pagamento.cartao_final is None


@pytest.mark.parametrize(
    ("valor", "exige"),
    [(1, False), (LIMITE_ANTIFRAUDE_CENTAVOS, False), (LIMITE_ANTIFRAUDE_CENTAVOS + 1, True)],
)
def test_antifraude_so_acima_de_500000(valor: int, exige: bool) -> None:
    assert LIMITE_ANTIFRAUDE_CENTAVOS == 500_000
    assert exige_analise_antifraude(valor) is exige


@pytest.mark.parametrize("valor", [0, -1])
def test_valor_nao_positivo_e_invalido(valor: int) -> None:
    with pytest.raises(ValueError, match="valor_centavos"):
        _aprovado(valor_centavos=valor)


@pytest.mark.parametrize("final", ["12345", "12a4", "123"])
def test_cartao_final_precisa_de_4_digitos(final: str) -> None:
    with pytest.raises(ValueError, match="cartao_final"):
        _aprovado(cartao_final=final)


def test_motivo_de_recusa_so_existe_em_pagamento_recusado() -> None:
    with pytest.raises(ValueError, match="motivo_recusa"):
        Pagamento(
            id=uuid4(),
            pedido_id="ped-1",
            cliente_id="cliente-1",
            valor_centavos=10,
            metodo=MetodoPagamento.PIX,
            status=StatusPagamento.APROVADO,
            motivo_recusa="qualquer",
            cartao_final=None,
            criado_em=AGORA,
            atualizado_em=AGORA,
        )


def test_dados_cartao_expoe_so_os_ultimos_digitos() -> None:
    cartao = DadosCartao(
        numero="4111111111110000", titular="Fulano de Tal", validade="12/28", cvv="987"
    )
    assert cartao.ultimos_digitos == "0000"
    for texto in (repr(cartao), str(cartao), f"{cartao}"):
        assert "4111111111110000" not in texto
        assert "Fulano" not in texto
        assert "987" not in texto
        assert "0000" in texto


@pytest.mark.parametrize("numero", ["41111111111100a0", "123", "1" * 20, "\u0661" * 16])
def test_dados_cartao_rejeita_numero_fora_do_formato(numero: str) -> None:
    with pytest.raises(ValueError, match="número de cartão inválido") as erro:
        DadosCartao(numero=numero, titular="X", validade="12/28", cvv="123")
    assert numero not in str(erro.value)


def test_pedido_cancelado() -> None:
    assert Pedido("ped-9", "cliente-1", 100, "cancelado").cancelado
    assert not Pedido("ped-1", "cliente-1", 100, "confirmado").cancelado


def test_erros_de_negocio_tem_status_codigo_e_detalhes() -> None:
    pagamento_id = uuid4()
    recusa = PagamentoRecusado(pagamento_id, "saldo_insuficiente")
    assert (recusa.status_http, recusa.codigo) == (409, "PAGAMENTO_RECUSADO")
    assert recusa.detalhes == {"pagamento_id": str(pagamento_id), "motivo": "saldo_insuficiente"}
    excesso = ValorExcedeSaldoEstornavel(120)
    assert (excesso.status_http, excesso.codigo) == (422, "VALOR_EXCEDE_SALDO_ESTORNAVEL")
    assert excesso.detalhes == {"saldo_estornavel_centavos": 120}
    assert (PedidoJaPago().status_http, PedidoJaPago().codigo) == (409, "PEDIDO_JA_PAGO")
    assert (PedidoDeOutroCliente().status_http, PedidoDeOutroCliente().codigo) == (
        403,
        "ACESSO_NEGADO",
    )
    assert IdempotencyKeyAusente().status_http == 400
    assert IdempotencyEmProcessamento().codigo == "IDEMPOTENCY_EM_PROCESSAMENTO"
