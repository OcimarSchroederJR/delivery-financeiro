"""Reassunção da Idempotency-Key depois de 60 s com duas execuções sobrepostas (banco real)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pagamentos.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql
from pagamentos.aplicacao.estornar_pagamento import (
    ComandoEstornar,
    EstornarPagamento,
    ResultadoEstorno,
)
from pagamentos.aplicacao.idempotencia import ExecutorIdempotente, ReservaIdempotencia
from pagamentos.aplicacao.portas import UnidadeDeTrabalho
from pagamentos.dominio.erros import IdempotencyEmProcessamento
from pagamentos.dominio.pagamento import Pagamento
from pagamentos.testes.fakes import INSTANTE, ApresentadorFake, RelogioFake, pagamento_aprovado
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.erros import ErroDependenciaIndisponivel

pytestmark = pytest.mark.integracao

ESCOPO = "POST /v1/pagamentos/x/estornos"
DADOS = {"corpo": {"valor_centavos": 1000, "motivo": "disputa"}}


@pytest.fixture
async def sessoes(banco_migrado: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = criar_engine(banco_migrado)
    yield criar_fabrica_sessoes(engine)
    await engine.dispose()


async def _sobrepor(
    sessoes: async_sessionmaker[AsyncSession], *, a_falha_com_503: bool
) -> tuple[Pagamento, list[BaseException]]:
    def fabrica() -> UnidadeDeTrabalho:
        return UnidadeDeTrabalhoSql(sessoes)

    pagamento = pagamento_aprovado()
    async with fabrica() as uow:
        await uow.pagamentos.adicionar(pagamento)
        await uow.commit()
    comando = ComandoEstornar(pagamento.id, "disputa", 1000)

    def executor(relogio: RelogioFake) -> ExecutorIdempotente:
        return ExecutorIdempotente(
            fabrica, ApresentadorFake(), chave_hash=b"h" * 32, relogio=relogio
        )

    def caso(relogio: RelogioFake) -> EstornarPagamento:
        return EstornarPagamento(
            fabrica_uow=fabrica, apresentador=ApresentadorFake(), relogio=relogio
        )

    relogio_a, relogio_b = RelogioFake(INSTANTE), RelogioFake(INSTANTE + timedelta(seconds=61))
    a_reservou, a_segue, b_reservou, b_segue = (asyncio.Event() for _ in range(4))

    async def operacao_a(reserva: ReservaIdempotencia) -> ResultadoEstorno:
        a_reservou.set()
        await a_segue.wait()
        if a_falha_com_503:
            raise ErroDependenciaIndisponivel("gateway")
        return await caso(relogio_a).executar(comando, reserva)

    async def operacao_b(reserva: ReservaIdempotencia) -> ResultadoEstorno:
        b_reservou.set()
        await b_segue.wait()
        return await caso(relogio_b).executar(comando, reserva)

    tarefa_a = asyncio.create_task(
        executor(relogio_a).executar(
            chave="disputa-1", escopo=ESCOPO, dados=DADOS, operacao=operacao_a
        )
    )
    await a_reservou.wait()
    tarefa_b = asyncio.create_task(
        executor(relogio_b).executar(
            chave="disputa-1", escopo=ESCOPO, dados=DADOS, operacao=operacao_b
        )
    )
    await b_reservou.wait()
    primeira, segunda = (a_segue, b_segue) if a_falha_com_503 else (b_segue, a_segue)
    primeira_tarefa = tarefa_a if a_falha_com_503 else tarefa_b
    primeira.set()
    await asyncio.gather(primeira_tarefa, return_exceptions=True)
    segunda.set()
    resultados = await asyncio.gather(tarefa_a, tarefa_b, return_exceptions=True)
    return pagamento, [r for r in resultados if isinstance(r, BaseException)]


async def _contar(sessoes: async_sessionmaker[AsyncSession], sql: str) -> int:
    async with sessoes() as sessao:
        return int((await sessao.execute(text(sql))).scalar_one())


async def test_reassuncao_sobreposta_estorna_exatamente_uma_vez(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    _, erros = await _sobrepor(sessoes, a_falha_com_503=False)
    assert len(erros) == 1
    assert isinstance(erros[0], IdempotencyEmProcessamento)
    assert await _contar(sessoes, "SELECT count(*) FROM estornos") == 1
    assert (
        await _contar(sessoes, "SELECT count(*) FROM outbox WHERE tipo = 'pagamento.estornado'")
        == 1
    )
    assert (
        await _contar(
            sessoes,
            "SELECT count(*) FROM chaves_idempotencia"
            " WHERE status = 'concluida' AND status_resposta = 201",
        )
        == 1
    )


async def test_falha_5xx_de_quem_perdeu_a_reserva_nao_apaga_a_de_quem_reassumiu(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    _, erros = await _sobrepor(sessoes, a_falha_com_503=True)
    assert [type(e) for e in erros] == [ErroDependenciaIndisponivel]
    assert await _contar(sessoes, "SELECT count(*) FROM estornos") == 1
    assert (
        await _contar(
            sessoes, "SELECT count(*) FROM chaves_idempotencia WHERE status = 'concluida'"
        )
        == 1
    )
