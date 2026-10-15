"""Execução de processos de worker com encerramento gracioso (SIGTERM/SIGINT)."""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable

SINAIS_DE_PARADA = (signal.SIGTERM, signal.SIGINT)


async def executar_ate_sinal(principal: Callable[[asyncio.Event], Awaitable[None]]) -> None:
    """Executa ``principal(parar)``; SIGTERM/SIGINT ligam ``parar``.

    ``principal`` deve sair do laço quando ``parar`` estiver ligado, concluindo
    o trabalho em andamento (spec §5, Shutdown).
    """
    parar = asyncio.Event()
    laco = asyncio.get_running_loop()
    for sinal in SINAIS_DE_PARADA:
        with contextlib.suppress(NotImplementedError):  # Windows não suporta
            laco.add_signal_handler(sinal, parar.set)
    try:
        await principal(parar)
    finally:
        for sinal in SINAIS_DE_PARADA:
            with contextlib.suppress(NotImplementedError):
                laco.remove_signal_handler(sinal)
