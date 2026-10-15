import pytest

from notificacoes.adaptadores.email_smtp import EnviadorSmtp, montar_mensagem
from notificacoes.aplicacao.portas import FalhaNoEnvioDeEmail


def test_monta_mensagem_em_utf8() -> None:
    mensagem = montar_mensagem(
        remetente="notificacoes@financeiro-eq5.local",
        para="cliente-1@exemplo.com",
        assunto="[Ação necessária] Estorno",
        corpo="Olá, Ana!\nR$ 45,90",
    )
    assert mensagem["From"] == "notificacoes@financeiro-eq5.local"
    assert mensagem["To"] == "cliente-1@exemplo.com"
    assert mensagem["Subject"] == "[Ação necessária] Estorno"
    assert "R$ 45,90" in mensagem.get_content()


async def test_smtp_indisponivel_vira_falha_transitoria() -> None:
    enviador = EnviadorSmtp(
        host="127.0.0.1", porta=1, remetente="notificacoes@x.local", timeout_segundos=1.0
    )
    with pytest.raises(FalhaNoEnvioDeEmail):
        await enviador.enviar(para="a@exemplo.com", assunto="x", corpo="y")
