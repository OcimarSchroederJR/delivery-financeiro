"""Implementações em memória das portas, para testes de unidade e de API."""

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

from avaliacoes.aplicacao.portas import (
    DadosEvento,
    EstornoRealizado,
    FabricaUnidadeDeTrabalho,
    PagamentoExterno,
    PedidoExterno,
    ResultadoEstorno,
    ResumoAvaliacoes,
)
from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import STATUS_NAO_TERMINAIS, Disputa, StatusDisputa
from avaliacoes.dominio.erros import AvaliacaoDuplicada, DisputaJaAberta
from plataforma.erros import ErroDependenciaIndisponivel


def autorizacao(token: str) -> dict[str, str]:
    """Header ``Authorization: Bearer <token>`` para os testes de API."""
    return {"Authorization": f"Bearer {token}"}


class RelogioFake:
    def __init__(self, inicio: datetime | None = None) -> None:
        self.agora = inicio or datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, **duracao: float) -> None:
        self.agora += timedelta(**duracao)


@dataclass
class BancoEmMemoria:
    avaliacoes: dict[uuid.UUID, Avaliacao] = field(default_factory=dict)
    disputas: dict[uuid.UUID, Disputa] = field(default_factory=dict)
    eventos: list[tuple[str, dict[str, str | int | None]]] = field(default_factory=list)
    commits: int = 0

    def tipos_de_eventos(self) -> list[str]:
        return [tipo for tipo, _ in self.eventos]


class RepositorioAvaliacoesEmMemoria:
    def __init__(self, banco: BancoEmMemoria) -> None:
        self._banco = banco

    async def adicionar(self, avaliacao: Avaliacao) -> None:
        if any(a.pedido_id == avaliacao.pedido_id for a in self._banco.avaliacoes.values()):
            raise AvaliacaoDuplicada()
        self._banco.avaliacoes[avaliacao.id] = copy.deepcopy(avaliacao)

    async def obter(self, avaliacao_id: uuid.UUID) -> Avaliacao | None:
        return copy.deepcopy(self._banco.avaliacoes.get(avaliacao_id))

    async def listar(
        self,
        *,
        restaurante_id: str | None,
        pedido_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Avaliacao], int]:
        filtradas = [
            a
            for a in self._banco.avaliacoes.values()
            if (restaurante_id is None or a.restaurante_id == restaurante_id)
            and (pedido_id is None or a.pedido_id == pedido_id)
        ]
        filtradas.sort(key=lambda a: (a.criado_em, str(a.id)), reverse=True)
        pagina = filtradas[deslocamento : deslocamento + limite]
        return copy.deepcopy(pagina), len(filtradas)

    async def resumir(self, restaurante_id: str) -> ResumoAvaliacoes:
        do_restaurante = [
            a for a in self._banco.avaliacoes.values() if a.restaurante_id == restaurante_id
        ]
        notas_entrega = [a.nota_entrega for a in do_restaurante if a.nota_entrega is not None]
        return ResumoAvaliacoes(
            restaurante_id=restaurante_id,
            media_restaurante=(
                round(sum(a.nota_restaurante for a in do_restaurante) / len(do_restaurante), 2)
                if do_restaurante
                else None
            ),
            media_entrega=(
                round(sum(notas_entrega) / len(notas_entrega), 2) if notas_entrega else None
            ),
            total=len(do_restaurante),
        )


class RepositorioDisputasEmMemoria:
    def __init__(self, banco: BancoEmMemoria) -> None:
        self._banco = banco

    async def adicionar(self, disputa: Disputa) -> None:
        if await self.existe_nao_terminal(disputa.pedido_id):
            raise DisputaJaAberta()
        self._banco.disputas[disputa.id] = copy.deepcopy(disputa)

    async def obter(self, disputa_id: uuid.UUID, *, para_atualizar: bool = False) -> Disputa | None:
        return copy.deepcopy(self._banco.disputas.get(disputa_id))

    async def salvar(self, disputa: Disputa) -> None:
        self._banco.disputas[disputa.id] = copy.deepcopy(disputa)

    async def existe_nao_terminal(self, pedido_id: str) -> bool:
        return any(
            d.pedido_id == pedido_id and d.status in STATUS_NAO_TERMINAIS
            for d in self._banco.disputas.values()
        )

    async def listar(
        self,
        *,
        status: StatusDisputa | None,
        cliente_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Disputa], int]:
        filtradas = [
            d
            for d in self._banco.disputas.values()
            if (status is None or d.status is status)
            and (cliente_id is None or d.cliente_id == cliente_id)
        ]
        filtradas.sort(key=lambda d: (d.criado_em, str(d.id)), reverse=True)
        pagina = filtradas[deslocamento : deslocamento + limite]
        return copy.deepcopy(pagina), len(filtradas)

    async def reservar_para_retentativa(
        self, *, agora: datetime, reservar_ate: datetime, limite: int
    ) -> list[uuid.UUID]:
        vencidas = sorted(
            (
                d
                for d in self._banco.disputas.values()
                if d.status is StatusDisputa.ESTORNO_PENDENTE
                and d.proxima_tentativa_em is not None
                and d.proxima_tentativa_em <= agora
            ),
            key=lambda d: (d.proxima_tentativa_em or agora, str(d.id)),
        )[:limite]
        for disputa in vencidas:
            disputa.proxima_tentativa_em = reservar_ate
        return [d.id for d in vencidas]


