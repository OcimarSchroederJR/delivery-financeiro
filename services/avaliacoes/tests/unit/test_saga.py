import uuid
from datetime import timedelta

import pytest

from avaliacoes.aplicacao.disputas import (
    AbrirDisputa,
    ComandoAbrirDisputa,
    ComandoDecidirDisputa,
    DecidirDisputa,
)
from avaliacoes.aplicacao.portas import (
    EstornoRealizado,
    FabricaUnidadeDeTrabalho,
    FalhaDefinitiva,
    FalhaTransitoria,
    Solicitante,
)
from avaliacoes.aplicacao.saga import PoliticaDeRetentativa, RetentativaDeEstornos, SagaEstorno
from avaliacoes.dominio.disputa import Decisao, Disputa, MotivoDisputa, StatusDisputa
from avaliacoes.dominio.erros import DisputaNaoEncontrada, TransicaoInvalida, ValorAprovadoInvalido
from avaliacoes.testes.fakes import BancoEmMemoria, EmissorTokenFake, PagamentosFake, RelogioFake

CLIENTE_1 = Solicitante(id="cliente-1", token="token-cliente-1")
PROCEDENTE = ComandoDecidirDisputa(Decisao.PROCEDENTE, parecer="faltou mesmo")


@pytest.fixture
async def disputa(
    uow: FabricaUnidadeDeTrabalho, pagamentos: PagamentosFake, relogio: RelogioFake
) -> Disputa:
    pagamentos.adicionar("ped-4", pagamento_id="pag-1", valor_centavos=3200)
    comando = ComandoAbrirDisputa("ped-4", MotivoDisputa.ITEM_FALTANDO, 1000)
    return await AbrirDisputa(uow, pagamentos, relogio=relogio).executar(comando, CLIENTE_1)


@pytest.fixture
def decidir(
    uow: FabricaUnidadeDeTrabalho, saga: SagaEstorno, relogio: RelogioFake
) -> DecidirDisputa:
    return DecidirDisputa(uow, saga, relogio=relogio)


def test_politica_backoff_exponencial_com_teto() -> None:
    politica = PoliticaDeRetentativa(
        espera_base=timedelta(seconds=5), espera_maxima=timedelta(seconds=60)
    )
    esperas = [politica.espera_apos(n).total_seconds() for n in range(1, 7)]
    assert esperas == [5, 10, 20, 40, 60, 60]
    assert not politica.esgotou(9)
    assert politica.esgotou(10)


async def test_improcedente_resolve_com_valor_zero_sem_chamar_pagamentos(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    banco: BancoEmMemoria,
) -> None:
    resultado = await decidir.executar(
        disputa.id, ComandoDecidirDisputa(Decisao.IMPROCEDENTE, parecer="sem provas")
    )
    assert resultado.status is StatusDisputa.IMPROCEDENTE
    assert pagamentos.chamadas_estorno == []
    assert banco.eventos[-1] == (
        "disputa.resolvida",
        {
            "disputa_id": str(disputa.id),
            "pedido_id": "ped-4",
            "cliente_id": "cliente-1",
            "decisao": "improcedente",
            "valor_estornado_centavos": 0,
        },
    )


async def test_procedente_com_estorno_ok_resolve(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    banco: BancoEmMemoria,
) -> None:
    pagamentos.programar_estorno(EstornoRealizado("est-77"))
    resultado = await decidir.executar(disputa.id, PROCEDENTE)
    assert resultado.status is StatusDisputa.RESOLVIDA
    assert resultado.estorno_id == "est-77"
    assert resultado.tentativas_estorno == 1
    [chamada] = pagamentos.chamadas_estorno
    assert chamada.pagamento_id == "pag-1"
    assert chamada.valor_centavos == 1000
    assert chamada.chave_idempotencia == f"disputa-{disputa.id}"
    assert chamada.token == "token-de-servico-fake"
    assert banco.eventos[-1] == (
        "disputa.resolvida",
        {
            "disputa_id": str(disputa.id),
            "pedido_id": "ped-4",
            "cliente_id": "cliente-1",
            "decisao": "procedente",
            "valor_estornado_centavos": 1000,
        },
    )


