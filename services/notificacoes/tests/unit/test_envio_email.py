import uuid
from datetime import UTC, datetime
from typing import Any

from notificacoes.adaptadores.memoria import (
    ArmazenamentoEmMemoria,
    EnviadorDeEmailEmMemoria,
    PerfisEmMemoria,
    UnidadeDeTrabalhoEmMemoria,
)
from notificacoes.aplicacao.envio_email import EnviarEmail
from notificacoes.aplicacao.portas import Perfil
from notificacoes.aplicacao.tarefas import TIPO_TAREFA_EMAIL, Desfecho, Tarefa, TipoDesfecho
from notificacoes.dominio.notificacao import Notificacao, StatusNotificacao
from plataforma.envelope import EnvelopeEvento

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
PERFIL = Perfil(id="cliente-1", email="cliente-1@exemplo.com", nome="Ana")
APROVADO = {
    "pagamento_id": "pag-1",
    "pedido_id": "ped-1",
    "cliente_id": "cliente-1",
    "valor_centavos": 4590,
    "metodo": "pix",
}


def _cenario(
    tipo: str = "pagamento.aprovado",
    dados: dict[str, Any] | None = None,
    *,
    destinatario_id: str | None = "cliente-1",
    destino: str | None = None,
) -> tuple[ArmazenamentoEmMemoria, Tarefa]:
    evento = EnvelopeEvento.novo(tipo, APROVADO if dados is None else dados)
    notificacao = Notificacao.para_email(
        mensagem_id_origem=evento.mensagem_id,
        tipo_evento=tipo,
        destinatario_id=destinatario_id,
        destino=destino,
        agora=AGORA,
    )
    armazenamento = ArmazenamentoEmMemoria(notificacoes={notificacao.id: notificacao})
    return armazenamento, Tarefa(TIPO_TAREFA_EMAIL, notificacao.id, evento)


def _caso(
    armazenamento: ArmazenamentoEmMemoria,
    perfis: PerfisEmMemoria,
    enviador: EnviadorDeEmailEmMemoria,
) -> EnviarEmail:
    return EnviarEmail(
        lambda: UnidadeDeTrabalhoEmMemoria(armazenamento),
        perfis,
        enviador,
        max_retentativas=5,
        agora=lambda: AGORA,
    )


async def test_envia_email_ao_cliente_com_template() -> None:
    armazenamento, tarefa = _cenario()
    enviador = EnviadorDeEmailEmMemoria()
    desfecho = await _caso(
        armazenamento, PerfisEmMemoria({"cliente-1": PERFIL}), enviador
    ).executar(tarefa)
    assert desfecho == Desfecho.concluida()
    [email] = enviador.enviados
    assert email.para == "cliente-1@exemplo.com"
    assert email.assunto == "Pagamento aprovado - pedido ped-1"
    assert "Olá, Ana!" in email.corpo
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert (
        notificacao.status,
        notificacao.destino,
        notificacao.tentativas,
        notificacao.enviada_em,
    ) == (StatusNotificacao.ENVIADA, "cliente-1@exemplo.com", 1, AGORA)


async def test_perfis_fora_pede_retentativa_e_nao_perde_a_mensagem() -> None:
    armazenamento, tarefa = _cenario()
    enviador = EnviadorDeEmailEmMemoria()
    caso = _caso(armazenamento, PerfisEmMemoria({"cliente-1": PERFIL}, indisponivel=1), enviador)
    primeiro = await caso.executar(tarefa)
    assert (primeiro.tipo, primeiro.retentativa) == (TipoDesfecho.REPETIR, 1)
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert notificacao.pendente
    assert notificacao.ultimo_erro is not None
    assert notificacao.ultimo_erro.startswith("ErroDependenciaIndisponivel")
    assert await caso.executar(tarefa) == Desfecho.concluida()
    assert len(enviador.enviados) == 1


