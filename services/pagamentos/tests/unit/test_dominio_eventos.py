from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pagamentos.dominio.eventos import (
    TIPO_PAGAMENTO_APROVADO,
    TIPO_PAGAMENTO_ESTORNADO,
    TIPO_PAGAMENTO_RECUSADO,
    dados_pagamento_estornado,
    evento_de_registro,
)
from pagamentos.dominio.pagamento import MetodoPagamento, Pagamento

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)


def _pagamento(aprovado: bool) -> Pagamento:
    comum: dict[str, Any] = {
        "id": uuid4(),
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "metodo": MetodoPagamento.CARTAO_CREDITO,
        "cartao_final": "0002",
        "agora": AGORA,
    }
    if aprovado:
        return Pagamento.aprovado(**comum)
    return Pagamento.recusado(motivo="saldo_insuficiente", **comum)


def test_evento_de_pagamento_aprovado_tem_exatamente_os_campos_da_spec() -> None:
    pagamento = _pagamento(aprovado=True)
    tipo, dados = evento_de_registro(pagamento)
    assert tipo == TIPO_PAGAMENTO_APROVADO == "pagamento.aprovado"
    assert dados == {
        "pagamento_id": str(pagamento.id),
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "metodo": "cartao_credito",
    }


def test_evento_de_pagamento_recusado_tem_exatamente_os_campos_da_spec() -> None:
    pagamento = _pagamento(aprovado=False)
    tipo, dados = evento_de_registro(pagamento)
    assert tipo == TIPO_PAGAMENTO_RECUSADO == "pagamento.recusado"
    assert dados == {
        "pagamento_id": str(pagamento.id),
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "motivo": "saldo_insuficiente",
    }


def test_evento_de_estorno_tem_exatamente_os_campos_da_spec() -> None:
    pagamento = _pagamento(aprovado=True)
    estorno = pagamento.estornar(
        valor_centavos=1000, motivo="disputa procedente", estorno_id=uuid4(), agora=AGORA
    )
    assert TIPO_PAGAMENTO_ESTORNADO == "pagamento.estornado"
    assert dados_pagamento_estornado(pagamento, estorno) == {
        "pagamento_id": str(pagamento.id),
        "estorno_id": str(estorno.id),
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 1000,
        "motivo": "disputa procedente",
    }
