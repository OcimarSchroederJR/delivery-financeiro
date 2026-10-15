"""Rotas de disputas. O ``PATCH`` (admin) inicia a saga de estorno."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi import status as http_status

from avaliacoes.adaptadores.http.dependencias import Deps, solicitante
from avaliacoes.adaptadores.http.schemas import DecisaoEntrada, DisputaEntrada, DisputaSaida
from avaliacoes.aplicacao.disputas import (
    AbrirDisputa,
    ComandoAbrirDisputa,
    ComandoDecidirDisputa,
    ConsultarDisputas,
    DecidirDisputa,
)
from avaliacoes.dominio.disputa import StatusDisputa
from plataforma.api.auth import exigir_papeis
from plataforma.api.erros import respostas_erro
from plataforma.api.paginacao import Pagina, Paginacao
from plataforma.auth import Papel, Usuario

router = APIRouter(prefix="/v1", tags=["disputas"])
SoCliente = Annotated[Usuario, Depends(exigir_papeis(Papel.CLIENTE))]
ClienteOuAdmin = Annotated[Usuario, Depends(exigir_papeis(Papel.CLIENTE, Papel.ADMIN))]
SoAdmin = Annotated[Usuario, Depends(exigir_papeis(Papel.ADMIN))]


@router.post(
    "/disputas",
    status_code=http_status.HTTP_201_CREATED,
    response_model=DisputaSaida,
    responses=respostas_erro(401, 403, 409, 422, 503),
    summary="Abre uma disputa sobre um pedido pago",
    description=(
        "Só o papel `cliente`. O pagamento contestável (aprovado ou parcialmente estornado) "
        "é buscado em Pagamentos com o token do cliente, e a listagem de Pagamentos só "
        "mostra ao cliente os pagamentos dele. Por isso, um pedido de outro cliente responde "
        "`422 PAGAMENTO_NAO_ENCONTRADO` (não `403`); o `403` é para papel diferente de "
        "`cliente`."
    ),
)
async def abrir(entrada: DisputaEntrada, usuario: SoCliente, deps: Deps) -> DisputaSaida:
    caso = AbrirDisputa(deps.uow, deps.pagamentos, relogio=deps.relogio)
    disputa = await caso.executar(
        ComandoAbrirDisputa(
            pedido_id=entrada.pedido_id,
            motivo=entrada.motivo,
            valor_solicitado_centavos=entrada.valor_solicitado_centavos,
            descricao=entrada.descricao,
        ),
        solicitante(usuario),
    )
    return DisputaSaida.de(disputa)


@router.get(
    "/disputas",
    response_model=Pagina[DisputaSaida],
    responses=respostas_erro(401, 403, 422),
    summary="Lista disputas (o cliente vê só as suas; o admin vê todas)",
)
async def listar(
    usuario: ClienteOuAdmin,
    deps: Deps,
    paginacao: Paginacao,
    status: StatusDisputa | None = None,
) -> Pagina[DisputaSaida]:
    itens, total = await ConsultarDisputas(deps.uow).listar(
        status=status,
        solicitante=solicitante(usuario),
        deslocamento=paginacao.deslocamento,
        limite=paginacao.tamanho,
    )
    return Pagina[DisputaSaida].criar([DisputaSaida.de(d) for d in itens], paginacao, total)


@router.get(
    "/disputas/{disputa_id}",
    response_model=DisputaSaida,
    responses=respostas_erro(401, 403, 404, 422),
    summary="Detalha uma disputa",
)
async def obter(disputa_id: uuid.UUID, usuario: ClienteOuAdmin, deps: Deps) -> DisputaSaida:
    disputa = await ConsultarDisputas(deps.uow).obter(disputa_id, solicitante(usuario))
    return DisputaSaida.de(disputa)


@router.patch(
    "/disputas/{disputa_id}",
    response_model=DisputaSaida,
    responses={
        202: {
            "model": DisputaSaida,
            "description": "Procedente, com estorno pendente (Pagamentos indisponível); "
            "o worker conclui depois.",
        },
        **respostas_erro(401, 403, 404, 409, 422),
    },
    summary="Decide a disputa (admin): procedente dispara o estorno; improcedente encerra",
)
async def decidir(
    disputa_id: uuid.UUID,
    entrada: DecisaoEntrada,
    _usuario: SoAdmin,
    deps: Deps,
    resposta: Response,
) -> DisputaSaida:
    caso = DecidirDisputa(deps.uow, deps.saga(), relogio=deps.relogio)
    disputa = await caso.executar(
        disputa_id,
        ComandoDecidirDisputa(
            decisao=entrada.status,
            valor_aprovado_centavos=entrada.valor_aprovado_centavos,
            parecer=entrada.parecer,
        ),
    )
    if disputa.status is StatusDisputa.ESTORNO_PENDENTE:
        resposta.status_code = http_status.HTTP_202_ACCEPTED
    return DisputaSaida.de(disputa)
