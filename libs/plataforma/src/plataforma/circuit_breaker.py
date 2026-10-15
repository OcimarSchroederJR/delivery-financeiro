"""Circuit breaker por dependência (spec §5).

Abre após ``limite_falhas`` falhas consecutivas; depois de ``tempo_recuperacao``
segundos fica meio-aberto e deixa passar UMA chamada de teste. Sucesso fecha;
falha reabre. Aberto → ``CircuitoAberto`` (503 DEPENDENCIA_INDISPONIVEL) imediato.
"""

import time
from collections.abc import Awaitable, Callable
from enum import StrEnum

from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import obter_logger

_log = obter_logger(__name__)


class EstadoCircuito(StrEnum):
    FECHADO = "fechado"
    ABERTO = "aberto"
    MEIO_ABERTO = "meio_aberto"


class CircuitoAberto(ErroDependenciaIndisponivel):
    def __init__(self, dependencia: str) -> None:
        super().__init__(
            dependencia,
            f"A dependência '{dependencia}' está indisponível (circuito aberto).",
        )


def _toda_excecao_e_falha(_erro: Exception) -> bool:
    return True


class CircuitBreaker:
    def __init__(
        self,
        dependencia: str,
        *,
        limite_falhas: int = 5,
        tempo_recuperacao: float = 30.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.dependencia = dependencia
        self._limite = limite_falhas
        self._recuperacao = tempo_recuperacao
        self._relogio = relogio
        self._falhas = 0
        self._aberto_em: float | None = None
        self._teste_em_andamento = False

    @property
    def estado(self) -> EstadoCircuito:
        if self._aberto_em is None:
            return EstadoCircuito.FECHADO
        if self._relogio() - self._aberto_em >= self._recuperacao:
            return EstadoCircuito.MEIO_ABERTO
        return EstadoCircuito.ABERTO

    def antes_da_chamada(self) -> None:
        """Levanta ``CircuitoAberto`` se a chamada não deve sair."""
        estado = self.estado
        if estado is EstadoCircuito.ABERTO:
            raise CircuitoAberto(self.dependencia)
        if estado is EstadoCircuito.MEIO_ABERTO:
            if self._teste_em_andamento:
                raise CircuitoAberto(self.dependencia)
            self._teste_em_andamento = True

    def registrar_sucesso(self) -> None:
        if self._aberto_em is not None:
            _log.info("circuito_fechado", dependencia=self.dependencia)
        self._falhas = 0
        self._aberto_em = None
        self._teste_em_andamento = False

    def registrar_falha(self) -> None:
        self._teste_em_andamento = False
        if self._aberto_em is not None:
            self._aberto_em = self._relogio()
            _log.warning("circuito_reaberto", dependencia=self.dependencia)
            return
        self._falhas += 1
        if self._falhas >= self._limite:
            self._aberto_em = self._relogio()
            _log.warning("circuito_aberto", dependencia=self.dependencia, falhas=self._falhas)

    async def executar[T](
        self,
        operacao: Callable[[], Awaitable[T]],
        *,
        e_falha: Callable[[Exception], bool] = _toda_excecao_e_falha,
    ) -> T:
        """Executa ``operacao`` sob o circuito. Exceções para as quais ``e_falha``
        retorna False contam como sucesso da dependência (ex.: respostas 4xx)."""
        chamada_de_teste = self.estado is EstadoCircuito.MEIO_ABERTO
        self.antes_da_chamada()
        try:
            resultado = await operacao()
        except Exception as erro:
            if e_falha(erro):
                self.registrar_falha()
            else:
                self.registrar_sucesso()
            raise
        except BaseException:
            # Cancelamento: só libera a vaga de teste se ESTA era a chamada de teste.
            if chamada_de_teste:
                self._teste_em_andamento = False
            raise
        self.registrar_sucesso()
        return resultado
