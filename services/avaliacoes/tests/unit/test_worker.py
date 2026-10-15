import asyncio

from avaliacoes.aplicacao.saga import RetentativaDeEstornos
from avaliacoes.worker import executar_retentativas


class RetentativaFake(RetentativaDeEstornos):
    def __init__(self, resultados: list[int | Exception]) -> None:
        self.resultados = resultados
        self.chamadas = 0

    async def processar_lote(self) -> int:
        self.chamadas += 1
        resultado = self.resultados.pop(0) if self.resultados else 0
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


async def test_laco_drena_sem_esperar_e_sobrevive_a_erros() -> None:
    retentativa = RetentativaFake([2, 1, RuntimeError("banco fora"), 0])
    parar = asyncio.Event()
    tarefa = asyncio.create_task(executar_retentativas(retentativa, parar, intervalo=0.01))
    for _ in range(100):
        if retentativa.chamadas >= 4:
            break
        await asyncio.sleep(0.01)
    parar.set()
    await asyncio.wait_for(tarefa, timeout=1)
    assert retentativa.chamadas >= 4
