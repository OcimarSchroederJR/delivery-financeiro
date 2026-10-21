import json
from datetime import UTC, datetime

from notificacoes.adaptadores.memoria import (
    ArmazenamentoEmMemoria,
    EntregadorDeWebhookEmMemoria,
    UnidadeDeTrabalhoEmMemoria,
)
from notificacoes.aplicacao.entrega_webhook import EntregarWebhook, serializar_evento
from notificacoes.aplicacao.portas import ResultadoEntrega
from notificacoes.aplicacao.tarefas import TIPO_TAREFA_WEBHOOK, Desfecho, Tarefa, TipoDesfecho
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.assinatura_hmac import assinatura_valida
from notificacoes.dominio.notificacao import Notificacao, StatusNotificacao
from plataforma.envelope import EnvelopeEvento

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
SEGREDO = "segredo-do-webhook"


def _cenario(*, ativa: bool = True) -> tuple[ArmazenamentoEmMemoria, AssinaturaWebhook, Tarefa]:
    assinatura = AssinaturaWebhook.nova(
        url="https://loja.exemplo.com/hook",
        eventos=["pagamento.*"],
        segredo=SEGREDO,
        criado_por="loja-1",
        somente_proprios=False,
        agora=AGORA,
        permitir_http=False,
        permitir_rede_interna=False,
    )
    if not ativa:
        assinatura.desativar()
    evento = EnvelopeEvento.novo(
        "pagamento.aprovado", {"pagamento_id": "pag-1", "cliente_id": "cliente-1"}
    )
    notificacao = Notificacao.para_webhook(
        mensagem_id_origem=evento.mensagem_id,
        tipo_evento=evento.tipo,
        assinatura=assinatura,
        agora=AGORA,
    )
    armazenamento = ArmazenamentoEmMemoria(
        notificacoes={notificacao.id: notificacao}, assinaturas={assinatura.id: assinatura}
    )
    return armazenamento, assinatura, Tarefa(TIPO_TAREFA_WEBHOOK, notificacao.id, evento)


def _caso(
    armazenamento: ArmazenamentoEmMemoria, entregador: EntregadorDeWebhookEmMemoria
) -> EntregarWebhook:
    return EntregarWebhook(
        lambda: UnidadeDeTrabalhoEmMemoria(armazenamento),
        entregador,
        max_retentativas=5,
        agora=lambda: AGORA,
    )


async def test_entrega_assinada_com_hmac_e_registrada() -> None:
    armazenamento, assinatura, tarefa = _cenario()
    entregador = EntregadorDeWebhookEmMemoria(ResultadoEntrega(status_http=200, duracao_ms=15))
    assert await _caso(armazenamento, entregador).executar(tarefa) == Desfecho.concluida()

    [chamada] = entregador.chamadas
    assert chamada.url == assinatura.url
    assert chamada.corpo == serializar_evento(tarefa.evento)
    assert json.loads(chamada.corpo) == tarefa.evento.para_json()
    timestamp = int(chamada.cabecalhos["X-Assinatura-Timestamp"])
    assert timestamp == int(AGORA.timestamp())
    assert assinatura_valida(
        SEGREDO, timestamp, chamada.corpo, chamada.cabecalhos["X-Assinatura"], agora=timestamp
    )
    assert chamada.cabecalhos["X-Evento-Id"] == str(tarefa.evento.mensagem_id)
    assert chamada.cabecalhos["X-Evento-Tipo"] == "pagamento.aprovado"

    [entrega] = armazenamento.entregas
    assert (entrega.tentativa, entrega.status_http, entrega.duracao_ms, entrega.erro) == (
        1,
        200,
        15,
        None,
    )
    assert armazenamento.notificacoes[tarefa.notificacao_id].status is StatusNotificacao.ENVIADA


async def test_falha_http_pede_retentativa_e_registra_cada_tentativa() -> None:
    armazenamento, _, tarefa = _cenario()
    entregador = EntregadorDeWebhookEmMemoria(
        ResultadoEntrega(500, 7),
        ResultadoEntrega(None, 5000, "Tempo esgotado (5 s)."),
        ResultadoEntrega(204, 3),
    )
    caso = _caso(armazenamento, entregador)
    primeiro, segundo, terceiro = [await caso.executar(tarefa) for _ in range(3)]
    assert (primeiro.tipo, primeiro.retentativa) == (TipoDesfecho.REPETIR, 1)
    assert (segundo.tipo, segundo.retentativa) == (TipoDesfecho.REPETIR, 2)
    assert terceiro == Desfecho.concluida()
    assert [e.tentativa for e in armazenamento.entregas] == [1, 2, 3]
    assert [e.status_http for e in armazenamento.entregas] == [500, None, 204]
    assert armazenamento.entregas[1].erro == "Tempo esgotado (5 s)."
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert (notificacao.status, notificacao.ultimo_erro) == (
        StatusNotificacao.ENVIADA,
        "Tempo esgotado (5 s).",
    )


async def test_webhook_falhando_ate_desistir() -> None:
    armazenamento, _, tarefa = _cenario()
    caso = _caso(armazenamento, EntregadorDeWebhookEmMemoria(ResultadoEntrega(503, 1)))
    tipos = [(await caso.executar(tarefa)).tipo for _ in range(6)]
    assert tipos == [TipoDesfecho.REPETIR] * 5 + [TipoDesfecho.DESISTIR]
    assert len(armazenamento.entregas) == 6
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert (notificacao.status, notificacao.ultimo_erro) == (StatusNotificacao.FALHOU, "HTTP 503")


async def test_assinatura_removida_cancela_sem_entregar() -> None:
    armazenamento, _, tarefa = _cenario(ativa=False)
    entregador = EntregadorDeWebhookEmMemoria()
    assert (await _caso(armazenamento, entregador).executar(tarefa)).tipo is TipoDesfecho.IGNORADA
    assert entregador.chamadas == []
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert (notificacao.status, notificacao.tentativas) == (StatusNotificacao.FALHOU, 0)


async def test_notificacao_finalizada_e_ignorada() -> None:
    armazenamento, _, tarefa = _cenario()
    entregador = EntregadorDeWebhookEmMemoria()
    caso = _caso(armazenamento, entregador)
    await caso.executar(tarefa)
    assert (await caso.executar(tarefa)).tipo is TipoDesfecho.IGNORADA
    assert len(entregador.chamadas) == 1
