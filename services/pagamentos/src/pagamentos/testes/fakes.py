"""Fakes em memória das portas, usados pelos testes de unidade e de API.

Ficam em ``src`` (como ``plataforma.testes``) porque os testes rodam com
``--import-mode=importlib`` e porque assim o ``mypy --strict`` confere que cada
fake implementa a porta correspondente.
"""

import asyncio
import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID, uuid4

from pagamentos.aplicacao.portas import FabricaUnidadeDeTrabalho, ResultadoAutorizacao
from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.erros import IdempotencyEmProcessamento, PedidoJaPago
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave
from pagamentos.dominio.pagamento import Estorno, MetodoPagamento, Pagamento, StatusPagamento
from pagamentos.dominio.pedido import Pedido
from plataforma.erros import ErroAplicacao, ErroDependenciaIndisponivel

INSTANTE = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)

PEDIDOS_PADRAO: tuple[Pedido, ...] = (
    Pedido("ped-1", "cliente-1", 4590, "confirmado"),
    Pedido("ped-2", "cliente-1", 600_000, "confirmado"),
    Pedido("ped-3", "cliente-2", 2590, "entregue"),
    Pedido("ped-4", "cliente-1", 3200, "entregue"),
)


def pagamento_aprovado(
    *,
    pedido_id: str = "ped-1",
    cliente_id: str = "cliente-1",
    valor_centavos: int = 4590,
    metodo: MetodoPagamento = MetodoPagamento.PIX,
    agora: datetime = INSTANTE,
) -> Pagamento:
    return Pagamento.aprovado(
        id=uuid4(),
        pedido_id=pedido_id,
        cliente_id=cliente_id,
        valor_centavos=valor_centavos,
        metodo=metodo,
        cartao_final="0000" if metodo == MetodoPagamento.CARTAO_CREDITO else None,
        agora=agora,
    )


def pagamento_recusado(
    *, pedido_id: str = "ped-1", cliente_id: str = "cliente-1", motivo: str = "saldo_insuficiente"
) -> Pagamento:
    return Pagamento.recusado(
        id=uuid4(),
        pedido_id=pedido_id,
        cliente_id=cliente_id,
        valor_centavos=4590,
        metodo=MetodoPagamento.CARTAO_CREDITO,
        cartao_final="0002",
        motivo=motivo,
        agora=INSTANTE,
    )


@dataclass
class EstadoFake:
    pagamentos: dict[UUID, Pagamento] = field(default_factory=dict)
    chaves: dict[tuple[str, str], RegistroIdempotencia] = field(default_factory=dict)
    eventos: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    commits: int = 0


class RepositorioPagamentosFake:
    def __init__(self, estado: EstadoFake) -> None:
        self._estado = estado

    async def adicionar(self, pagamento: Pagamento) -> None:
        if pagamento.efetivado and await self.existe_efetivado(pagamento.pedido_id):
            raise PedidoJaPago()
        self._estado.pagamentos[pagamento.id] = pagamento

    async def obter(self, pagamento_id: UUID, *, para_atualizar: bool = False) -> Pagamento | None:
        return self._estado.pagamentos.get(pagamento_id)

    async def existe_efetivado(self, pedido_id: str) -> bool:
        return any(
            p.pedido_id == pedido_id and p.efetivado for p in self._estado.pagamentos.values()
        )

    async def listar(
        self, *, pedido_id: str | None, cliente_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Pagamento], int]:
        filtrados = [
            p
            for p in self._estado.pagamentos.values()
            if (pedido_id is None or p.pedido_id == pedido_id)
            and (cliente_id is None or p.cliente_id == cliente_id)
        ]
        filtrados.sort(key=lambda p: (p.criado_em, str(p.id)), reverse=True)
        return filtrados[deslocamento : deslocamento + limite], len(filtrados)

    async def salvar(self, pagamento: Pagamento) -> None:
        self._estado.pagamentos[pagamento.id] = pagamento


class RepositorioChavesIdempotenciaFake:
    def __init__(self, estado: EstadoFake) -> None:
        self._estado = estado

    async def obter(
        self, escopo: str, chave: str, *, para_atualizar: bool = False
    ) -> RegistroIdempotencia | None:
        return self._estado.chaves.get((escopo, chave))

    async def reservar(self, registro: RegistroIdempotencia) -> None:
        if (registro.escopo, registro.chave) in self._estado.chaves:
            raise IdempotencyEmProcessamento()
        self._estado.chaves[(registro.escopo, registro.chave)] = registro

    async def substituir(self, registro: RegistroIdempotencia) -> None:
        self._estado.chaves[(registro.escopo, registro.chave)] = registro

    async def concluir(
        self, escopo: str, chave: str, *, status_resposta: int, corpo_resposta: Mapping[str, Any]
    ) -> None:
        registro = self._estado.chaves.get((escopo, chave))
        if registro is not None and registro.status == StatusChave.EM_PROCESSAMENTO:
            registro.status = StatusChave.CONCLUIDA
            registro.status_resposta = status_resposta
            registro.corpo_resposta = dict(corpo_resposta)

    async def remover(self, escopo: str, chave: str) -> None:
        registro = self._estado.chaves.get((escopo, chave))
        if registro is not None and registro.status == StatusChave.EM_PROCESSAMENTO:
            del self._estado.chaves[(escopo, chave)]

    async def remover_expiradas(self, antes_de: datetime) -> int:
        expiradas = [k for k, r in self._estado.chaves.items() if r.criado_em < antes_de]
        for k in expiradas:
            del self._estado.chaves[k]
        return len(expiradas)


