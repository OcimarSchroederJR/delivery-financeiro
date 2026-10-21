"""Repositórios SQLAlchemy: convertem entre linhas do banco e entidades do domínio."""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from notificacoes.adaptadores.db.modelos import (
    AssinaturaWebhookLinha,
    EntregaWebhookLinha,
    MensagemOutbox,
    MensagemProcessada,
    NotificacaoLinha,
    TarefaSaida,
)
from notificacoes.aplicacao.portas import CifradorDeSegredos
from notificacoes.aplicacao.tarefas import Tarefa
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.notificacao import Canal, Notificacao, StatusNotificacao
from plataforma.envelope import EnvelopeEvento
from plataforma.inbox import registrar_na_inbox
from plataforma.outbox import gravar_no_outbox


async def _contar(sessao: AsyncSession, modelo: Any, filtros: list[ColumnElement[bool]]) -> int:
    return int(await sessao.scalar(select(func.count()).select_from(modelo).where(*filtros)) or 0)


def _notificacao(linha: NotificacaoLinha) -> Notificacao:
    return Notificacao(
        id=linha.id,
        mensagem_id_origem=linha.mensagem_id_origem,
        tipo_evento=linha.tipo_evento,
        canal=Canal(linha.canal),
        destino=linha.destino,
        destinatario_id=linha.destinatario_id,
        assinatura_id=linha.assinatura_id,
        status=StatusNotificacao(linha.status),
        tentativas=linha.tentativas,
        ultimo_erro=linha.ultimo_erro,
        criado_em=linha.criado_em,
        enviada_em=linha.enviada_em,
    )


class RepositorioNotificacoesSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def adicionar(self, notificacao: Notificacao) -> None:
        self._sessao.add(
            NotificacaoLinha(
                id=notificacao.id,
                mensagem_id_origem=notificacao.mensagem_id_origem,
                tipo_evento=notificacao.tipo_evento,
                canal=notificacao.canal.value,
                destino=notificacao.destino,
                destinatario_id=notificacao.destinatario_id,
                assinatura_id=notificacao.assinatura_id,
                status=notificacao.status.value,
                tentativas=notificacao.tentativas,
                ultimo_erro=notificacao.ultimo_erro,
                criado_em=notificacao.criado_em,
                enviada_em=notificacao.enviada_em,
            )
        )

    async def obter_para_atualizar(self, notificacao_id: uuid.UUID) -> Notificacao | None:
        linha = await self._sessao.scalar(
            select(NotificacaoLinha).where(NotificacaoLinha.id == notificacao_id).with_for_update()
        )
        return None if linha is None else _notificacao(linha)

    async def atualizar(self, notificacao: Notificacao) -> None:
        await self._sessao.execute(
            update(NotificacaoLinha)
            .where(NotificacaoLinha.id == notificacao.id)
            .values(
                destino=notificacao.destino,
                status=notificacao.status.value,
                tentativas=notificacao.tentativas,
                ultimo_erro=notificacao.ultimo_erro,
                enviada_em=notificacao.enviada_em,
            )
        )

    async def listar(
        self, *, destinatario_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Notificacao], int]:
        filtros: list[ColumnElement[bool]] = []
        if destinatario_id is not None:
            filtros.append(NotificacaoLinha.destinatario_id == destinatario_id)
        linhas = await self._sessao.scalars(
            select(NotificacaoLinha)
            .where(*filtros)
            .order_by(NotificacaoLinha.criado_em.desc(), NotificacaoLinha.id)
            .offset(deslocamento)
            .limit(limite)
        )
        total = await _contar(self._sessao, NotificacaoLinha, filtros)
        return [_notificacao(linha) for linha in linhas], total


