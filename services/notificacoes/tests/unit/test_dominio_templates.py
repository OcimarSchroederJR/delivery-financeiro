from typing import Any

import pytest

from notificacoes.dominio.erros import DadosDoEventoInsuficientes
from notificacoes.dominio.templates import MODELOS, formatar_reais, modelo_para

EXEMPLOS: dict[str, dict[str, Any]] = {
    "pagamento.aprovado": {
        "pagamento_id": "pag-1",
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "metodo": "pix",
    },
    "pagamento.recusado": {
        "pagamento_id": "pag-2",
        "pedido_id": "ped-2",
        "cliente_id": "cliente-1",
        "valor_centavos": 600000,
        "motivo": "analise_antifraude",
    },
    "pagamento.estornado": {
        "pagamento_id": "pag-1",
        "estorno_id": "est-1",
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 1000,
        "motivo": "disputa procedente",
    },
    "avaliacao.registrada": {
        "avaliacao_id": "ava-1",
        "pedido_id": "ped-4",
        "restaurante_id": "rest-1",
        "cliente_id": "cliente-1",
        "nota_restaurante": 5,
        "nota_entrega": 4,
    },
    "disputa.aberta": {
        "disputa_id": "disp-1",
        "pedido_id": "ped-4",
        "cliente_id": "cliente-1",
        "motivo": "item_faltando",
        "valor_solicitado_centavos": 1500,
    },
    "disputa.resolvida": {
        "disputa_id": "disp-1",
        "pedido_id": "ped-4",
        "cliente_id": "cliente-1",
        "decisao": "procedente",
        "valor_estornado_centavos": 1500,
    },
    "disputa.estorno_falhou": {
        "disputa_id": "disp-1",
        "pedido_id": "ped-4",
        "motivo": "pagamento_nao_estornavel",
    },
    "entrega.concluida": {
        "pedido_id": "ped-3",
        "cliente_id": "cliente-2",
        "entregador_id": "entregador-1",
        "concluida_em": "2026-10-14T15:00:00Z",
    },
}


@pytest.mark.parametrize(
    ("centavos", "texto"),
    [
        (0, "R$ 0,00"),
        (5, "R$ 0,05"),
        (4590, "R$ 45,90"),
        (123456, "R$ 1.234,56"),
        (100000000, "R$ 1.000.000,00"),
        (-250, "-R$ 2,50"),
    ],
)
def test_formatar_reais(centavos: int, texto: str) -> None:
    assert formatar_reais(centavos) == texto


def test_ha_template_para_cada_exemplo() -> None:
    assert set(MODELOS) == set(EXEMPLOS)


@pytest.mark.parametrize("tipo", sorted(EXEMPLOS))
def test_todo_tipo_com_template_renderiza(tipo: str) -> None:
    modelo = modelo_para(tipo)
    assert modelo is not None
    email = modelo.renderizar(EXEMPLOS[tipo], nome="Ana")
    assert "Ana" in email.corpo
    assert "{" not in email.assunto + email.corpo
    assert EXEMPLOS[tipo]["pedido_id"] in email.assunto + email.corpo


def test_estorno_mostra_o_valor_do_estorno_e_nao_o_do_pagamento() -> None:
    modelo = modelo_para("pagamento.estornado")
    assert modelo is not None
    corpo = modelo.renderizar(EXEMPLOS["pagamento.estornado"], nome="Ana").corpo
    assert "Estornamos R$ 10,00" in corpo


def test_valores_em_reais_e_dados_do_evento() -> None:
    modelo = modelo_para("pagamento.aprovado")
    assert modelo is not None
    email = modelo.renderizar(EXEMPLOS["pagamento.aprovado"], nome="Ana")
    assert email.assunto == "Pagamento aprovado - pedido ped-1"
    assert "R$ 45,90" in email.corpo
    assert "pix" in email.corpo


def test_destinatario_e_o_cliente_ou_o_admin() -> None:
    do_cliente = modelo_para("pagamento.aprovado")
    do_admin = modelo_para("disputa.estorno_falhou")
    assert do_cliente is not None
    assert do_admin is not None
    assert do_cliente.destinatario_id(EXEMPLOS["pagamento.aprovado"]) == "cliente-1"
    assert not do_cliente.para_admin
    assert do_admin.para_admin
    assert do_admin.destinatario_id(EXEMPLOS["disputa.estorno_falhou"]) is None


@pytest.mark.parametrize("dados", [{}, {"cliente_id": ""}, {"cliente_id": 7}])
def test_destinatario_ausente_ou_invalido(dados: dict[str, Any]) -> None:
    modelo = modelo_para("pagamento.aprovado")
    assert modelo is not None
    assert modelo.destinatario_id(dados) is None


@pytest.mark.parametrize("tipo", ["pedido.criado", "pagamento.qualquer", "entrega.saiu"])
def test_tipos_sem_template(tipo: str) -> None:
    assert modelo_para(tipo) is None


def test_campo_ausente_e_falha_definitiva() -> None:
    modelo = modelo_para("pagamento.aprovado")
    assert modelo is not None
    with pytest.raises(DadosDoEventoInsuficientes):
        modelo.renderizar({"pedido_id": "ped-1"}, nome="Ana")


def test_valor_com_chaves_nao_e_interpretado() -> None:
    modelo = modelo_para("pagamento.recusado")
    assert modelo is not None
    dados = {**EXEMPLOS["pagamento.recusado"], "motivo": "{nome} {0}"}
    assert "Motivo: {nome} {0}." in modelo.renderizar(dados, nome="Ana").corpo
