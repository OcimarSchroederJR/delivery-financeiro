"""Consumidor de ``notificacoes.eventos``: inbox + fan-out (spec §4.2, itens 1 a 5).

Numa única transação: registra a mensagem na inbox; cria a notificação de
e-mail (se há template e destinatário); cria uma notificação de webhook por
assinatura ativa que casa com o ``tipo``; agenda as tarefas no outbox de
tarefas. Não chama nenhuma dependência externa: o envio é feito pelos
consumidores de ``notificacoes.emails`` e ``notificacoes.webhooks``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from notificacoes.aplicacao.portas import FabricaUow, UnidadeDeTrabalho
from notificacoes.aplicacao.tarefas import TIPO_TAREFA_EMAIL, TIPO_TAREFA_WEBHOOK, Tarefa
from notificacoes.dominio.notificacao import Notificacao
from notificacoes.dominio.templates import modelo_para
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoDistribuicao:
    nova: bool
    emails: int = 0
    webhooks: int = 0


class DistribuirEvento:
    def __init__(
        self,
        fabrica_uow: FabricaUow,
        *,
        email_admin: str,
        agora: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._fabrica_uow = fabrica_uow
        self._email_admin = email_admin
        self._agora = agora

    async def executar(self, envelope: EnvelopeEvento) -> ResultadoDistribuicao:
        async with self._fabrica_uow() as uow:
            if not await uow.inbox.registrar(envelope):
                return ResultadoDistribuicao(nova=False)
            agora = self._agora()
            emails = await self._agendar_email(uow, envelope, agora)
            webhooks = await self._agendar_webhooks(uow, envelope, agora)
            await uow.commit()
        _log.info(
            "evento_distribuido",
            tipo=envelope.tipo,
            mensagem_id=str(envelope.mensagem_id),
            emails=emails,
            webhooks=webhooks,
        )
        return ResultadoDistribuicao(nova=True, emails=emails, webhooks=webhooks)

    async def _agendar_email(
        self, uow: UnidadeDeTrabalho, envelope: EnvelopeEvento, agora: datetime
    ) -> int:
        modelo = modelo_para(envelope.tipo)
        if modelo is None:
            return 0
        destinatario_id: str | None = None
        destino: str | None = None
        if modelo.para_admin:
            destino = self._email_admin
        else:
            destinatario_id = modelo.destinatario_id(envelope.dados)
            if destinatario_id is None:
                _log.warning("email_sem_destinatario", tipo=envelope.tipo)
                return 0
        notificacao = Notificacao.para_email(
            mensagem_id_origem=envelope.mensagem_id,
            tipo_evento=envelope.tipo,
            destinatario_id=destinatario_id,
            destino=destino,
            agora=agora,
        )
        await uow.notificacoes.adicionar(notificacao)
        await uow.tarefas.agendar(Tarefa(TIPO_TAREFA_EMAIL, notificacao.id, envelope))
        return 1

    async def _agendar_webhooks(
        self, uow: UnidadeDeTrabalho, envelope: EnvelopeEvento, agora: datetime
    ) -> int:
        quantidade = 0
        for assinatura in await uow.assinaturas.listar_ativas():
            if not assinatura.recebe(envelope.tipo, envelope.dados):
                continue
            notificacao = Notificacao.para_webhook(
                mensagem_id_origem=envelope.mensagem_id,
                tipo_evento=envelope.tipo,
                assinatura=assinatura,
                agora=agora,
            )
            await uow.notificacoes.adicionar(notificacao)
            await uow.tarefas.agendar(Tarefa(TIPO_TAREFA_WEBHOOK, notificacao.id, envelope))
            quantidade += 1
        return quantidade