class RepositorioAssinaturasSql:
    def __init__(self, sessao: AsyncSession, cifrador: CifradorDeSegredos) -> None:
        self._sessao = sessao
        self._cifrador = cifrador

    def _assinatura(self, linha: AssinaturaWebhookLinha) -> AssinaturaWebhook:
        return AssinaturaWebhook(
            id=linha.id,
            url=linha.url,
            eventos=tuple(linha.eventos),
            segredo=self._cifrador.decifrar(linha.segredo_cifrado),
            ativa=linha.ativa,
            criado_por=linha.criado_por,
            somente_proprios=linha.somente_proprios,
            criado_em=linha.criado_em,
        )

    async def adicionar(self, assinatura: AssinaturaWebhook) -> None:
        self._sessao.add(
            AssinaturaWebhookLinha(
                id=assinatura.id,
                url=assinatura.url,
                eventos=list(assinatura.eventos),
                segredo_cifrado=self._cifrador.cifrar(assinatura.segredo),
                ativa=assinatura.ativa,
                criado_por=assinatura.criado_por,
                somente_proprios=assinatura.somente_proprios,
                criado_em=assinatura.criado_em,
            )
        )

    async def obter(self, assinatura_id: uuid.UUID) -> AssinaturaWebhook | None:
        linha = await self._sessao.get(AssinaturaWebhookLinha, assinatura_id)
        return None if linha is None else self._assinatura(linha)

    async def atualizar(self, assinatura: AssinaturaWebhook) -> None:
        await self._sessao.execute(
            update(AssinaturaWebhookLinha)
            .where(AssinaturaWebhookLinha.id == assinatura.id)
            .values(ativa=assinatura.ativa)
        )

    async def listar(
        self, *, criado_por: str | None, deslocamento: int, limite: int
    ) -> tuple[list[AssinaturaWebhook], int]:
        filtros: list[ColumnElement[bool]] = [AssinaturaWebhookLinha.ativa.is_(True)]
        if criado_por is not None:
            filtros.append(AssinaturaWebhookLinha.criado_por == criado_por)
        linhas = await self._sessao.scalars(
            select(AssinaturaWebhookLinha)
            .where(*filtros)
            .order_by(AssinaturaWebhookLinha.criado_em.desc(), AssinaturaWebhookLinha.id)
            .offset(deslocamento)
            .limit(limite)
        )
        total = await _contar(self._sessao, AssinaturaWebhookLinha, filtros)
        return [self._assinatura(linha) for linha in linhas], total

    async def listar_ativas(self) -> list[AssinaturaWebhook]:
        linhas = await self._sessao.scalars(
            select(AssinaturaWebhookLinha).where(AssinaturaWebhookLinha.ativa.is_(True))
        )
        return [self._assinatura(linha) for linha in linhas]


class RepositorioEntregasSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def adicionar(self, entrega: EntregaWebhook) -> None:
        self._sessao.add(
            EntregaWebhookLinha(
                id=entrega.id,
                assinatura_id=entrega.assinatura_id,
                mensagem_id=entrega.mensagem_id,
                tentativa=entrega.tentativa,
                status_http=entrega.status_http,
                duracao_ms=entrega.duracao_ms,
                erro=entrega.erro,
                criado_em=entrega.criado_em,
            )
        )

    async def listar(
        self, assinatura_id: uuid.UUID, *, deslocamento: int, limite: int
    ) -> tuple[list[EntregaWebhook], int]:
        filtros: list[ColumnElement[bool]] = [EntregaWebhookLinha.assinatura_id == assinatura_id]
        linhas = await self._sessao.scalars(
            select(EntregaWebhookLinha)
            .where(*filtros)
            .order_by(EntregaWebhookLinha.criado_em.desc(), EntregaWebhookLinha.tentativa.desc())
            .offset(deslocamento)
            .limit(limite)
        )
        total = await _contar(self._sessao, EntregaWebhookLinha, filtros)
        return [
            EntregaWebhook(
                id=linha.id,
                assinatura_id=linha.assinatura_id,
                mensagem_id=linha.mensagem_id,
                tentativa=linha.tentativa,
                status_http=linha.status_http,
                duracao_ms=linha.duracao_ms,
                erro=linha.erro,
                criado_em=linha.criado_em,
            )
            for linha in linhas
        ], total


class InboxSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def registrar(self, envelope: EnvelopeEvento) -> bool:
        return await registrar_na_inbox(self._sessao, MensagemProcessada, envelope)


class FilaDeTarefasSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def agendar(self, tarefa: Tarefa) -> None:
        gravar_no_outbox(self._sessao, TarefaSaida, tarefa.para_envelope())


class CaixaDeEventosExternosSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def registrar_se_novo(self, envelope: EnvelopeEvento) -> bool:
        comando = (
            insert(MensagemOutbox)
            .values(
                mensagem_id=envelope.mensagem_id,
                tipo=envelope.tipo,
                envelope=envelope.para_json(),
                tentativas=0,
            )
            .on_conflict_do_nothing(index_elements=["mensagem_id"])
            .returning(MensagemOutbox.id)
        )
        return (await self._sessao.execute(comando)).scalar_one_or_none() is not None
