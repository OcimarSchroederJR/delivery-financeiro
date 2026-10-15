import pytest

from notificacoes.dominio.erros import PadraoDeEventoInvalido
from notificacoes.dominio.padroes import padrao_casa, validar_padrao


@pytest.mark.parametrize(
    ("padrao", "tipo", "esperado"),
    [
        ("pagamento.*", "pagamento.aprovado", True),
        ("pagamento.*", "disputa.aberta", False),
        ("pagamento.*", "pagamento", False),
        ("pagamento.aprovado", "pagamento.aprovado", True),
        ("pagamento.aprovado", "pagamento.recusado", False),
        ("*.aprovado", "pagamento.aprovado", True),
        ("*", "pagamento.aprovado", False),
        ("#", "pagamento.aprovado", True),
        ("pagamento.#", "pagamento.aprovado", True),
        ("pagamento.#", "pagamento", True),
        ("#.estornado", "pagamento.estornado", True),
        ("#.estornado", "pagamento.aprovado", False),
    ],
)
def test_padrao_casa_como_routing_key_amqp(padrao: str, tipo: str, esperado: bool) -> None:
    assert padrao_casa(padrao, tipo) is esperado


@pytest.mark.parametrize(
    "padrao", ["pagamento.*", "#", "*.aprovado", "disputa.estorno_falhou", "a.b.c"]
)
def test_padroes_validos(padrao: str) -> None:
    assert validar_padrao(padrao) == padrao


@pytest.mark.parametrize(
    "padrao",
    [
        "",
        "Pagamento.*",
        "pagamento..aprovado",
        "pagamento.**",
        "pagamento.a-b",
        ".pagamento",
        "x" * 101,
    ],
)
def test_padroes_invalidos(padrao: str) -> None:
    with pytest.raises(PadraoDeEventoInvalido):
        validar_padrao(padrao)


def test_erro_de_padrao_e_422_com_codigo() -> None:
    with pytest.raises(PadraoDeEventoInvalido) as erro:
        validar_padrao("NADA")
    assert erro.value.status_http == 422
    assert erro.value.codigo == "PADRAO_DE_EVENTO_INVALIDO"
    assert erro.value.detalhes == {"padrao": "NADA"}
