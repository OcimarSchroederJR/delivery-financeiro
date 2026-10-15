"""Rotas HTTP de pagamentos e estornos (spec §4.1)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from pagamentos.adaptadores.http.dependencias import (
    HEADER_RESPOSTA_REPETIDA,
    CasosDeUsoDep,
    ClienteOuAdmin,
    IdempotencyKey,
    para_solicitante,
)
from pagamentos.adaptadores.http.esquemas import CriarPagamentoEntrada, PagamentoSaida
from pagamentos.aplicacao.idempotencia import ReservaIdempotencia, RespostaGravada
from pagamentos.dominio.erros import PagamentoNaoEncontrado
from pagamentos.dominio.pagamento import Pagamento
from plataforma.api.erros import respostas_erro

router = APIRouter(prefix="/v1/pagamentos", tags=["pagamentos"])

ESCOPO_CRIAR = "POST /v1/pagamentos"


def _uuid_ou_404(texto: str) -> UUID:
    try:
        return UUID(texto)
    except ValueError:
        raise PagamentoNaoEncontrado() from None


def _json(status: int, corpo: dict[str, Any], *, repetida: bool = False) -> JSONResponse:
    headers = {HEADER_RESPOSTA_REPETIDA: "true"} if repetida else None
    return JSONResponse(corpo, status_code=status, headers=headers)


@router.post(
    "",
    status_code=201,
    response_model=PagamentoSaida,
    responses=respostas_erro(400, 401, 403, 409, 422, 503),
    summary="Cria (autoriza) o pagamento de um pedido",
    description=(
        "O valor vem da Equipe 3. Recusa devolve 409 PAGAMENTO_RECUSADO com `pagamento_id`; "
        "a mesma Idempotency-Key com o mesmo corpo devolve a resposta gravada."
    ),
)
async def criar_pagamento(
    corpo: CriarPagamentoEntrada,
    usuario: ClienteOuAdmin,
    casos: CasosDeUsoDep,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    solicitante = para_solicitante(usuario)

    async def operar(reserva: ReservaIdempotencia) -> Pagamento:
        return await casos.criar_pagamento.executar(corpo.para_comando(), solicitante, reserva)

    resultado = await casos.idempotencia.executar(
        chave=idempotency_key,
        escopo=ESCOPO_CRIAR,
        dados={"usuario_id": usuario.id, "corpo": corpo.dados_idempotencia()},
        operacao=operar,
    )
    if isinstance(resultado, RespostaGravada):
        return _json(resultado.status, resultado.corpo, repetida=True)
    return _json(201, casos.apresentador.pagamento(resultado))
