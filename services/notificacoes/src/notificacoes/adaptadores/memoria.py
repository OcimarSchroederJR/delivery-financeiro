"""Adaptadores em memória: Unit of Work transacional e dublês das portas externas.

Usados nos testes de unidade e de API. A UoW trabalha numa cópia do
armazenamento e só a publica no ``commit`` (mesma semântica da UoW SQL).
"""

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from notificacoes.aplicacao.portas import (
    FabricaUow,
    FalhaNoEnvioDeEmail,
    Perfil,
    PerfilNaoEncontrado,
    ResultadoEntrega,
    UnidadeDeTrabalho,
)
from notificacoes.aplicacao.tarefas import Tarefa
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.notificacao import Notificacao
from plataforma.envelope import EnvelopeEvento
from plataforma.erros import ErroDependenciaIndisponivel


@dataclass
class ArmazenamentoEmMemoria:
    notificacoes: dict[uuid.UUID, Notificacao] = field(default_factory=dict)
    assinaturas: dict[uuid.UUID, AssinaturaWebhook] = field(default_factory=dict)
    entregas: list[EntregaWebhook] = field(default_factory=list)
    inbox: set[uuid.UUID] = field(default_factory=set)
    tarefas: list[Tarefa] = field(default_factory=list)
    eventos_externos: dict[uuid.UUID, EnvelopeEvento] = field(default_factory=dict)
    commits: int = 0


def _fatia[T](itens: list[T], deslocamento: int, limite: int) -> tuple[list[T], int]:
    return itens[deslocamento : deslocamento + limite], len(itens)


class RepositorioNotificacoesEmMemoria:
    def __init__(self, dados: ArmazenamentoEmMemoria) -> None:
        self._dados = dados

    async def adicionar(self, notificacao: Notificacao) -> None:
        self._dados.notificacoes[notificacao.id] = notificacao

    async def obter_para_atualizar(self, notificacao_id: uuid.UUID) -> Notificacao | None:
        return self._dados.notificacoes.get(notificacao_id)

    async def atualizar(self, notificacao: Notificacao) -> None:
        self._dados.notificacoes[notificacao.id] = notificacao

    async def listar(
        self, *, destinatario_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Notificacao], int]:
        itens = sorted(
            (
                notificacao
                for notificacao in self._dados.notificacoes.values()
                if destinatario_id is None or notificacao.destinatario_id == destinatario_id
            ),
            key=lambda notificacao: notificacao.criado_em,
            reverse=True,
        )
        return _fatia(itens, deslocamento, limite)


class RepositorioAssinaturasEmMemoria:
    def __init__(self, dados: ArmazenamentoEmMemoria) -> None:
        self._dados = dados

    async def adicionar(self, assinatura: AssinaturaWebhook) -> None:
        self._dados.assinaturas[assinatura.id] = assinatura

    async def obter(self, assinatura_id: uuid.UUID) -> AssinaturaWebhook | None:
        return self._dados.assinaturas.get(assinatura_id)

    async def atualizar(self, assinatura: AssinaturaWebhook) -> None:
        self._dados.assinaturas[assinatura.id] = assinatura

    async def listar(
        self, *, criado_por: str | None, deslocamento: int, limite: int
    ) -> tuple[list[AssinaturaWebhook], int]:
        itens = sorted(
            (
                assinatura
                for assinatura in self._dados.assinaturas.values()
                if assinatura.ativa and (criado_por is None or assinatura.criado_por == criado_por)
            ),
            key=lambda assinatura: assinatura.criado_em,
            reverse=True,
        )
        return _fatia(itens, deslocamento, limite)

    async def listar_ativas(self) -> list[AssinaturaWebhook]:
        return [assinatura for assinatura in self._dados.assinaturas.values() if assinatura.ativa]


class RepositorioEntregasEmMemoria:
    def __init__(self, dados: ArmazenamentoEmMemoria) -> None:
        self._dados = dados

    async def adicionar(self, entrega: EntregaWebhook) -> None:
        self._dados.entregas.append(entrega)

    async def listar(
        self, assinatura_id: uuid.UUID, *, deslocamento: int, limite: int
    ) -> tuple[list[EntregaWebhook], int]:
        itens = sorted(
            (entrega for entrega in self._dados.entregas if entrega.assinatura_id == assinatura_id),
            key=lambda entrega: (entrega.criado_em, entrega.tentativa),
            reverse=True,
        )
        return _fatia(itens, deslocamento, limite)


class InboxEmMemoria:
    def __init__(self, dados: ArmazenamentoEmMemoria) -> None:
        self._dados = dados

    async def registrar(self, envelope: EnvelopeEvento) -> bool:
        if envelope.mensagem_id in self._dados.inbox:
            return False
        self._dados.inbox.add(envelope.mensagem_id)
        return True


