"""Casos de uso das assinaturas de webhook (spec §4.2, endpoints /v1/webhooks)."""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime

from notificacoes.aplicacao.portas import UnidadeDeTrabalho
from notificacoes.aplicacao.solicitante import PoliticaDeUrl, Solicitante
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.assinatura_hmac import gerar_segredo as gerar_segredo_padrao
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.erros import AssinaturaNaoEncontrada
from plataforma.erros import ErroAcessoNegado
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


async def criar_assinatura(
    uow: UnidadeDeTrabalho,
    solicitante: Solicitante,
    *,
    url: str,
    eventos: Sequence[str],
    politica: PoliticaDeUrl,
    gerar_segredo: Callable[[], str] = gerar_segredo_padrao,
    agora: Callable[[], datetime] = agora_utc,
) -> AssinaturaWebhook:
    assinatura = AssinaturaWebhook.nova(
        url=url,
        eventos=eventos,
        segredo=gerar_segredo(),
        criado_por=solicitante.id,
        somente_proprios=not solicitante.admin,
        agora=agora(),
        permitir_http=politica.permitir_http,
        permitir_rede_interna=politica.permitir_rede_interna,
    )
    async with uow:
        await uow.assinaturas.adicionar(assinatura)
        await uow.commit()
    _log.info(
        "assinatura_criada", assinatura_id=str(assinatura.id), eventos=list(assinatura.eventos)
    )
    return assinatura


async def listar_assinaturas(
    uow: UnidadeDeTrabalho, solicitante: Solicitante, *, deslocamento: int, limite: int
) -> tuple[list[AssinaturaWebhook], int]:
    async with uow:
        return await uow.assinaturas.listar(
            criado_por=None if solicitante.admin else solicitante.id,
            deslocamento=deslocamento,
            limite=limite,
        )


async def _obter_gerivel(
    uow: UnidadeDeTrabalho, solicitante: Solicitante, assinatura_id: uuid.UUID
) -> AssinaturaWebhook:
    assinatura = await uow.assinaturas.obter(assinatura_id)
    if assinatura is None or not assinatura.ativa:
        raise AssinaturaNaoEncontrada()
    if not assinatura.pode_ser_gerida_por(solicitante.id, admin=solicitante.admin):
        raise ErroAcessoNegado("A assinatura pertence a outro usuário.")
    return assinatura


async def remover_assinatura(
    uow: UnidadeDeTrabalho, solicitante: Solicitante, assinatura_id: uuid.UUID
) -> None:
    async with uow:
        assinatura = await _obter_gerivel(uow, solicitante, assinatura_id)
        assinatura.desativar()
        await uow.assinaturas.atualizar(assinatura)
        await uow.commit()
    _log.info("assinatura_removida", assinatura_id=str(assinatura_id))


async def listar_entregas(
    uow: UnidadeDeTrabalho,
    solicitante: Solicitante,
    assinatura_id: uuid.UUID,
    *,
    deslocamento: int,
    limite: int,
) -> tuple[list[EntregaWebhook], int]:
    async with uow:
        await _obter_gerivel(uow, solicitante, assinatura_id)
        return await uow.entregas.listar(assinatura_id, deslocamento=deslocamento, limite=limite)
