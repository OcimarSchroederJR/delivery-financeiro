"""Portas (Protocols) que os adaptadores implementam."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.idempotencia import RegistroIdempotencia
from pagamentos.dominio.pagamento import Estorno, MetodoPagamento, Pagamento, StatusPagamento
from pagamentos.dominio.pedido import Pedido
from plataforma.erros import ErroAplicacao

Relogio = Callable[[], datetime]
GeradorDeId = Callable[[], UUID]


class RepositorioPagamentos(Protocol):
    async def adicionar(self, pagamento: Pagamento) -> None:
        """Insere. Levanta ``PedidoJaPago`` se o pedido já tem pagamento efetivado."""
        ...

    async def obter(self, pagamento_id: UUID, *, para_atualizar: bool = False) -> Pagamento | None:
        """Com ``para_atualizar=True`` trava a linha até o fim da transação."""
        ...

    async def existe_efetivado(self, pedido_id: str) -> bool: ...

    async def listar(
        self, *, pedido_id: str | None, cliente_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Pagamento], int]:
        """Mais recentes primeiro. Retorna (página, total sem paginação)."""
        ...

    async def salvar(self, pagamento: Pagamento) -> None:
        """Persiste status, ``atualizado_em`` e estornos novos de um pagamento existente."""
        ...


class RepositorioChavesIdempotencia(Protocol):
    async def obter(
        self, escopo: str, chave: str, *, para_atualizar: bool = False
    ) -> RegistroIdempotencia | None: ...

    async def reservar(self, registro: RegistroIdempotencia) -> None:
        """INSERT protegido pela PK (escopo, chave); concorrente -> IdempotencyEmProcessamento."""
        ...

    async def substituir(self, registro: RegistroIdempotencia) -> None:
        """Reaproveita uma chave expirada ou abandonada com uma nova reserva (dono novo)."""
        ...

    async def concluir(
        self,
        escopo: str,
        chave: str,
        dono: UUID,
        *,
        status_resposta: int,
        corpo_resposta: Mapping[str, Any],
    ) -> bool:
        """Grava a resposta se a reserva ainda é deste ``dono`` e está em processamento.

        Retorna ``False`` (sem alterar nada) se a chave foi reassumida por outro dono
        ou já está concluída.
        """
        ...

    async def remover(self, escopo: str, chave: str, dono: UUID) -> None:
        """Libera a reserva deste ``dono`` se ainda estiver ``em_processamento``.

        Chave concluída nunca é removida (a conclusão é gravada na transação do efeito)
        e a reserva de outro dono (reassumida) também não.
        """
        ...

    async def remover_expiradas(self, antes_de: datetime) -> int: ...


class RegistroDeEventos(Protocol):
    def registrar(self, tipo: str, dados: Mapping[str, Any]) -> None:
        """Grava o evento no outbox, na transação da unidade de trabalho."""
        ...


class UnidadeDeTrabalho(Protocol):
    """Transação: sem ``commit()`` explícito, tudo é desfeito na saída do ``async with``."""

    @property
    def pagamentos(self) -> RepositorioPagamentos: ...

    @property
    def chaves_idempotencia(self) -> RepositorioChavesIdempotencia: ...

    @property
    def eventos(self) -> RegistroDeEventos: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


FabricaUnidadeDeTrabalho = Callable[[], UnidadeDeTrabalho]


class ConsultaPedidos(Protocol):
    async def obter(self, pedido_id: str, *, token: str) -> Pedido | None:
        """``None`` se não existe. Falha da Eq. 3 -> ``ErroDependenciaIndisponivel``."""
        ...


@dataclass(frozen=True, slots=True)
class ResultadoAutorizacao:
    aprovado: bool
    motivo_recusa: str | None = None


class GatewayDePagamento(Protocol):
    async def autorizar(
        self, *, metodo: MetodoPagamento, valor_centavos: int, cartao: DadosCartao | None
    ) -> ResultadoAutorizacao:
        """Timeout -> ``ErroDependenciaIndisponivel("gateway")``."""
        ...


class Apresentador(Protocol):
    """Converte resultados no corpo HTTP gravado na idempotência."""

    def pagamento(self, pagamento: Pagamento) -> dict[str, Any]: ...

    def estorno(self, estorno: Estorno, status_pagamento: StatusPagamento) -> dict[str, Any]:
        """Corpo do 201 do estorno: inclui o ``status`` do pagamento após o estorno."""
        ...

    def erro(self, erro: ErroAplicacao) -> dict[str, Any]: ...
