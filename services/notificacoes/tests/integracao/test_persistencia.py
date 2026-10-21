import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from notificacoes.adaptadores.cifrador import CifradorFernet
from notificacoes.adaptadores.db.modelos import Base
from notificacoes.adaptadores.db.uow import fabrica_sql
from notificacoes.aplicacao.portas import FabricaUow
from notificacoes.aplicacao.tarefas import TIPO_TAREFA_EMAIL, Tarefa
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.notificacao import Notificacao, StatusNotificacao
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.envelope import EnvelopeEvento
from plataforma.testes.migracoes import diferencas_modelo_banco

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
CIFRADOR = CifradorFernet.de_segredo("chave-de-teste-" + "x" * 32)


@pytest.fixture
async def fabrica_uow(banco_migrado: str) -> AsyncIterator[FabricaUow]:
    engine = criar_engine(banco_migrado)
    yield fabrica_sql(criar_fabrica_sessoes(engine), CIFRADOR)
    await engine.dispose()


def _assinatura(
    criado_por: str = "cliente-1", segredo: str = "segredo-em-claro"
) -> AssinaturaWebhook:
    return AssinaturaWebhook.nova(
        url="https://receptor.exemplo.com/hook",
        eventos=["pagamento.*"],
        segredo=segredo,
        criado_por=criado_por,
        somente_proprios=True,
        agora=AGORA,
        permitir_http=False,
        permitir_rede_interna=False,
    )


def _email(destinatario_id: str, agora: datetime = AGORA) -> Notificacao:
    return Notificacao.para_email(
        mensagem_id_origem=uuid.uuid4(),
        tipo_evento="pagamento.aprovado",
        destinatario_id=destinatario_id,
        destino=None,
        agora=agora,
    )


async def test_migracao_cria_tabelas_e_bate_com_os_modelos(banco_migrado: str) -> None:
    engine = create_async_engine(banco_migrado)
    async with engine.connect() as conexao:
        tabelas = await conexao.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    assert {
        "outbox",
        "inbox",
        "outbox_tarefas",
        "assinaturas_webhook",
        "notificacoes",
        "entregas_webhook",
    } <= set(tabelas)
    assert await diferencas_modelo_banco(banco_migrado, Base.metadata) == []


async def test_segredo_fica_cifrado_no_banco(fabrica_uow: FabricaUow, banco_migrado: str) -> None:
    assinatura = _assinatura()
    async with fabrica_uow() as uow:
        await uow.assinaturas.adicionar(assinatura)
        await uow.commit()

    engine = create_async_engine(banco_migrado)
    async with engine.connect() as conexao:
        linha = (
            await conexao.execute(text("SELECT segredo_cifrado, eventos FROM assinaturas_webhook"))
        ).one()
    await engine.dispose()
    assert linha.segredo_cifrado != "segredo-em-claro"
    assert linha.segredo_cifrado.startswith("gAAAA")
    assert linha.eventos == ["pagamento.*"]

    async with fabrica_uow() as uow:
        assert await uow.assinaturas.obter(assinatura.id) == assinatura


async def test_notificacoes_atualizacao_e_listagem(fabrica_uow: FabricaUow) -> None:
    assinatura = _assinatura(criado_por="loja-1")
    async with fabrica_uow() as uow:
        await uow.assinaturas.adicionar(assinatura)
        await uow.commit()
    primeira = _email("cliente-1")
    segunda = _email("cliente-1", AGORA + timedelta(seconds=1))
    webhook = Notificacao.para_webhook(
        mensagem_id_origem=uuid.uuid4(),
        tipo_evento="pagamento.aprovado",
        assinatura=assinatura,
        agora=AGORA,
    )
    async with fabrica_uow() as uow:
        for notificacao in (primeira, segunda, webhook):
            await uow.notificacoes.adicionar(notificacao)
        await uow.commit()

    async with fabrica_uow() as uow:
        lida = await uow.notificacoes.obter_para_atualizar(primeira.id)
        assert lida is not None
        lida.registrar_falha("Identidade fora", max_retentativas=5)
        await uow.notificacoes.atualizar(lida)
        await uow.commit()

    async with fabrica_uow() as uow:
        relida = await uow.notificacoes.obter_para_atualizar(primeira.id)
        assert relida is not None
        assert (relida.status, relida.tentativas, relida.ultimo_erro) == (
            StatusNotificacao.PENDENTE,
            1,
            "Identidade fora",
        )
        itens, total = await uow.notificacoes.listar(
            destinatario_id="cliente-1", deslocamento=0, limite=1
        )
        assert (total, [n.id for n in itens]) == (2, [segunda.id])
        _, todas = await uow.notificacoes.listar(destinatario_id=None, deslocamento=0, limite=20)
        assert todas == 3


