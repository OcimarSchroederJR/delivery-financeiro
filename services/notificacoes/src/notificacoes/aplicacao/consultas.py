"""Consulta de notificações (spec §4.2, ``GET /v1/notificacoes?destinatario_id=``)."""

import uuid

from notificacoes.aplicacao.portas import UnidadeDeTrabalho
from notificacoes.aplicacao.solicitante import Solicitante
from notificacoes.dominio.erros import NotificacaoNaoEncontrada
from notificacoes.dominio.notificacao import Notificacao
from plataforma.erros import ErroAcessoNegado


async def listar_notificacoes(
    uow: UnidadeDeTrabalho,
    solicitante: Solicitante,
    *,
    destinatario_id: str | None,
    deslocamento: int,
    limite: int,
) -> tuple[list[Notificacao], int]:
    """Não-admin só vê as próprias; admin filtra por qualquer destinatário (ou nenhum)."""
    if not solicitante.admin:
        if destinatario_id is not None and destinatario_id != solicitante.id:
            raise ErroAcessoNegado("Só é possível consultar as próprias notificações.")
        destinatario_id = solicitante.id
    async with uow:
        return await uow.notificacoes.listar(
            destinatario_id=destinatario_id, deslocamento=deslocamento, limite=limite
        )


async def obter_notificacao(
    uow: UnidadeDeTrabalho, solicitante: Solicitante, notificacao_id: uuid.UUID
) -> Notificacao:
    """Não-admin só vê as próprias; a de outro destinatário responde 403 (como a lista)."""
    async with uow:
        notificacao = await uow.notificacoes.obter(notificacao_id)
    if notificacao is None:
        raise NotificacaoNaoEncontrada()
    if not solicitante.admin and notificacao.destinatario_id != solicitante.id:
        raise ErroAcessoNegado("Só é possível consultar as próprias notificações.")
    return notificacao
