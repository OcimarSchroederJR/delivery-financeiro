import asyncio
from datetime import timedelta

from pagamentos.aplicacao.idempotencia import remover_chaves_expiradas
from pagamentos.aplicacao.portas import UnidadeDeTrabalho
from pagamentos.dominio.idempotencia import RegistroIdempotencia
from pagamentos.testes.fakes import INSTANTE, EstadoFake, RelogioFake, fabrica_fake
from pagamentos.worker import limpar_periodicamente


def _semear(estado: EstadoFake, chave: str, idade: timedelta) -> None:
    estado.chaves[("e", chave)] = RegistroIdempotencia.reservar(
        escopo="e", chave=chave, hash_requisicao="h", agora=INSTANTE - idade
    )


async def test_remove_so_as_chaves_com_mais_de_24h() -> None:
    estado = EstadoFake()
    _semear(estado, "velha", timedelta(hours=24, seconds=1))
    _semear(estado, "nova", timedelta(hours=23))
    assert await remover_chaves_expiradas(fabrica_fake(estado), agora=INSTANTE) == 1
    assert list(estado.chaves) == [("e", "nova")]
    assert estado.commits == 1


async def test_limpeza_periodica_roda_ate_o_sinal_de_parada() -> None:
    estado = EstadoFake()
    _semear(estado, "velha", timedelta(days=2))
    parar = asyncio.Event()
    tarefa = asyncio.create_task(
        limpar_periodicamente(fabrica_fake(estado), parar, intervalo=0.01, relogio=RelogioFake())
    )
    for _ in range(100):
        if not estado.chaves:
            break
        await asyncio.sleep(0.01)
    parar.set()
    await asyncio.wait_for(tarefa, timeout=1)
    assert estado.chaves == {}


async def test_falha_na_limpeza_nao_derruba_o_laco() -> None:
    chamadas = 0

    def fabrica() -> UnidadeDeTrabalho:
        nonlocal chamadas
        chamadas += 1
        raise RuntimeError("banco fora")

    parar = asyncio.Event()
    tarefa = asyncio.create_task(limpar_periodicamente(fabrica, parar, intervalo=0.01))
    for _ in range(100):
        if chamadas >= 2:
            break
        await asyncio.sleep(0.01)
    parar.set()
    await asyncio.wait_for(tarefa, timeout=1)
    assert chamadas >= 2
