import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from pagamentos.aplicacao.estornar_pagamento import (
    ComandoEstornar,
    EstornarPagamento,
    ResultadoEstorno,
)
from pagamentos.aplicacao.idempotencia import ReservaIdempotencia
from pagamentos.dominio.erros import (
    PagamentoNaoEncontrado,
    PagamentoNaoEstornavel,
    ValorExcedeSaldoEstornavel,
)
from pagamentos.dominio.eventos import dados_pagamento_estornado
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave
from pagamentos.dominio.pagamento import Pagamento, StatusPagamento
from pagamentos.testes.fakes import (
    INSTANTE,
    ApresentadorFake,
    EstadoFake,
    RelogioFake,
    fabrica_fake,
    pagamento_aprovado,
    pagamento_recusado,
)

ESTORNO_ID = UUID("00000000-0000-4000-8000-0000000000e1")
DEPOIS = INSTANTE + timedelta(hours=1)
ESCOPO = "POST /v1/pagamentos/x/estornos"


def _caso(estado: EstadoFake) -> EstornarPagamento:
    return EstornarPagamento(
        fabrica_uow=fabrica_fake(estado),
        apresentador=ApresentadorFake(),
        relogio=RelogioFake(DEPOIS),
        gerar_id=lambda: ESTORNO_ID,
    )


def _semear(estado: EstadoFake, pagamento: Pagamento | None = None) -> Pagamento:
    pagamento = pagamento or pagamento_aprovado()
    estado.pagamentos[pagamento.id] = pagamento
    return pagamento


def _reservar(estado: EstadoFake) -> ReservaIdempotencia:
    registro = RegistroIdempotencia.reservar(
        escopo=ESCOPO, chave="disputa-1", hash_requisicao="h", agora=INSTANTE
    )
    estado.chaves[(ESCOPO, "disputa-1")] = registro
    return ReservaIdempotencia(ESCOPO, "disputa-1", registro.dono)


async def test_estorno_parcial_grava_e_publica_evento() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    resultado = await _caso(estado).executar(ComandoEstornar(pagamento.id, "item faltando", 1000))
    assert isinstance(resultado, ResultadoEstorno)
    estorno = resultado.estorno
    assert (estorno.id, estorno.valor_centavos, estorno.criado_em) == (ESTORNO_ID, 1000, DEPOIS)
    assert resultado.status_pagamento == StatusPagamento.PARCIALMENTE_ESTORNADO
    salvo = estado.pagamentos[pagamento.id]
    assert salvo.status == StatusPagamento.PARCIALMENTE_ESTORNADO
    assert (salvo.saldo_estornavel_centavos, salvo.atualizado_em) == (3590, DEPOIS)
    assert estado.eventos == [("pagamento.estornado", dados_pagamento_estornado(salvo, estorno))]
    assert estado.commits == 1


async def test_sem_valor_estorna_o_saldo_inteiro() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    resultado = await _caso(estado).executar(ComandoEstornar(pagamento.id, "disputa"))
    assert resultado.estorno.valor_centavos == 4590
    assert resultado.status_pagamento == StatusPagamento.ESTORNADO
    assert estado.pagamentos[pagamento.id].status == StatusPagamento.ESTORNADO


async def test_valor_acima_do_saldo_nao_altera_nada() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    with pytest.raises(ValorExcedeSaldoEstornavel) as erro:
        await _caso(estado).executar(ComandoEstornar(pagamento.id, "x", 5000))
    assert erro.value.saldo_estornavel_centavos == 4590
    salvo = estado.pagamentos[pagamento.id]
    assert (salvo.status, salvo.estornos) == (StatusPagamento.APROVADO, [])
    assert (estado.eventos, estado.commits) == ([], 0)


async def test_pagamento_inexistente() -> None:
    with pytest.raises(PagamentoNaoEncontrado):
        await _caso(EstadoFake()).executar(ComandoEstornar(uuid4(), "x"))


async def test_pagamento_recusado_nao_e_estornavel() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado, pagamento_recusado())
    with pytest.raises(PagamentoNaoEstornavel):
        await _caso(estado).executar(ComandoEstornar(pagamento.id, "x"))


async def test_conclui_a_chave_na_mesma_transacao() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    reserva = _reservar(estado)
    await _caso(estado).executar(ComandoEstornar(pagamento.id, "x", 1000), reserva)
    registro = estado.chaves[(ESCOPO, "disputa-1")]
    assert registro.resposta() == (
        201,
        {"id": str(ESTORNO_ID), "valor_centavos": 1000, "status": "parcialmente_estornado"},
    )