async def test_sair_sem_commit_desfaz(fabrica_uow: FabricaUow) -> None:
    notificacao = _email("cliente-1")
    async with fabrica_uow() as uow:
        await uow.notificacoes.adicionar(notificacao)
    async with fabrica_uow() as uow:
        assert await uow.notificacoes.obter_para_atualizar(notificacao.id) is None


async def test_inbox_outbox_de_tarefas_e_eventos_externos(
    fabrica_uow: FabricaUow, banco_migrado: str
) -> None:
    envelope = EnvelopeEvento.novo("entrega.concluida", {"pedido_id": "ped-3"})
    tarefa = Tarefa(TIPO_TAREFA_EMAIL, uuid.uuid4(), envelope)
    async with fabrica_uow() as uow:
        assert await uow.inbox.registrar(envelope) is True
        await uow.tarefas.agendar(tarefa)
        assert await uow.eventos_externos.registrar_se_novo(envelope) is True
        assert await uow.eventos_externos.registrar_se_novo(envelope) is False
        await uow.commit()
    async with fabrica_uow() as uow:
        assert await uow.inbox.registrar(envelope) is False

    engine = create_async_engine(banco_migrado)
    async with engine.connect() as conexao:
        tarefas = (
            await conexao.execute(
                text("SELECT tipo, envelope->'dados'->>'notificacao_id' AS id FROM outbox_tarefas")
            )
        ).all()
        externos = (await conexao.execute(text("SELECT tipo FROM outbox"))).scalars().all()
    await engine.dispose()
    assert [(linha.tipo, linha.id) for linha in tarefas] == [
        ("tarefa.email", str(tarefa.notificacao_id))
    ]
    assert externos == ["entrega.concluida"]


async def test_assinaturas_e_entregas_paginadas(fabrica_uow: FabricaUow) -> None:
    do_cliente, de_outro, removida = (
        _assinatura("cliente-1"),
        _assinatura("cliente-2"),
        _assinatura("cliente-1"),
    )
    async with fabrica_uow() as uow:
        for assinatura in (do_cliente, de_outro, removida):
            await uow.assinaturas.adicionar(assinatura)
        await uow.commit()
    removida.desativar()
    async with fabrica_uow() as uow:
        await uow.assinaturas.atualizar(removida)
        for segundos in range(3):
            await uow.entregas.adicionar(
                EntregaWebhook.registrar(
                    assinatura_id=do_cliente.id,
                    mensagem_id=uuid.uuid4(),
                    tentativa=segundos + 1,
                    status_http=500,
                    duracao_ms=10,
                    erro=None,
                    agora=AGORA + timedelta(seconds=segundos),
                )
            )
        await uow.commit()

    async with fabrica_uow() as uow:
        _, do_dono = await uow.assinaturas.listar(criado_por="cliente-1", deslocamento=0, limite=20)
        _, todas = await uow.assinaturas.listar(criado_por=None, deslocamento=0, limite=20)
        ativas = await uow.assinaturas.listar_ativas()
        entregas, total = await uow.entregas.listar(do_cliente.id, deslocamento=0, limite=2)
    assert (do_dono, todas, len(ativas)) == (1, 2, 2)
    assert total == 3
    assert [entrega.tentativa for entrega in entregas] == [3, 2]