async def test_smtp_fora_tambem_repete() -> None:
    armazenamento, tarefa = _cenario()
    caso = _caso(
        armazenamento, PerfisEmMemoria({"cliente-1": PERFIL}), EnviadorDeEmailEmMemoria(falhas=1)
    )
    desfecho = await caso.executar(tarefa)
    assert (desfecho.tipo, desfecho.retentativa) == (TipoDesfecho.REPETIR, 1)


async def test_esgota_retentativas_e_desiste() -> None:
    armazenamento, tarefa = _cenario()
    caso = _caso(
        armazenamento,
        PerfisEmMemoria({"cliente-1": PERFIL}, indisponivel=10),
        EnviadorDeEmailEmMemoria(),
    )
    tipos = [(await caso.executar(tarefa)).tipo for _ in range(6)]
    assert tipos == [TipoDesfecho.REPETIR] * 5 + [TipoDesfecho.DESISTIR]
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert (notificacao.status, notificacao.tentativas) == (StatusNotificacao.FALHOU, 6)
    assert (await caso.executar(tarefa)).tipo is TipoDesfecho.IGNORADA


async def test_perfil_inexistente_e_falha_definitiva() -> None:
    armazenamento, tarefa = _cenario()
    enviador = EnviadorDeEmailEmMemoria()
    desfecho = await _caso(armazenamento, PerfisEmMemoria(), enviador).executar(tarefa)
    assert desfecho.tipo is TipoDesfecho.DESISTIR
    notificacao = armazenamento.notificacoes[tarefa.notificacao_id]
    assert (notificacao.status, notificacao.tentativas) == (StatusNotificacao.FALHOU, 1)
    assert enviador.enviados == []


async def test_evento_sem_campo_do_template_e_falha_definitiva() -> None:
    dados = {k: v for k, v in APROVADO.items() if k != "valor_centavos"}
    armazenamento, tarefa = _cenario(dados=dados)
    caso = _caso(armazenamento, PerfisEmMemoria({"cliente-1": PERFIL}), EnviadorDeEmailEmMemoria())
    assert (await caso.executar(tarefa)).tipo is TipoDesfecho.DESISTIR


async def test_tipo_sem_template_e_falha_definitiva() -> None:
    armazenamento, tarefa = _cenario("pedido.criado", {"cliente_id": "cliente-1"})
    caso = _caso(armazenamento, PerfisEmMemoria({"cliente-1": PERFIL}), EnviadorDeEmailEmMemoria())
    assert (await caso.executar(tarefa)).tipo is TipoDesfecho.DESISTIR


async def test_email_do_admin_nao_consulta_perfis() -> None:
    dados = {"disputa_id": "d1", "pedido_id": "ped-4", "motivo": "pagamento_nao_estornavel"}
    armazenamento, tarefa = _cenario(
        "disputa.estorno_falhou",
        dados,
        destinatario_id=None,
        destino="admin@financeiro-eq5.local",
    )
    perfis, enviador = PerfisEmMemoria(), EnviadorDeEmailEmMemoria()
    assert await _caso(armazenamento, perfis, enviador).executar(tarefa) == Desfecho.concluida()
    assert perfis.consultas == []
    [email] = enviador.enviados
    assert email.para == "admin@financeiro-eq5.local"
    assert "equipe de operações" in email.corpo


async def test_notificacao_ja_enviada_ou_inexistente_e_ignorada() -> None:
    armazenamento, tarefa = _cenario()
    enviador = EnviadorDeEmailEmMemoria()
    caso = _caso(armazenamento, PerfisEmMemoria({"cliente-1": PERFIL}), enviador)
    await caso.executar(tarefa)
    assert (await caso.executar(tarefa)).tipo is TipoDesfecho.IGNORADA
    inexistente = Tarefa(TIPO_TAREFA_EMAIL, uuid.uuid4(), tarefa.evento)
    assert (await caso.executar(inexistente)).tipo is TipoDesfecho.IGNORADA
    assert len(enviador.enviados) == 1
