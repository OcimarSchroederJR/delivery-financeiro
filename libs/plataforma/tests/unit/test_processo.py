import asyncio
import os
import signal

import pytest

from plataforma.processo import executar_ate_sinal


async def test_executar_ate_sinal_executa_principal() -> None:
    chamado: list[bool] = []

    async def principal(parar: asyncio.Event) -> None:
        chamado.append(not parar.is_set())

    await executar_ate_sinal(principal)
    assert chamado == [True]


@pytest.mark.skipif(os.name == "nt", reason="add_signal_handler não existe no Windows")
async def test_executar_ate_sinal_liga_parar_no_sigterm() -> None:
    async def principal(parar: asyncio.Event) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(parar.wait(), timeout=2)

    await executar_ate_sinal(principal)
