from datetime import UTC, datetime
from typing import Any

import pytest

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria, UnidadeDeTrabalhoEmMemoria
from notificacoes.aplicacao.distribuicao import DistribuirEvento, ResultadoDistribuicao
from notificacoes.aplicacao.tarefas import Tarefa
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.notificacao import Canal, StatusNotificacao
from plataforma.envelope import EnvelopeEvento

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
EMAIL_ADMIN = "admin@financeiro-eq5.local"
APROVADO = {
    "pagamento_id": "pag-1",
    "pedido_id": "ped-1",
    "cliente_id": "cliente-1",
    "valor_centavos": 4590,
    "metodo": "pix",
}


def _assinatura(
    armazenamento: ArmazenamentoEmMemoria,
    *,
    eventos: list[str],
    criado_por: str = "loja-1",
    somente_proprios: bool = False,
    ativa: bool = True,
) -> AssinaturaWebhook:
    assinatura = AssinaturaWebhook.nova(
        url="https://receptor.exemplo.com/hook",
        eventos=eventos,
        segredo="s" * 43,
        criado_por=criado_por,
        somente_proprios=somente_proprios,
        agora=AGORA,
        permitir_http=False,
        permitir_rede_interna=False,
    )
    if not ativa:
        assinatura.desativar()
    armazenamento.assinaturas[assinatura.id] = assinatura
    return assinatura


def _distribuir(armazenamento: ArmazenamentoEmMemoria) -> DistribuirEvento:
    return DistribuirEvento(
        lambda: UnidadeDeTrabalhoEmMemoria(armazenamento),
        email_admin=EMAIL_ADMIN,
        agora=lambda: AGORA,
    )


async def test_pagamento_aprovado_gera_email_e_webhooks_que_casam() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    casa = _assinatura(armazenamento, eventos=["pagamento.*"])
    _assinatura(armazenamento, eventos=["disputa.*"])
    _assinatura(armazenamento, eventos=["#"], ativa=False)
    envelope = EnvelopeEvento.novo("pagamento.aprovado", APROVADO)

    resultado = await _distribuir(armazenamento).executar(envelope)

    assert resultado == ResultadoDistribuicao(nova=True, emails=1, webhooks=1)
    assert sorted(tarefa.tipo for tarefa in armazenamento.tarefas) == [
        "tarefa.email",
        "tarefa.webhook",
    ]
    email = next(n for n in armazenamento.notificacoes.values() if n.canal is Canal.EMAIL)
    assert (email.destinatario_id, email.destino, email.status) == (
        "cliente-1",
        None,
        StatusNotificacao.PENDENTE,
    )
    webhook = next(n for n in armazenamento.notificacoes.values() if n.canal is Canal.WEBHOOK)
    assert webhook.assinatura_id == casa.id
    for tarefa in armazenamento.tarefas:
        assert tarefa.evento == envelope
        assert tarefa.notificacao_id in armazenamento.notificacoes
    assert envelope.mensagem_id in armazenamento.inbox


async def test_mensagem_duplicada_nao_gera_nada_de_novo() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    envelope = EnvelopeEvento.novo("pagamento.aprovado", APROVADO)
    distribuir = _distribuir(armazenamento)
    await distribuir.executar(envelope)
    assert await distribuir.executar(envelope) == ResultadoDistribuicao(nova=False)
    assert len(armazenamento.notificacoes) == 1
    assert len(armazenamento.tarefas) == 1


async def test_evento_sem_template_e_sem_assinatura_so_registra_na_inbox() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    envelope = EnvelopeEvento.novo("pedido.criado", {"pedido_id": "ped-9"})
    assert await _distribuir(armazenamento).executar(envelope) == ResultadoDistribuicao(nova=True)
    assert armazenamento.inbox == {envelope.mensagem_id}
    assert armazenamento.commits == 1


async def test_estorno_falhou_vai_para_o_admin() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    dados = {"disputa_id": "d1", "pedido_id": "ped-4", "motivo": "pagamento_nao_estornavel"}
    await _distribuir(armazenamento).executar(EnvelopeEvento.novo("disputa.estorno_falhou", dados))
    [email] = armazenamento.notificacoes.values()
    assert (email.destino, email.destinatario_id) == (EMAIL_ADMIN, None)


async def test_template_sem_destinatario_nao_gera_email() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    dados: dict[str, Any] = {k: v for k, v in APROVADO.items() if k != "cliente_id"}
    resultado = await _distribuir(armazenamento).executar(
        EnvelopeEvento.novo("pagamento.aprovado", dados)
    )
    assert resultado == ResultadoDistribuicao(nova=True)


async def test_webhook_de_cliente_nao_recebe_evento_de_outro_cliente() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    _assinatura(
        armazenamento, eventos=["pagamento.*"], criado_por="cliente-1", somente_proprios=True
    )
    distribuir = _distribuir(armazenamento)
    de_outro = await distribuir.executar(
        EnvelopeEvento.novo("pagamento.aprovado", {**APROVADO, "cliente_id": "cliente-2"})
    )
    proprio = await distribuir.executar(EnvelopeEvento.novo("pagamento.aprovado", APROVADO))
    assert (de_outro.webhooks, proprio.webhooks) == (0, 1)


async def test_falha_no_meio_nao_grava_inbox_nem_notificacoes() -> None:
    class FilaQueFalha:
        async def agendar(self, tarefa: Tarefa) -> None:
            raise RuntimeError("banco caiu")

    class UowQueFalha(UnidadeDeTrabalhoEmMemoria):
        async def __aenter__(self) -> "UowQueFalha":
            await super().__aenter__()
            self.tarefas = FilaQueFalha()  # type: ignore[assignment]
            return self

    armazenamento = ArmazenamentoEmMemoria()
    distribuir = DistribuirEvento(lambda: UowQueFalha(armazenamento), email_admin=EMAIL_ADMIN)
    with pytest.raises(RuntimeError):
        await distribuir.executar(EnvelopeEvento.novo("pagamento.aprovado", APROVADO))
    assert armazenamento.inbox == set()
    assert armazenamento.notificacoes == {}
