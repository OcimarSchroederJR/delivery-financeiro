"""Rotas de avaliações e do resumo por restaurante."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from avaliacoes.adaptadores.http.dependencias import Deps, solicitante
from avaliacoes.adaptadores.http.schemas import (
    AvaliacaoEntrada,
    AvaliacaoSaida,
    ResumoAvaliacoesSaida,
)
from avaliacoes.aplicacao.avaliacoes import (
    ComandoRegistrarAvaliacao,
    ConsultarAvaliacoes,
    RegistrarAvaliacao,
)
from plataforma.api.auth import UsuarioAtual, exigir_papeis
from plataforma.api.erros import respostas_erro
from plataforma.api.paginacao import Pagina, Paginacao
from plataforma.auth import Papel, Usuario

router = APIRouter(prefix="/v1", tags=["avaliacoes"])
SoCliente = Annotated[Usuario, Depends(exigir_papeis(Papel.CLIENTE))]


@router.post(
    "/avaliacoes",
    status_code=status.HTTP_201_CREATED,
    response_model=AvaliacaoSaida,
    responses=respostas_erro(401, 403, 409, 422, 503),
    summary="Avalia um pedido entregue (uma avaliação por pedido)",
)
async def registrar(entrada: AvaliacaoEntrada, usuario: SoCliente, deps: Deps) -> AvaliacaoSaida:
    caso = RegistrarAvaliacao(deps.uow, deps.pedidos, relogio=deps.relogio)
    avaliacao = await caso.executar(
        ComandoRegistrarAvaliacao(
            pedido_id=entrada.pedido_id,
            nota_restaurante=entrada.nota_restaurante,
            nota_entrega=entrada.nota_entrega,
            comentario=entrada.comentario,
        ),
        solicitante(usuario),
    )
    return AvaliacaoSaida.de(avaliacao)


@router.get(
    "/avaliacoes",
    response_model=Pagina[AvaliacaoSaida],
    responses=respostas_erro(401, 403, 422),
    summary="Lista avaliações, filtrando por restaurante e/ou pedido",
)
async def listar(
    _usuario: UsuarioAtual,
    deps: Deps,
    paginacao: Paginacao,
    restaurante_id: str | None = None,
    pedido_id: str | None = None,
) -> Pagina[AvaliacaoSaida]:
    itens, total = await ConsultarAvaliacoes(deps.uow).listar(
        restaurante_id=restaurante_id,
        pedido_id=pedido_id,
        deslocamento=paginacao.deslocamento,
        limite=paginacao.tamanho,
    )
    return Pagina[AvaliacaoSaida].criar([AvaliacaoSaida.de(a) for a in itens], paginacao, total)


@router.get(
    "/avaliacoes/{avaliacao_id}",
    response_model=AvaliacaoSaida,
    responses=respostas_erro(401, 403, 404, 422),
    summary="Detalha uma avaliação",
)
async def obter(avaliacao_id: uuid.UUID, _usuario: UsuarioAtual, deps: Deps) -> AvaliacaoSaida:
    return AvaliacaoSaida.de(await ConsultarAvaliacoes(deps.uow).obter(avaliacao_id))


@router.get(
    "/resumos-avaliacoes/{restaurante_id}",
    response_model=ResumoAvaliacoesSaida,
    responses=respostas_erro(401, 403),
    summary="Médias de notas e total de avaliações de um restaurante",
)
async def resumir(restaurante_id: str, _usuario: UsuarioAtual, deps: Deps) -> ResumoAvaliacoesSaida:
    return ResumoAvaliacoesSaida.de(await ConsultarAvaliacoes(deps.uow).resumir(restaurante_id))