async def test_estorno_pendente_e_gravado_antes_da_chamada(
    uow: FabricaUnidadeDeTrabalho,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    banco: BancoEmMemoria,
    relogio: RelogioFake,
) -> None:
    """Passo 1 da saga: se o processo morrer durante a chamada, o worker retoma."""
    vistos: list[StatusDisputa] = []

    class PagamentosQueObserva(PagamentosFake):
        async def estornar(self, pagamento_id: str, **kwargs: object) -> EstornoRealizado:
            vistos.append(banco.disputas[disputa.id].status)
            return EstornoRealizado("est-1")

    saga = SagaEstorno(uow, PagamentosQueObserva(), EmissorTokenFake(), relogio=relogio)
    await DecidirDisputa(uow, saga, relogio=relogio).executar(disputa.id, PROCEDENTE)
    assert vistos == [StatusDisputa.ESTORNO_PENDENTE]


async def test_valor_aprovado_parcial(
    decidir: DecidirDisputa, disputa: Disputa, pagamentos: PagamentosFake
) -> None:
    comando = ComandoDecidirDisputa(Decisao.PROCEDENTE, valor_aprovado_centavos=400)
    resultado = await decidir.executar(disputa.id, comando)
    assert resultado.valor_aprovado_centavos == 400
    assert pagamentos.chamadas_estorno[0].valor_centavos == 400


async def test_valor_aprovado_invalido_nao_muda_nada(
    decidir: DecidirDisputa, disputa: Disputa, banco: BancoEmMemoria
) -> None:
    comando = ComandoDecidirDisputa(Decisao.PROCEDENTE, valor_aprovado_centavos=1001)
    with pytest.raises(ValorAprovadoInvalido):
        await decidir.executar(disputa.id, comando)
    assert banco.disputas[disputa.id].status is StatusDisputa.ABERTA


async def test_falha_transitoria_mantem_pendente_e_agenda_retentativa(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    banco: BancoEmMemoria,
    relogio: RelogioFake,
) -> None:
    pagamentos.programar_estorno(FalhaTransitoria("DEPENDENCIA_INDISPONIVEL"))
    resultado = await decidir.executar(disputa.id, PROCEDENTE)
    assert resultado.status is StatusDisputa.ESTORNO_PENDENTE
    assert resultado.tentativas_estorno == 1
    assert resultado.proxima_tentativa_em == relogio.agora + timedelta(seconds=5)
    assert banco.tipos_de_eventos() == ["disputa.aberta"]


async def test_falha_definitiva_vira_estorno_falhou(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    banco: BancoEmMemoria,
) -> None:
    pagamentos.programar_estorno(FalhaDefinitiva("PAGAMENTO_NAO_ESTORNAVEL"))
    resultado = await decidir.executar(disputa.id, PROCEDENTE)
    assert resultado.status is StatusDisputa.ESTORNO_FALHOU
    assert banco.eventos[-1] == (
        "disputa.estorno_falhou",
        {"disputa_id": str(disputa.id), "pedido_id": "ped-4", "motivo": "PAGAMENTO_NAO_ESTORNAVEL"},
    )


async def test_decidir_duas_vezes_e_transicao_invalida(
    decidir: DecidirDisputa, disputa: Disputa
) -> None:
    await decidir.executar(disputa.id, PROCEDENTE)
    with pytest.raises(TransicaoInvalida):
        await decidir.executar(disputa.id, PROCEDENTE)


async def test_decidir_inexistente(decidir: DecidirDisputa) -> None:
    with pytest.raises(DisputaNaoEncontrada):
        await decidir.executar(uuid.uuid4(), PROCEDENTE)