class UnidadeDeTrabalhoEmMemoria:
    """Sem ``commit()``, o ``__aexit__`` desfaz as mudanças e descarta os eventos."""

    def __init__(self, banco: BancoEmMemoria) -> None:
        self._banco = banco
        self._avaliacoes = RepositorioAvaliacoesEmMemoria(banco)
        self._disputas = RepositorioDisputasEmMemoria(banco)
        self._copia: tuple[dict[uuid.UUID, Avaliacao], dict[uuid.UUID, Disputa]] | None = None
        self._eventos: list[tuple[str, dict[str, str | int | None]]] = []

    @property
    def avaliacoes(self) -> RepositorioAvaliacoesEmMemoria:
        return self._avaliacoes

    @property
    def disputas(self) -> RepositorioDisputasEmMemoria:
        return self._disputas

    async def __aenter__(self) -> Self:
        self._copia = copy.deepcopy((self._banco.avaliacoes, self._banco.disputas))
        self._eventos = []
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        if self._copia is not None:
            self._banco.avaliacoes, self._banco.disputas = self._copia
        self._copia = None
        self._eventos = []

    async def commit(self) -> None:
        self._banco.eventos.extend(self._eventos)
        self._banco.commits += 1
        self._eventos = []
        self._copia = copy.deepcopy((self._banco.avaliacoes, self._banco.disputas))

    def registrar_evento(self, tipo: str, dados: DadosEvento) -> None:
        self._eventos.append((tipo, dict(dados)))


def fabrica_uow_em_memoria(banco: BancoEmMemoria) -> FabricaUnidadeDeTrabalho:
    return lambda: UnidadeDeTrabalhoEmMemoria(banco)


class PedidosFake:
    def __init__(self) -> None:
        self.pedidos: dict[str, PedidoExterno] = {}
        self.indisponivel = False
        self.tokens_recebidos: list[str] = []

    def adicionar(
        self,
        pedido_id: str,
        *,
        cliente_id: str = "cliente-1",
        restaurante_id: str = "rest-1",
        entregue: bool = True,
    ) -> PedidoExterno:
        pedido = PedidoExterno(
            id=pedido_id, cliente_id=cliente_id, restaurante_id=restaurante_id, entregue=entregue
        )
        self.pedidos[pedido_id] = pedido
        return pedido

    async def obter(self, pedido_id: str, *, token: str) -> PedidoExterno | None:
        self.tokens_recebidos.append(token)
        if self.indisponivel:
            raise ErroDependenciaIndisponivel("pedidos")
        return self.pedidos.get(pedido_id)


@dataclass(frozen=True, slots=True)
class ChamadaEstorno:
    pagamento_id: str
    valor_centavos: int
    motivo: str
    chave_idempotencia: str
    token: str


class PagamentosFake:
    def __init__(self) -> None:
        self.pagamentos: list[PagamentoExterno] = []
        self.indisponivel = False
        self.resultados_estorno: list[ResultadoEstorno] = []
        self.chamadas_estorno: list[ChamadaEstorno] = []
        self.tokens_listagem: list[str] = []

    def adicionar(
        self,
        pedido_id: str,
        *,
        cliente_id: str = "cliente-1",
        valor_centavos: int = 3200,
        status: str = "aprovado",
        pagamento_id: str | None = None,
    ) -> PagamentoExterno:
        pagamento = PagamentoExterno(
            id=pagamento_id or f"pag-{len(self.pagamentos) + 1}",
            pedido_id=pedido_id,
            cliente_id=cliente_id,
            valor_centavos=valor_centavos,
            status=status,
        )
        self.pagamentos.append(pagamento)
        return pagamento

    def programar_estorno(self, *resultados: ResultadoEstorno) -> None:
        """Próximas respostas de ``estornar``; depois delas, sempre sucesso."""
        self.resultados_estorno.extend(resultados)

    async def listar_por_pedido(self, pedido_id: str, *, token: str) -> list[PagamentoExterno]:
        self.tokens_listagem.append(token)
        if self.indisponivel:
            raise ErroDependenciaIndisponivel("pagamentos")
        return [p for p in self.pagamentos if p.pedido_id == pedido_id]

    async def estornar(
        self,
        pagamento_id: str,
        *,
        valor_centavos: int,
        motivo: str,
        chave_idempotencia: str,
        token: str,
    ) -> ResultadoEstorno:
        self.chamadas_estorno.append(
            ChamadaEstorno(pagamento_id, valor_centavos, motivo, chave_idempotencia, token)
        )
        if self.resultados_estorno:
            return self.resultados_estorno.pop(0)
        return EstornoRealizado(estorno_id=f"est-{len(self.chamadas_estorno)}")


class EmissorTokenFake:
    def __init__(self, valor: str = "token-de-servico-fake") -> None:
        self.token = valor

    def emitir(self) -> str:
        return self.token
