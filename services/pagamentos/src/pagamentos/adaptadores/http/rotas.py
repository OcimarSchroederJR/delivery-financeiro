"""Rotas HTTP de pagamentos e estornos (spec §4.1)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from pagamentos.adaptadores.http.dependencias import (
    HEADER_RESPOSTA_REPETIDA,
    CasosDeUsoDep,
    ClienteOuAdmin,
    IdempotencyKey,
    LeitorDaLista,
    QuemEstorna,
    para_solicitante,
)
from pagamentos.adaptadores.http.esquemas import (
    PADRAO_ID_EXTERNO,
    CriarPagamentoEntrada,
    EstornarEntrada,
    EstornoCriadoSaida,
    EstornoSaida,
    PagamentoSaida,
)
from pagamentos.aplicacao.estornar_pagamento import ComandoEstornar, ResultadoEstorno
from pagamentos.aplicacao.idempotencia import ReservaIdempotencia, RespostaGravada
from pagamentos.dominio.erros import PagamentoNaoEncontrado
from pagamentos.dominio.pagamento import Pagamento
from plataforma.api.erros import respostas_erro
from plataforma.api.paginacao import Pagina, Paginacao

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


@router.get(
    "",
    response_model=Pagina[PagamentoSaida],
    responses=respostas_erro(401, 403, 422),
    summary="Lista pagamentos (cliente vê só os seus; admin e serviço veem todos)",
)
async def listar_pagamentos(
    usuario: LeitorDaLista,
    casos: CasosDeUsoDep,
    paginacao: Paginacao,
    pedido_id: Annotated[str | None, Query(pattern=PADRAO_ID_EXTERNO)] = None,
) -> Pagina[PagamentoSaida]:
    itens, total = await casos.consultas.listar(
        para_solicitante(usuario),
        pedido_id=pedido_id,
        deslocamento=paginacao.deslocamento,
        limite=paginacao.tamanho,
    )
    return Pagina[PagamentoSaida].criar(
        [PagamentoSaida.de_dominio(p) for p in itens], paginacao, total
    )


@router.get(
    "/{pagamento_id}",
    response_model=PagamentoSaida,
    responses=respostas_erro(401, 403, 404),
    summary="Detalha um pagamento",
)
async def obter_pagamento(
    pagamento_id: str, usuario: ClienteOuAdmin, casos: CasosDeUsoDep
) -> PagamentoSaida:
    pagamento = await casos.consultas.obter(_uuid_ou_404(pagamento_id), para_solicitante(usuario))
    return PagamentoSaida.de_dominio(pagamento)


def _escopo_estorno(pagamento_id: UUID) -> str:
    return f"POST /v1/pagamentos/{pagamento_id}/estornos"


@router.post(
    "/{pagamento_id}/estornos",
    status_code=201,
    response_model=EstornoCriadoSaida,
    responses=respostas_erro(400, 401, 403, 404, 409, 422),
    summary="Estorna total ou parcialmente um pagamento",
    description=(
        "Sem `valor_centavos`, estorna o saldo estornável inteiro. Aceita token de serviço "
        "(saga de disputa de Avaliações). A mesma Idempotency-Key devolve o estorno gravado."
    ),
)
async def estornar_pagamento(
    pagamento_id: str,
    corpo: EstornarEntrada,
    usuario: QuemEstorna,
    casos: CasosDeUsoDep,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    identificador = _uuid_ou_404(pagamento_id)
    comando = ComandoEstornar(
        pagamento_id=identificador, motivo=corpo.motivo, valor_centavos=corpo.valor_centavos
    )

    async def operar(reserva: ReservaIdempotencia) -> ResultadoEstorno:
        return await casos.estornar_pagamento.executar(comando, reserva)

    resultado = await casos.idempotencia.executar(
        chave=idempotency_key,
        escopo=_escopo_estorno(identificador),
        dados={"corpo": corpo.dados_idempotencia()},
        operacao=operar,
    )
    if isinstance(resultado, RespostaGravada):
        return _json(resultado.status, resultado.corpo, repetida=True)
    return _json(201, casos.apresentador.estorno(resultado.estorno, resultado.status_pagamento))


@router.get(
    "/{pagamento_id}/estornos",
    response_model=Pagina[EstornoSaida],
    responses=respostas_erro(401, 403, 404, 422),
    summary="Lista os estornos de um pagamento",
)
async def listar_estornos(
    pagamento_id: str, usuario: ClienteOuAdmin, casos: CasosDeUsoDep, paginacao: Paginacao
) -> Pagina[EstornoSaida]:
    estornos = await casos.consultas.listar_estornos(
        _uuid_ou_404(pagamento_id), para_solicitante(usuario)
    )
    fatia = estornos[paginacao.deslocamento : paginacao.deslocamento + paginacao.tamanho]
    return Pagina[EstornoSaida].criar(
        [EstornoSaida.de_dominio(e) for e in fatia], paginacao, len(estornos)
    )
