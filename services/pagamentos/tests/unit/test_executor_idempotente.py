from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from pagamentos.aplicacao.idempotencia import (
    ExecutorIdempotente,
    ReservaIdempotencia,
    RespostaGravada,
)
from pagamentos.aplicacao.portas import FabricaUnidadeDeTrabalho, UnidadeDeTrabalho
from pagamentos.dominio.erros import (
    IdempotencyEmProcessamento,
    IdempotencyKeyAusente,
    IdempotencyKeyInvalida,
    IdempotencyKeyReutilizada,
    PagamentoRecusado,
    PedidoJaPago,
)
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave, calcular_hash
from pagamentos.testes.fakes import (
    INSTANTE,
    ApresentadorFake,
    EstadoFake,
    RelogioFake,
    UnidadeDeTrabalhoFake,
    fabrica_fake,
)
from plataforma.erros import ErroDependenciaIndisponivel

CHAVE_HASH = b"chave-de-hash-de-teste-0123456789"
ESCOPO = "POST /v1/teste"
DADOS = {"pedido_id": "ped-1"}


class Operacao:
    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.reservas: list[ReservaIdempotencia] = []

    async def __call__(self, reserva: ReservaIdempotencia) -> str:
        self.reservas.append(reserva)
        if self.erro is not None:
            raise self.erro
        return "ok"


def _executor(
    estado: EstadoFake,
    relogio: RelogioFake | None = None,
    fabrica: FabricaUnidadeDeTrabalho | None = None,
) -> ExecutorIdempotente:
    return ExecutorIdempotente(
        fabrica or fabrica_fake(estado),
        ApresentadorFake(),
        chave_hash=CHAVE_HASH,
        relogio=relogio or RelogioFake(),
    )


def _semear(estado: EstadoFake, status: StatusChave, criado_em: datetime = INSTANTE) -> None:
    concluida = status == StatusChave.CONCLUIDA
    estado.chaves[(ESCOPO, "k-1")] = RegistroIdempotencia(
        escopo=ESCOPO,
        chave="k-1",
        hash_requisicao=calcular_hash(DADOS, chave=CHAVE_HASH),
        status=status,
        criado_em=criado_em,
        status_resposta=201 if concluida else None,
        corpo_resposta={"id": "p-1"} if concluida else None,
    )


async def test_primeira_execucao_reserva_e_chama_a_operacao() -> None:
    estado, operacao = EstadoFake(), Operacao()
    resultado = await _executor(estado).executar(
        chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao
    )
    assert resultado == "ok"
    assert operacao.reservas == [ReservaIdempotencia(escopo=ESCOPO, chave="k-1")]
    registro = estado.chaves[(ESCOPO, "k-1")]
    # Concluir a chave é responsabilidade da operação, na transação do efeito.
    assert registro.status == StatusChave.EM_PROCESSAMENTO
    assert registro.hash_requisicao == calcular_hash(DADOS, chave=CHAVE_HASH)
    assert registro.criado_em == INSTANTE


async def test_resposta_gravada_e_repetida_sem_executar() -> None:
    estado, operacao = EstadoFake(), Operacao()
    _semear(estado, StatusChave.CONCLUIDA)
    resultado = await _executor(estado).executar(
        chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao
    )
    assert resultado == RespostaGravada(status=201, corpo={"id": "p-1"})
    assert operacao.reservas == []


async def test_mesma_chave_com_corpo_diferente() -> None:
    estado, operacao = EstadoFake(), Operacao()
    _semear(estado, StatusChave.CONCLUIDA)
    with pytest.raises(IdempotencyKeyReutilizada):
        await _executor(estado).executar(
            chave="k-1", escopo=ESCOPO, dados={"pedido_id": "ped-2"}, operacao=operacao
        )
    assert operacao.reservas == []


async def test_em_processamento_recente() -> None:
    estado, operacao = EstadoFake(), Operacao()
    _semear(estado, StatusChave.EM_PROCESSAMENTO)
    relogio = RelogioFake(INSTANTE + timedelta(seconds=30))
    with pytest.raises(IdempotencyEmProcessamento):
        await _executor(estado, relogio).executar(
            chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao
        )
    assert operacao.reservas == []


