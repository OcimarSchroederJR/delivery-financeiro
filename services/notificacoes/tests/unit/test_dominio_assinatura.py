import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.erros import PadraoDeEventoInvalido, UrlDeWebhookInvalida

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)


def _nova(**mudancas: Any) -> AssinaturaWebhook:
    argumentos: dict[str, Any] = {
        "url": "https://exemplo.com/webhook",
        "eventos": ["pagamento.*"],
        "segredo": "segredo-super-secreto",
        "criado_por": "cliente-1",
        "somente_proprios": False,
        "agora": AGORA,
        "permitir_http": False,
        "permitir_rede_interna": False,
    }
    return AssinaturaWebhook.nova(**{**argumentos, **mudancas})


def test_nova_valida_e_deduplica_padroes() -> None:
    assinatura = _nova(eventos=["pagamento.*", "pagamento.*", "disputa.resolvida"])
    assert assinatura.eventos == ("pagamento.*", "disputa.resolvida")
    assert assinatura.ativa is True
    assert isinstance(assinatura.id, uuid.UUID)
    assert assinatura.criado_em == AGORA


def test_nova_rejeita_padrao_invalido() -> None:
    with pytest.raises(PadraoDeEventoInvalido):
        _nova(eventos=["Pagamento"])


@pytest.mark.parametrize("eventos", [[], [f"a.e{i}" for i in range(21)]])
def test_nova_rejeita_lista_vazia_ou_longa(eventos: list[str]) -> None:
    with pytest.raises(PadraoDeEventoInvalido):
        _nova(eventos=eventos)


def test_nova_rejeita_url_http_em_producao() -> None:
    with pytest.raises(UrlDeWebhookInvalida):
        _nova(url="http://exemplo.com/webhook")


def test_recebe_por_padrao() -> None:
    assinatura = _nova()
    assert assinatura.recebe("pagamento.aprovado", {})
    assert not assinatura.recebe("disputa.aberta", {})


def test_assinatura_de_nao_admin_so_recebe_eventos_proprios() -> None:
    assinatura = _nova(somente_proprios=True)
    assert assinatura.recebe("pagamento.aprovado", {"cliente_id": "cliente-1"})
    assert not assinatura.recebe("pagamento.aprovado", {"cliente_id": "cliente-2"})
    assert assinatura.recebe("pagamento.aprovado", {"restaurante_id": "cliente-1"})
    assert not assinatura.recebe("pagamento.aprovado", {})


def test_inativa_nao_recebe() -> None:
    assinatura = _nova()
    assinatura.desativar()
    assert assinatura.ativa is False
    assert not assinatura.recebe("pagamento.aprovado", {})


def test_pode_ser_gerida_pelo_dono_ou_admin() -> None:
    assinatura = _nova()
    assert assinatura.pode_ser_gerida_por("cliente-1", admin=False)
    assert not assinatura.pode_ser_gerida_por("cliente-2", admin=False)
    assert assinatura.pode_ser_gerida_por("admin-1", admin=True)


def test_repr_nao_mostra_segredo() -> None:
    assert "segredo-super-secreto" not in repr(_nova())