class RegistroDeEventosFake:
    def __init__(self, estado: EstadoFake) -> None:
        self._estado = estado

    def registrar(self, tipo: str, dados: Mapping[str, Any]) -> None:
        self._estado.eventos.append((tipo, dict(dados)))


class UnidadeDeTrabalhoFake:
    """Rollback real: guarda uma cópia do estado na entrada e a restaura sem commit."""

    def __init__(self, estado: EstadoFake) -> None:
        self._estado = estado
        self._copia: tuple[
            dict[UUID, Pagamento],
            dict[tuple[str, str], RegistroIdempotencia],
            list[tuple[str, dict[str, Any]]],
        ] = ({}, {}, [])
        self._confirmada = False
        self.pagamentos = RepositorioPagamentosFake(estado)
        self.chaves_idempotencia = RepositorioChavesIdempotenciaFake(estado)
        self.eventos = RegistroDeEventosFake(estado)

    async def __aenter__(self) -> Self:
        self._copia = copy.deepcopy(
            (self._estado.pagamentos, self._estado.chaves, self._estado.eventos)
        )
        self._confirmada = False
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        if not self._confirmada:
            self._estado.pagamentos, self._estado.chaves, self._estado.eventos = self._copia

    async def commit(self) -> None:
        self._confirmada = True
        self._estado.commits += 1


def fabrica_fake(estado: EstadoFake) -> FabricaUnidadeDeTrabalho:
    return lambda: UnidadeDeTrabalhoFake(estado)


class ConsultaPedidosFake:
    def __init__(self, pedidos: tuple[Pedido, ...] = PEDIDOS_PADRAO) -> None:
        self.pedidos: dict[str, Pedido] = {pedido.id: pedido for pedido in pedidos}
        self.fora = False
        self.chamadas: list[tuple[str, str]] = []

    def adicionar(self, pedido: Pedido) -> None:
        self.pedidos[pedido.id] = pedido

    async def obter(self, pedido_id: str, *, token: str) -> Pedido | None:
        self.chamadas.append((pedido_id, token))
        if self.fora:
            raise ErroDependenciaIndisponivel("pedidos")
        return self.pedidos.get(pedido_id)


class ApresentadorFake:
    def pagamento(self, pagamento: Pagamento) -> dict[str, Any]:
        return {"id": str(pagamento.id), "status": pagamento.status.value}

    def estorno(self, estorno: Estorno, status_pagamento: StatusPagamento) -> dict[str, Any]:
        return {
            "id": str(estorno.id),
            "valor_centavos": estorno.valor_centavos,
            "status": status_pagamento.value,
        }

    def erro(self, erro: ErroAplicacao) -> dict[str, Any]:
        return {**erro.detalhes, "erro": True, "codigo": erro.codigo, "mensagem": erro.mensagem}


class RelogioFake:
    def __init__(self, agora: datetime = INSTANTE) -> None:
        self.agora = agora

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, delta: timedelta) -> None:
        self.agora += delta


class GatewayComBarreira:
    """Aprova, mas só depois de ``liberar.set()``; permite simular concorrência."""

    def __init__(self, esperadas: int) -> None:
        self.liberar = asyncio.Event()
        self.entradas = 0
        self._esperadas = esperadas
        self._todas = asyncio.Event()

    async def autorizar(
        self, *, metodo: MetodoPagamento, valor_centavos: int, cartao: DadosCartao | None
    ) -> ResultadoAutorizacao:
        self.entradas += 1
        if self.entradas >= self._esperadas:
            self._todas.set()
        await self.liberar.wait()
        return ResultadoAutorizacao(aprovado=True)

    async def aguardar_entradas(self, limite_segundos: float = 5.0) -> None:
        await asyncio.wait_for(self._todas.wait(), timeout=limite_segundos)


if TYPE_CHECKING:  # o mypy confere que os fakes implementam as portas
    from pagamentos.aplicacao.portas import Apresentador, ConsultaPedidos, GatewayDePagamento

    def _conferir_tipos() -> None:
        _pedidos: ConsultaPedidos = ConsultaPedidosFake()
        _apresentador: Apresentador = ApresentadorFake()
        _gateway: GatewayDePagamento = GatewayComBarreira(1)
