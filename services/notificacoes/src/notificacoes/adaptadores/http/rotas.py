"""Rotas HTTP do serviço de Notificações (spec §4.2)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from notificacoes.adaptadores.http.dependencias import (
    ConfigAtual,
    ProdutorDeEventos,
    Uow,
    solicitante_de,
)
from notificacoes.adaptadores.http.schemas import (
    AssinaturaCriada,
    AssinaturaEntrada,
    AssinaturaSaida,
    EntregaSaida,
    EventoAceito,
    NotificacaoSaida,
)
from notificacoes.aplicacao.assinaturas import (
    criar_assinatura,
    listar_assinaturas,
    listar_entregas,
    remover_assinatura,
)
from notificacoes.aplicacao.consultas import listar_notificacoes
from notificacoes.aplicacao.eventos_externos import interpretar_corpo, receber_evento_externo
from plataforma.api.auth import UsuarioAtual
from plataforma.api.erros import respostas_erro
from plataforma.api.paginacao import Pagina, Paginacao
from plataforma.envelope import EnvelopeEvento

router = APIRouter(prefix="/v1")

# O corpo é lido cru para que envelope inválido responda 400 (e não o 422 padrão).
_CORPO_ENVELOPE = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": EnvelopeEvento.model_json_schema()}},
    }
}


@router.post(
    "/eventos",
    status_code=202,
    response_model=EventoAceito,
    responses=respostas_erro(400, 401, 403),
    summary="Recebe um evento de outra equipe (ex.: pedido.*, entrega.*)",
    description="Valida o envelope, deduplica por mensagem_id e o publica em "
    "financeiro.eventos (routing key = tipo). Papéis: loja, entregador, admin.",
    openapi_extra=_CORPO_ENVELOPE,
    tags=["eventos"],
)
async def receber_evento(
    requisicao: Request, _produtor: ProdutorDeEventos, uow: Uow
) -> EventoAceito:
    recebido = await receber_evento_externo(uow, interpretar_corpo(await requisicao.body()))
    return EventoAceito(
        mensagem_id=recebido.mensagem_id, status="aceito" if recebido.novo else "duplicado"
    )


@router.post(
    "/webhooks",
    status_code=201,
    response_model=AssinaturaCriada,
    responses=respostas_erro(401, 403, 422),
    summary="Cria uma assinatura de webhook (o segredo só aparece nesta resposta)",
    tags=["webhooks"],
)
async def criar_webhook(
    entrada: AssinaturaEntrada, usuario: UsuarioAtual, uow: Uow, config: ConfigAtual
) -> AssinaturaCriada:
    assinatura = await criar_assinatura(
        uow,
        solicitante_de(usuario),
        url=entrada.url,
        eventos=entrada.eventos,
        politica=config.politica_de_url(),
    )
    return AssinaturaCriada.com_segredo(assinatura)


@router.get(
    "/webhooks",
    response_model=Pagina[AssinaturaSaida],
    responses=respostas_erro(401, 403, 422),
    summary="Lista as assinaturas ativas (admin vê todas)",
    tags=["webhooks"],
)
async def listar_webhooks(
    usuario: UsuarioAtual, paginacao: Paginacao, uow: Uow
) -> Pagina[AssinaturaSaida]:
    itens, total = await listar_assinaturas(
        uow, solicitante_de(usuario), deslocamento=paginacao.deslocamento, limite=paginacao.tamanho
    )
    return Pagina[AssinaturaSaida].criar(
        [AssinaturaSaida.de(item) for item in itens], paginacao, total
    )


@router.delete(
    "/webhooks/{assinatura_id}",
    status_code=204,
    responses=respostas_erro(401, 403, 404, 422),
    summary="Remove (desativa) uma assinatura",
    tags=["webhooks"],
)
async def remover_webhook(assinatura_id: uuid.UUID, usuario: UsuarioAtual, uow: Uow) -> Response:
    await remover_assinatura(uow, solicitante_de(usuario), assinatura_id)
    return Response(status_code=204)


@router.get(
    "/webhooks/{assinatura_id}/entregas",
    response_model=Pagina[EntregaSaida],
    responses=respostas_erro(401, 403, 404, 422),
    summary="Lista as tentativas de entrega de uma assinatura",
    tags=["webhooks"],
)
async def listar_entregas_do_webhook(
    assinatura_id: uuid.UUID, usuario: UsuarioAtual, paginacao: Paginacao, uow: Uow
) -> Pagina[EntregaSaida]:
    itens, total = await listar_entregas(
        uow,
        solicitante_de(usuario),
        assinatura_id,
        deslocamento=paginacao.deslocamento,
        limite=paginacao.tamanho,
    )
    return Pagina[EntregaSaida].criar([EntregaSaida.de(item) for item in itens], paginacao, total)


@router.get(
    "/notificacoes",
    response_model=Pagina[NotificacaoSaida],
    responses=respostas_erro(401, 403, 422),
    summary="Lista notificações (não-admin só vê as próprias)",
    tags=["notificacoes"],
)
async def listar_notificacoes_do_usuario(
    usuario: UsuarioAtual,
    paginacao: Paginacao,
    uow: Uow,
    destinatario_id: Annotated[str | None, Query(max_length=128)] = None,
) -> Pagina[NotificacaoSaida]:
    itens, total = await listar_notificacoes(
        uow,
        solicitante_de(usuario),
        destinatario_id=destinatario_id,
        deslocamento=paginacao.deslocamento,
        limite=paginacao.tamanho,
    )
    return Pagina[NotificacaoSaida].criar(
        [NotificacaoSaida.de(item) for item in itens], paginacao, total
    )