async def test_worker_conclui_depois_de_pagamentos_voltar(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    saga: SagaEstorno,
    uow: FabricaUnidadeDeTrabalho,
    banco: BancoEmMemoria,
    relogio: RelogioFake,
) -> None:
    """Spec §9: Pagamentos fora durante a saga → 202 e conclusão posterior."""
    pagamentos.programar_estorno(FalhaTransitoria("DEPENDENCIA_INDISPONIVEL"))
    await decidir.executar(disputa.id, PROCEDENTE)
    retentativa = RetentativaDeEstornos(uow, saga, relogio=relogio)

    assert await retentativa.processar_lote() == 0  # ainda não venceu o backoff
    relogio.avancar(seconds=5)
    assert await retentativa.processar_lote() == 1

    resolvida = banco.disputas[disputa.id]
    assert resolvida.status is StatusDisputa.RESOLVIDA
    assert resolvida.tentativas_estorno == 2
    chaves = {c.chave_idempotencia for c in pagamentos.chamadas_estorno}
    corpos = {(c.valor_centavos, c.motivo) for c in pagamentos.chamadas_estorno}
    assert chaves == {f"disputa-{disputa.id}"}
    assert len(corpos) == 1  # corpo idêntico: o replay de Pagamentos devolve o mesmo 201
    assert banco.tipos_de_eventos() == ["disputa.aberta", "disputa.resolvida"]


async def test_tentativas_esgotadas_viram_estorno_falhou(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    saga: SagaEstorno,
    uow: FabricaUnidadeDeTrabalho,
    banco: BancoEmMemoria,
    relogio: RelogioFake,
) -> None:
    pagamentos.programar_estorno(*[FalhaTransitoria("DEPENDENCIA_INDISPONIVEL")] * 10)
    await decidir.executar(disputa.id, PROCEDENTE)
    retentativa = RetentativaDeEstornos(uow, saga, relogio=relogio)
    for _ in range(9):
        relogio.avancar(minutes=10)
        assert await retentativa.processar_lote() == 1
    final = banco.disputas[disputa.id]
    assert final.status is StatusDisputa.ESTORNO_FALHOU
    assert final.tentativas_estorno == 10
    assert final.motivo_falha_estorno == "TENTATIVAS_ESGOTADAS"
    assert banco.tipos_de_eventos()[-1] == "disputa.estorno_falhou"
    relogio.avancar(minutes=10)
    assert await retentativa.processar_lote() == 0


async def test_resultado_atrasado_nao_regride_disputa_ja_resolvida(
    decidir: DecidirDisputa,
    disputa: Disputa,
    pagamentos: PagamentosFake,
    saga: SagaEstorno,
    banco: BancoEmMemoria,
) -> None:
    """Corrida entre PATCH e worker: quem chega depois só lê o estado final."""
    pagamentos.programar_estorno(FalhaTransitoria("DEPENDENCIA_INDISPONIVEL"))
    await decidir.executar(disputa.id, PROCEDENTE)
    await saga.tentar(disputa.id)  # sucesso
    eventos_antes = list(banco.eventos)
    final = await saga._aplicar(disputa.id, FalhaDefinitiva("ATRASADO"))
    assert final.status is StatusDisputa.RESOLVIDA
    assert banco.eventos == eventos_antes
    assert await saga.tentar(disputa.id) == final
    assert len(pagamentos.chamadas_estorno) == 2


async def test_erro_inesperado_numa_disputa_nao_para_o_lote(
    decidir: DecidirDisputa,
    disputa: Disputa,
    uow: FabricaUnidadeDeTrabalho,
    banco: BancoEmMemoria,
    relogio: RelogioFake,
    pagamentos: PagamentosFake,
) -> None:
    pagamentos.programar_estorno(FalhaTransitoria("DEPENDENCIA_INDISPONIVEL"))
    await decidir.executar(disputa.id, PROCEDENTE)

    class SagaQueQuebra(SagaEstorno):
        async def tentar(self, disputa_id: uuid.UUID) -> Disputa:
            raise RuntimeError("bug")

    relogio.avancar(seconds=5)
    retentativa = RetentativaDeEstornos(
        uow, SagaQueQuebra(uow, pagamentos, EmissorTokenFake(), relogio=relogio), relogio=relogio
    )
    assert await retentativa.processar_lote() == 1
    assert banco.disputas[disputa.id].status is StatusDisputa.ESTORNO_PENDENTE