async def test_erro_de_negocio_deixa_a_chave_para_o_executor() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    reserva = _reservar(estado)
    with pytest.raises(ValorExcedeSaldoEstornavel):
        await _caso(estado).executar(ComandoEstornar(pagamento.id, "x", 9999), reserva)
    assert estado.chaves[(ESCOPO, "disputa-1")].status == StatusChave.EM_PROCESSAMENTO


async def _reassumir(estado: EstadoFake, *, a_falha_com_503: bool) -> list[Exception]:
    """A reserva a chave e para; B reassume depois de 60 s e estorna; então A retoma."""
    from pagamentos.aplicacao.idempotencia import ExecutorIdempotente
    from plataforma.erros import ErroDependenciaIndisponivel

    pagamento = estado.pagamentos[next(iter(estado.pagamentos))]
    comando = ComandoEstornar(pagamento.id, "disputa", 1000)
    dados = {"corpo": {"valor_centavos": 1000, "motivo": "disputa"}}

    def executor(relogio: RelogioFake) -> ExecutorIdempotente:
        return ExecutorIdempotente(
            fabrica_fake(estado), ApresentadorFake(), chave_hash=b"h" * 32, relogio=relogio
        )

    def caso(relogio: RelogioFake) -> EstornarPagamento:
        return EstornarPagamento(
            fabrica_uow=fabrica_fake(estado), apresentador=ApresentadorFake(), relogio=relogio
        )

    a_reservou, a_pode_seguir = asyncio.Event(), asyncio.Event()

    async def operacao_a(reserva: ReservaIdempotencia) -> ResultadoEstorno:
        a_reservou.set()
        await a_pode_seguir.wait()
        if a_falha_com_503:
            raise ErroDependenciaIndisponivel("gateway")
        return await caso(RelogioFake(INSTANTE)).executar(comando, reserva)

    relogio_b = RelogioFake(INSTANTE + timedelta(seconds=61))
    tarefa_a = asyncio.create_task(
        executor(RelogioFake(INSTANTE)).executar(
            chave="disputa-1", escopo=ESCOPO, dados=dados, operacao=operacao_a
        )
    )
    await a_reservou.wait()
    b_reservou, b_pode_seguir = asyncio.Event(), asyncio.Event()

    async def operacao_b(reserva: ReservaIdempotencia) -> ResultadoEstorno:
        b_reservou.set()
        await b_pode_seguir.wait()
        return await caso(relogio_b).executar(comando, reserva)

    tarefa_b = asyncio.create_task(
        executor(relogio_b).executar(
            chave="disputa-1", escopo=ESCOPO, dados=dados, operacao=operacao_b
        )
    )
    await b_reservou.wait()
    if a_falha_com_503:
        a_pode_seguir.set()  # A falha (5xx) depois que B reassumiu, antes de B concluir
        await asyncio.gather(tarefa_a, return_exceptions=True)
        b_pode_seguir.set()
    else:
        b_pode_seguir.set()  # B estorna e conclui; só então A retoma
        await asyncio.gather(tarefa_b, return_exceptions=True)
        a_pode_seguir.set()
    resultados = await asyncio.gather(tarefa_a, tarefa_b, return_exceptions=True)
    return [r for r in resultados if isinstance(r, Exception)]


async def test_reassuncao_apos_60s_nao_estorna_duas_vezes() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    erros = await _reassumir(estado, a_falha_com_503=False)
    assert [type(e).__name__ for e in erros] == ["ReservaIdempotenciaPerdida"]
    assert len(estado.pagamentos[pagamento.id].estornos) == 1
    assert [tipo for tipo, _ in estado.eventos] == ["pagamento.estornado"]
    assert estado.chaves[(ESCOPO, "disputa-1")].status == StatusChave.CONCLUIDA


async def test_falha_de_quem_perdeu_a_reserva_nao_apaga_a_reserva_nova() -> None:
    estado = EstadoFake()
    pagamento = _semear(estado)
    erros = await _reassumir(estado, a_falha_com_503=True)
    assert [type(e).__name__ for e in erros] == ["ErroDependenciaIndisponivel"]
    assert len(estado.pagamentos[pagamento.id].estornos) == 1
    assert estado.chaves[(ESCOPO, "disputa-1")].status == StatusChave.CONCLUIDA
