import uuid
from datetime import UTC, datetime

import pytest

from notificacoes.adaptadores.memoria import (
    ArmazenamentoEmMemoria,
    EmailEnviado,
    EntregadorDeWebhookEmMemoria,
    EnviadorDeEmailEmMemoria,
    PerfisEmMemoria,
    UnidadeDeTrabalhoEmMemoria,
)
from notificacoes.aplicacao.portas import (
    FalhaNoEnvioDeEmail,
    Perfil,
    PerfilNaoEncontrado,
    ResultadoEntrega,
)
from notificacoes.dominio.notificacao import Notificacao
from plataforma.envelope import EnvelopeEvento
from plataforma.erros import ErroDependenciaIndisponivel

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)


def _notificacao(destinatario_id: str) -> Notificacao:
    return Notificacao.para_email(
        mensagem_id_origem=uuid.uuid4(),
        tipo_evento="pagamento.aprovado",
        destinatario_id=destinatario_id,
        destino=None,
        agora=AGORA,
    )


async def test_commit_publica_e_saida_sem_commit_descarta() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    notificacao = _notificacao("cliente-1")
    async with UnidadeDeTrabalhoEmMemoria(armazenamento) as uow:
        await uow.notificacoes.adicionar(notificacao)
    assert armazenamento.notificacoes == {}
    async with UnidadeDeTrabalhoEmMemoria(armazenamento) as uow:
        await uow.notificacoes.adicionar(notificacao)
        await uow.commit()
    assert notificacao.id in armazenamento.notificacoes
    assert armazenamento.commits == 1


async def test_inbox_e_eventos_externos_detectam_duplicata() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    envelope = EnvelopeEvento.novo("entrega.concluida", {})
    async with UnidadeDeTrabalhoEmMemoria(armazenamento) as uow:
        assert await uow.inbox.registrar(envelope) is True
        assert await uow.inbox.registrar(envelope) is False
        assert await uow.eventos_externos.registrar_se_novo(envelope) is True
        assert await uow.eventos_externos.registrar_se_novo(envelope) is False
        await uow.commit()
    assert envelope.mensagem_id in armazenamento.inbox


async def test_listagem_paginada_e_filtrada() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    async with UnidadeDeTrabalhoEmMemoria(armazenamento) as uow:
        for destinatario in ("cliente-1", "cliente-1", "cliente-2"):
            await uow.notificacoes.adicionar(_notificacao(destinatario))
        itens, total = await uow.notificacoes.listar(
            destinatario_id="cliente-1", deslocamento=0, limite=1
        )
    assert (len(itens), total) == (1, 2)


async def test_dubles_das_portas_externas() -> None:
    perfil = Perfil(id="c1", email="c1@exemplo.com", nome="Ana")
    perfis = PerfisEmMemoria({"c1": perfil}, indisponivel=1)
    with pytest.raises(ErroDependenciaIndisponivel):
        await perfis.obter("c1")
    assert await perfis.obter("c1") == perfil
    with pytest.raises(PerfilNaoEncontrado):
        await perfis.obter("c2")
    assert perfis.consultas == ["c1", "c1", "c2"]

    enviador = EnviadorDeEmailEmMemoria(falhas=1)
    with pytest.raises(FalhaNoEnvioDeEmail):
        await enviador.enviar(para="a@b.c", assunto="x", corpo="y")
    await enviador.enviar(para="a@b.c", assunto="x", corpo="y")
    assert enviador.enviados == [EmailEnviado("a@b.c", "x", "y")]

    entregador = EntregadorDeWebhookEmMemoria(ResultadoEntrega(500, 3), ResultadoEntrega(204, 2))
    assert (await entregador.entregar("https://x", b"{}", {})).status_http == 500
    assert (await entregador.entregar("https://x", b"{}", {})).sucesso
    assert (await entregador.entregar("https://x", b"{}", {})).sucesso
    assert len(entregador.chamadas) == 3
    assert ResultadoEntrega(None, 5000, "Tempo esgotado.").descricao_falha() == "Tempo esgotado."
    assert ResultadoEntrega(503, 1).descricao_falha() == "HTTP 503"
