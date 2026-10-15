import json
from uuid import uuid4

from pagamentos.adaptadores.mensageria.especificacao import criar_broker_documentado
from pagamentos.adaptadores.mensageria.esquemas import EVENTOS_PUBLICADOS
from pagamentos.api import TITULO, VERSAO
from pagamentos.dominio.eventos import (
    TIPO_PAGAMENTO_APROVADO,
    TIPO_PAGAMENTO_ESTORNADO,
    TIPO_PAGAMENTO_RECUSADO,
    dados_pagamento_aprovado,
    dados_pagamento_estornado,
    dados_pagamento_recusado,
)
from pagamentos.testes.fakes import INSTANTE, pagamento_aprovado, pagamento_recusado
from plataforma.contratos import asyncapi_json

CAMPOS_DA_SPEC = {
    "pagamento.aprovado": {"pagamento_id", "pedido_id", "cliente_id", "valor_centavos", "metodo"},
    "pagamento.recusado": {"pagamento_id", "pedido_id", "cliente_id", "valor_centavos", "motivo"},
    "pagamento.estornado": {
        "pagamento_id",
        "estorno_id",
        "pedido_id",
        "cliente_id",
        "valor_centavos",
        "motivo",
    },
}


def test_asyncapi_documenta_os_tres_eventos_com_os_campos_da_spec() -> None:
    documento = json.loads(
        asyncapi_json(criar_broker_documentado(), titulo=f"{TITULO} (eventos)", versao=VERSAO)
    )
    assert set(CAMPOS_DA_SPEC) <= set(documento["channels"])
    esquemas = documento["components"]["schemas"]
    for tipo, campos in CAMPOS_DA_SPEC.items():
        nome = EVENTOS_PUBLICADOS[tipo].dados.__name__
        assert set(esquemas[nome]["properties"]) == campos
        assert set(esquemas[nome]["required"]) == campos


def test_dados_gerados_pelo_dominio_seguem_o_esquema_documentado() -> None:
    aprovado = pagamento_aprovado()
    estorno = aprovado.estornar(valor_centavos=100, motivo="m", estorno_id=uuid4(), agora=INSTANTE)
    recusado = pagamento_recusado(motivo="analise_antifraude")
    for tipo, dados in (
        (TIPO_PAGAMENTO_APROVADO, dados_pagamento_aprovado(aprovado)),
        (TIPO_PAGAMENTO_RECUSADO, dados_pagamento_recusado(recusado)),
        (TIPO_PAGAMENTO_ESTORNADO, dados_pagamento_estornado(aprovado, estorno)),
    ):
        assert set(dados) == CAMPOS_DA_SPEC[tipo]
        EVENTOS_PUBLICADOS[tipo].dados.model_validate(dados)