class FilaDeTarefasEmMemoria:
    def __init__(self, dados: ArmazenamentoEmMemoria) -> None:
        self._dados = dados

    async def agendar(self, tarefa: Tarefa) -> None:
        self._dados.tarefas.append(tarefa)


class CaixaDeEventosExternosEmMemoria:
    def __init__(self, dados: ArmazenamentoEmMemoria) -> None:
        self._dados = dados

    async def registrar_se_novo(self, envelope: EnvelopeEvento) -> bool:
        if envelope.mensagem_id in self._dados.eventos_externos:
            return False
        self._dados.eventos_externos[envelope.mensagem_id] = envelope
        return True


class UnidadeDeTrabalhoEmMemoria:
    notificacoes: RepositorioNotificacoesEmMemoria
    assinaturas: RepositorioAssinaturasEmMemoria
    entregas: RepositorioEntregasEmMemoria
    inbox: InboxEmMemoria
    tarefas: FilaDeTarefasEmMemoria
    eventos_externos: CaixaDeEventosExternosEmMemoria

    def __init__(self, armazenamento: ArmazenamentoEmMemoria) -> None:
        self._armazenamento = armazenamento
        self._trabalho = ArmazenamentoEmMemoria()

    async def __aenter__(self) -> Self:
        self._trabalho = copy.deepcopy(self._armazenamento)
        self.notificacoes = RepositorioNotificacoesEmMemoria(self._trabalho)
        self.assinaturas = RepositorioAssinaturasEmMemoria(self._trabalho)
        self.entregas = RepositorioEntregasEmMemoria(self._trabalho)
        self.inbox = InboxEmMemoria(self._trabalho)
        self.tarefas = FilaDeTarefasEmMemoria(self._trabalho)
        self.eventos_externos = CaixaDeEventosExternosEmMemoria(self._trabalho)
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        return None  # sem commit, a cópia de trabalho é descartada

    async def commit(self) -> None:
        confirmado = copy.deepcopy(self._trabalho)
        destino = self._armazenamento
        destino.notificacoes = confirmado.notificacoes
        destino.assinaturas = confirmado.assinaturas
        destino.entregas = confirmado.entregas
        destino.inbox = confirmado.inbox
        destino.tarefas = confirmado.tarefas
        destino.eventos_externos = confirmado.eventos_externos
        destino.commits += 1


def fabrica_em_memoria(armazenamento: ArmazenamentoEmMemoria) -> FabricaUow:
    """Fábrica de UoW em memória (o mypy confere que ela cumpre a porta)."""

    def fabrica() -> UnidadeDeTrabalho:
        return UnidadeDeTrabalhoEmMemoria(armazenamento)

    return fabrica


class PerfisEmMemoria:
    def __init__(
        self, perfis: Mapping[str, Perfil] | None = None, *, indisponivel: int = 0
    ) -> None:
        self._perfis = dict(perfis or {})
        self.indisponivel = indisponivel
        self.consultas: list[str] = []

    async def obter(self, usuario_id: str) -> Perfil:
        self.consultas.append(usuario_id)
        if self.indisponivel > 0:
            self.indisponivel -= 1
            raise ErroDependenciaIndisponivel("identidade")
        perfil = self._perfis.get(usuario_id)
        if perfil is None:
            raise PerfilNaoEncontrado(f"Perfil {usuario_id} não existe.")
        return perfil


@dataclass(frozen=True, slots=True)
class EmailEnviado:
    para: str
    assunto: str
    corpo: str


class EnviadorDeEmailEmMemoria:
    def __init__(self, *, falhas: int = 0) -> None:
        self.falhas = falhas
        self.enviados: list[EmailEnviado] = []

    async def enviar(self, *, para: str, assunto: str, corpo: str) -> None:
        if self.falhas > 0:
            self.falhas -= 1
            raise FalhaNoEnvioDeEmail("SMTP indisponível (simulado).")
        self.enviados.append(EmailEnviado(para, assunto, corpo))


@dataclass(frozen=True, slots=True)
class ChamadaWebhook:
    url: str
    corpo: bytes
    cabecalhos: dict[str, str]


class EntregadorDeWebhookEmMemoria:
    """Devolve os resultados na ordem; o último se repete. Padrão: ``204``."""

    def __init__(self, *resultados: ResultadoEntrega) -> None:
        self._resultados = list(resultados) or [ResultadoEntrega(status_http=204, duracao_ms=1)]
        self.chamadas: list[ChamadaWebhook] = []

    async def entregar(
        self, url: str, corpo: bytes, cabecalhos: Mapping[str, str]
    ) -> ResultadoEntrega:
        self.chamadas.append(ChamadaWebhook(url, corpo, dict(cabecalhos)))
        if len(self._resultados) > 1:
            return self._resultados.pop(0)
        return self._resultados[0]
