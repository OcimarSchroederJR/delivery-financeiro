"""Tipos e ``dados`` dos eventos publicados (spec §3.5).

Os campos são exatamente os da spec: Notificações depende deles. Mudança
incompatível exige incrementar ``versao`` no envelope.
"""

from typing import Any

from pagamentos.dominio.pagamento import Estorno, Pagamento

TIPO_PAGAMENTO_APROVADO = "pagamento.aprovado"
TIPO_PAGAMENTO_RECUSADO = "pagamento.recusado"
TIPO_PAGAMENTO_ESTORNADO = "pagamento.estornado"


def dados_pagamento_aprovado(pagamento: Pagamento) -> dict[str, Any]:
    return {
        "pagamento_id": str(pagamento.id),
        "pedido_id": pagamento.pedido_id,
        "cliente_id": pagamento.cliente_id,
        "valor_centavos": pagamento.valor_centavos,
        "metodo": pagamento.metodo.value,
    }


def dados_pagamento_recusado(pagamento: Pagamento) -> dict[str, Any]:
    return {
        "pagamento_id": str(pagamento.id),
        "pedido_id": pagamento.pedido_id,
        "cliente_id": pagamento.cliente_id,
        "valor_centavos": pagamento.valor_centavos,
        "motivo": pagamento.motivo_recusa,
    }


def dados_pagamento_estornado(pagamento: Pagamento, estorno: Estorno) -> dict[str, Any]:
    return {
        "pagamento_id": str(pagamento.id),
        "estorno_id": str(estorno.id),
        "pedido_id": pagamento.pedido_id,
        "cliente_id": pagamento.cliente_id,
        "valor_centavos": estorno.valor_centavos,
        "motivo": estorno.motivo,
    }


def evento_de_registro(pagamento: Pagamento) -> tuple[str, dict[str, Any]]:
    """Evento da tentativa de pagamento: aprovado ou recusado."""
    if pagamento.efetivado:
        return TIPO_PAGAMENTO_APROVADO, dados_pagamento_aprovado(pagamento)
    return TIPO_PAGAMENTO_RECUSADO, dados_pagamento_recusado(pagamento)