async def test_em_processamento_abandonado_e_reassumido() -> None:
    estado, operacao = EstadoFake(), Operacao()
    _semear(estado, StatusChave.EM_PROCESSAMENTO)
    relogio = RelogioFake(INSTANTE + timedelta(seconds=61))
    assert (
        await _executor(estado, relogio).executar(
            chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao
        )
        == "ok"
    )
    assert len(operacao.reservas) == 1
    assert estado.chaves[(ESCOPO, "k-1")].criado_em == relogio.agora


async def test_chave_expirada_e_processada_de_novo() -> None:
    estado, operacao = EstadoFake(), Operacao()
    _semear(estado, StatusChave.CONCLUIDA)
    relogio = RelogioFake(INSTANTE + timedelta(hours=24))
    await _executor(estado, relogio).executar(
        chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao
    )
    registro = estado.chaves[(ESCOPO, "k-1")]
    assert len(operacao.reservas) == 1
    assert (registro.status, registro.status_resposta) == (StatusChave.EM_PROCESSAMENTO, None)


async def test_erro_4xx_tem_a_resposta_gravada_e_repetida() -> None:
    estado, operacao = EstadoFake(), Operacao(erro=PedidoJaPago())
    executor = _executor(estado)
    with pytest.raises(PedidoJaPago):
        await executor.executar(chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao)
    registro = estado.chaves[(ESCOPO, "k-1")]
    assert (registro.status, registro.status_resposta) == (StatusChave.CONCLUIDA, 409)
    assert registro.corpo_resposta is not None
    assert registro.corpo_resposta["codigo"] == "PEDIDO_JA_PAGO"
    repetida = await executor.executar(chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao)
    assert isinstance(repetida, RespostaGravada)
    assert repetida.status == 409
    assert len(operacao.reservas) == 1


async def test_erro_5xx_libera_a_chave_para_nova_tentativa() -> None:
    estado, operacao = EstadoFake(), Operacao(erro=ErroDependenciaIndisponivel("pedidos"))
    executor = _executor(estado)
    for _ in range(2):
        with pytest.raises(ErroDependenciaIndisponivel):
            await executor.executar(chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao)
        assert (ESCOPO, "k-1") not in estado.chaves
    assert len(operacao.reservas) == 2


async def test_excecao_inesperada_libera_a_chave() -> None:
    estado, operacao = EstadoFake(), Operacao(erro=RuntimeError("falha inesperada"))
    with pytest.raises(RuntimeError, match="falha inesperada"):
        await _executor(estado).executar(chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao)
    assert estado.chaves == {}


@pytest.mark.parametrize("chave", [None, "", "   "])
async def test_chave_ausente(chave: str | None) -> None:
    estado, operacao = EstadoFake(), Operacao()
    with pytest.raises(IdempotencyKeyAusente):
        await _executor(estado).executar(chave=chave, escopo=ESCOPO, dados=DADOS, operacao=operacao)
    assert (estado.chaves, operacao.reservas) == ({}, [])


async def test_chave_fora_do_formato() -> None:
    estado, operacao = EstadoFake(), Operacao()
    with pytest.raises(IdempotencyKeyInvalida):
        await _executor(estado).executar(
            chave="x" * 256, escopo=ESCOPO, dados=DADOS, operacao=operacao
        )
    assert estado.chaves == {}


async def test_conclusao_feita_pela_operacao_prevalece() -> None:
    estado = EstadoFake()

    async def operacao(reserva: ReservaIdempotencia) -> str:
        async with UnidadeDeTrabalhoFake(estado) as uow:
            await uow.chaves_idempotencia.concluir(
                reserva.escopo, reserva.chave, status_resposta=409, corpo_resposta={"de": "op"}
            )
            await uow.commit()
        raise PagamentoRecusado(uuid4(), "saldo_insuficiente")

    with pytest.raises(PagamentoRecusado):
        await _executor(estado).executar(chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao)
    assert estado.chaves[(ESCOPO, "k-1")].corpo_resposta == {"de": "op"}


async def test_falha_ao_liberar_nao_esconde_o_erro_original() -> None:
    estado, chamadas = EstadoFake(), 0

    def fabrica() -> UnidadeDeTrabalho:
        nonlocal chamadas
        chamadas += 1
        if chamadas > 1:
            raise RuntimeError("banco fora")
        return UnidadeDeTrabalhoFake(estado)

    operacao = Operacao(erro=ErroDependenciaIndisponivel("gateway"))
    with pytest.raises(ErroDependenciaIndisponivel):
        await _executor(estado, fabrica=fabrica).executar(
            chave="k-1", escopo=ESCOPO, dados=DADOS, operacao=operacao
        )
