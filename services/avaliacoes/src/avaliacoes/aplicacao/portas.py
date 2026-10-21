"""Portas (Protocols) que a aplicação usa e os adaptadores implementam."""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import Disputa, StatusDisputa

Relogio = Callable[[], datetime]
DadosEvento = Mapping[str, str | int | None]


@dataclass(frozen=True, slots=True)
class Solicitante:
    """Quem faz a requisição (vem do token, já validado pelo adaptador HTTP)."""

    id: str
    token: str
    admin: bool = False


@dataclass(frozen=True, slots=True)
class ResumoAvaliacoes:
    restaurante_id: str
    media_restaurante: float | None
    media_entrega: float | None
    total: int


class RepositorioAvaliacoes(Protocol):
    async def adicionar(self, avaliacao: Avaliacao) -> None:
        """Levanta ``AvaliacaoDuplicada`` se o pedido já tem avaliação."""
        ...

    async def obter(self, avaliacao_id: uuid.UUID) -> Avaliacao | None: ...

    async def listar(
        self,
        *,
        restaurante_id: str | None,
        pedido_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Avaliacao], int]: ...

    async def resumir(self, restaurante_id: str) -> ResumoAvaliacoes: ...


class RepositorioDisputas(Protocol):
    async def adicionar(self, disputa: Disputa) -> None:
        """Levanta ``DisputaJaAberta`` se o pedido já tem disputa não-terminal."""
        ...

    async def obter(
        self, disputa_id: uuid.UUID, *, para_atualizar: bool = False
    ) -> Disputa | None: ...

    async def salvar(self, disputa: Disputa) -> None: ...

    async def existe_nao_terminal(self, pedido_id: str) -> bool: ...

    async def listar(
        self,
        *,
        status: StatusDisputa | None,
        cliente_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Disputa], int]: ...

    async def reservar_para_retentativa(
        self, *, agora: datetime, reservar_ate: datetime, limite: int
    ) -> list[uuid.UUID]:
        """Disputas ``estorno_pendente`` vencidas; adia cada uma para ``reservar_ate``."""
        ...


class UnidadeDeTrabalho(Protocol):
    """Transação: nada é gravado (nem eventos) sem ``commit()``."""

    @property
    def avaliacoes(self) -> RepositorioAvaliacoes: ...

    @property
    def disputas(self) -> RepositorioDisputas: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    def registrar_evento(self, tipo: str, dados: DadosEvento) -> None:
        """Coloca o evento no outbox, na mesma transação."""
        ...


FabricaUnidadeDeTrabalho = Callable[[], UnidadeDeTrabalho]


@dataclass(frozen=True, slots=True)
class PedidoExterno:
    id: str
    cliente_id: str
    restaurante_id: str
    entregue: bool


class PortaPedidos(Protocol):
    async def obter(self, pedido_id: str, *, token: str) -> PedidoExterno | None:
        """``None`` se o pedido não existe. Eq. 3 fora: ``ErroDependenciaIndisponivel``."""
        ...


@dataclass(frozen=True, slots=True)
class PagamentoExterno:
    id: str
    pedido_id: str
    cliente_id: str
    valor_centavos: int
    status: str


@dataclass(frozen=True, slots=True)
class EstornoRealizado:
    estorno_id: str


@dataclass(frozen=True, slots=True)
class FalhaTransitoria:
    motivo: str


@dataclass(frozen=True, slots=True)
class FalhaDefinitiva:
    motivo: str


ResultadoEstorno = EstornoRealizado | FalhaTransitoria | FalhaDefinitiva


class PortaPagamentos(Protocol):
    async def listar_por_pedido(self, pedido_id: str, *, token: str) -> list[PagamentoExterno]:
        """Todos os pagamentos do pedido. Pagamentos fora: ``ErroDependenciaIndisponivel``."""
        ...

    async def estornar(
        self,
        pagamento_id: str,
        *,
        valor_centavos: int,
        motivo: str,
        chave_idempotencia: str,
        token: str,
    ) -> ResultadoEstorno:
        """Nunca levanta por falha HTTP: classifica em sucesso, transitória ou definitiva."""
        ...


class EmissorDeToken(Protocol):
    def emitir(self) -> str: ...
