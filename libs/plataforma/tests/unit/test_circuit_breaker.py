import asyncio

import pytest

from plataforma.circuit_breaker import CircuitBreaker, CircuitoAberto, EstadoCircuito


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


async def _falhar() -> None:
    raise ConnectionError("fora do ar")


async def _ok() -> str:
    return "ok"


async def _abrir(breaker: CircuitBreaker, vezes: int = 5) -> None:
    for _ in range(vezes):
        with pytest.raises(ConnectionError):
            await breaker.executar(_falhar)


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def breaker(relogio: Relogio) -> CircuitBreaker:
    return CircuitBreaker("pedidos", limite_falhas=5, tempo_recuperacao=30.0, relogio=relogio)


async def test_abre_apos_5_falhas_consecutivas(breaker: CircuitBreaker) -> None:
    await _abrir(breaker, 4)
    assert breaker.estado is EstadoCircuito.FECHADO
    await _abrir(breaker, 1)
    assert breaker.estado is EstadoCircuito.ABERTO
    with pytest.raises(CircuitoAberto) as erro:
        await breaker.executar(_ok)
    assert erro.value.status_http == 503
    assert erro.value.codigo == "DEPENDENCIA_INDISPONIVEL"


async def test_sucesso_zera_contagem(breaker: CircuitBreaker) -> None:
    await _abrir(breaker, 4)
    assert await breaker.executar(_ok) == "ok"
    await _abrir(breaker, 4)
    assert breaker.estado is EstadoCircuito.FECHADO


async def test_meio_aberto_apos_30s_e_fecha_com_sucesso(
    breaker: CircuitBreaker, relogio: Relogio
) -> None:
    await _abrir(breaker)
    relogio.agora += 30
    assert breaker.estado is EstadoCircuito.MEIO_ABERTO
    assert await breaker.executar(_ok) == "ok"
    assert breaker.estado is EstadoCircuito.FECHADO


async def test_meio_aberto_reabre_com_falha(breaker: CircuitBreaker, relogio: Relogio) -> None:
    await _abrir(breaker)
    relogio.agora += 30
    with pytest.raises(ConnectionError):
        await breaker.executar(_falhar)
    assert breaker.estado is EstadoCircuito.ABERTO


async def test_meio_aberto_deixa_passar_so_uma_chamada(
    breaker: CircuitBreaker, relogio: Relogio
) -> None:
    await _abrir(breaker)
    relogio.agora += 30
    liberar = asyncio.Event()

    async def lenta() -> str:
        await liberar.wait()
        return "ok"

    teste = asyncio.create_task(breaker.executar(lenta))
    await asyncio.sleep(0)
    with pytest.raises(CircuitoAberto):
        await breaker.executar(_ok)
    liberar.set()
    assert await teste == "ok"


async def test_cancelamento_no_meio_aberto_nao_trava_o_circuito(
    breaker: CircuitBreaker, relogio: Relogio
) -> None:
    await _abrir(breaker)
    relogio.agora += 30

    async def eterna() -> str:
        await asyncio.Event().wait()
        return "nunca"

    tarefa = asyncio.create_task(breaker.executar(eterna))
    await asyncio.sleep(0)
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert await breaker.executar(_ok) == "ok"


async def test_excecao_que_nao_e_falha_conta_como_sucesso(breaker: CircuitBreaker) -> None:
    async def nao_encontrado() -> None:
        raise LookupError("404")

    await _abrir(breaker, 4)
    with pytest.raises(LookupError):
        await breaker.executar(nao_encontrado, e_falha=lambda _erro: False)
    await _abrir(breaker, 4)
    assert breaker.estado is EstadoCircuito.FECHADO


async def test_cancelar_chamada_antiga_nao_libera_segunda_chamada_de_teste(
    breaker: CircuitBreaker, relogio: Relogio
) -> None:
    async def eterna() -> str:
        await asyncio.Event().wait()
        return "nunca"

    antiga = asyncio.create_task(breaker.executar(eterna))  # começou com o circuito FECHADO
    await asyncio.sleep(0)
    await _abrir(breaker)
    relogio.agora += 30
    teste = asyncio.create_task(breaker.executar(eterna))  # a chamada de teste do meio-aberto
    await asyncio.sleep(0)

    antiga.cancel()
    with pytest.raises(asyncio.CancelledError):
        await antiga
    with pytest.raises(CircuitoAberto):
        await breaker.executar(_ok)

    teste.cancel()
    with pytest.raises(asyncio.CancelledError):
        await teste
    assert await breaker.executar(_ok) == "ok"
