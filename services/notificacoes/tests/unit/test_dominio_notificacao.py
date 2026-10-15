import uuid
from datetime import UTC, datetime, timedelta

import pytest

from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.erros import TransicaoInvalida
from notificacoes.dominio.notificacao import Canal, Notificacao, StatusNotificacao

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
DEPOIS = AGORA + timedelta(seconds=3)


def _email() -> Notificacao:
    return Notificacao.para_email(
        mensagem_id_origem=uuid.uuid4(),
        tipo_evento="pagamento.aprovado",
        destinatario_id="cliente-1",
        destino=None,
        agora=AGORA,
    )


def test_nova_notificacao_de_email_comeca_pendente() -> None:
    notificacao = _email()
    assert notificacao.status is StatusNotificacao.PENDENTE
    assert notificacao.pendente
    assert notificacao.canal is Canal.EMAIL
    assert (notificacao.tentativas, notificacao.enviada_em, notificacao.assinatura_id) == (
        0,
        None,
        None,
    )


def test_notificacao_de_webhook_copia_dados_da_assinatura() -> None:
    assinatura = AssinaturaWebhook.nova(
        url="https://loja.exemplo.com/hook",
        eventos=["pagamento.*"],
        segredo="s" * 40,
        criado_por="loja-1",
        somente_proprios=True,
        agora=AGORA,
        permitir_http=False,
        permitir_rede_interna=False,
    )
    notificacao = Notificacao.para_webhook(
        mensagem_id_origem=uuid.uuid4(),
        tipo_evento="pagamento.aprovado",
        assinatura=assinatura,
        agora=AGORA,
    )
    assert notificacao.canal is Canal.WEBHOOK
    assert notificacao.destino == "https://loja.exemplo.com/hook"
    assert notificacao.destinatario_id == "loja-1"
    assert notificacao.assinatura_id == assinatura.id


def test_registrar_envio() -> None:
    notificacao = _email()
    notificacao.registrar_envio(agora=DEPOIS, destino="cliente-1@exemplo.com")
    assert notificacao.status is StatusNotificacao.ENVIADA
    assert (notificacao.tentativas, notificacao.enviada_em) == (1, DEPOIS)
    assert notificacao.destino == "cliente-1@exemplo.com"


def test_falhas_devolvem_numero_da_retentativa_ate_esgotar() -> None:
    notificacao = _email()
    assert [notificacao.registrar_falha("x", max_retentativas=5) for _ in range(5)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert notificacao.pendente
    assert notificacao.registrar_falha("ainda fora", max_retentativas=5) is None
    assert notificacao.status is StatusNotificacao.FALHOU
    assert (notificacao.tentativas, notificacao.ultimo_erro) == (6, "ainda fora")


def test_erro_e_truncado_em_500_caracteres() -> None:
    notificacao = _email()
    notificacao.registrar_falha("e" * 900, max_retentativas=5)
    assert notificacao.ultimo_erro is not None
    assert len(notificacao.ultimo_erro) == 500


def test_falha_definitiva_e_cancelamento() -> None:
    definitiva = _email()
    definitiva.falhar_definitivamente("perfil inexistente")
    assert (definitiva.status, definitiva.tentativas) == (StatusNotificacao.FALHOU, 1)
    cancelada = _email()
    cancelada.cancelar("assinatura removida")
    assert (cancelada.status, cancelada.tentativas) == (StatusNotificacao.FALHOU, 0)
    assert cancelada.ultimo_erro == "assinatura removida"


def test_notificacao_finalizada_nao_muda_mais() -> None:
    notificacao = _email()
    notificacao.registrar_envio(agora=AGORA)
    with pytest.raises(TransicaoInvalida):
        notificacao.registrar_falha("x", max_retentativas=5)
    with pytest.raises(TransicaoInvalida):
        notificacao.registrar_envio(agora=DEPOIS)


def test_entrega_webhook_registrar() -> None:
    assinatura_id, mensagem_id = uuid.uuid4(), uuid.uuid4()
    entrega = EntregaWebhook.registrar(
        assinatura_id=assinatura_id,
        mensagem_id=mensagem_id,
        tentativa=2,
        status_http=500,
        duracao_ms=12,
        erro=None,
        agora=AGORA,
    )
    assert isinstance(entrega.id, uuid.UUID)
    assert (entrega.assinatura_id, entrega.mensagem_id, entrega.tentativa) == (
        assinatura_id,
        mensagem_id,
        2,
    )
    assert (entrega.status_http, entrega.duracao_ms, entrega.erro, entrega.criado_em) == (
        500,
        12,
        None,
        AGORA,
    )
