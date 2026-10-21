"""Portas (Protocols) da aplicação. Os adaptadores as implementam."""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

from notificacoes.aplicacao.tarefas import Tarefa
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.notificacao import Notificacao
from plataforma.envelope import EnvelopeEvento

# Persistência ------------------------------------------------------------------


class RepositorioNotificacoes(Protocol):
    async def adicionar(self, notificacao: Notificacao) -> None: ...

    async def obter_para_atualizar(self, notificacao_id: uuid.UUID) -> Notificacao | None:
        """Lê com trava de linha (``FOR UPDATE``) até o fim da transação."""
        ...

    async def atualizar(self, notificacao: Notificacao) -> None: ...

    async def listar(
        self, *, destinatario_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Notificacao], int]: ...


class RepositorioAssinaturas(Protocol):
    async def adicionar(self, assinatura: AssinaturaWebhook) -> None: ...

    async def obter(self, assinatura_id: uuid.UUID) -> AssinaturaWebhook | None: ...

    async def atualizar(self, assinatura: AssinaturaWebhook) -> None: ...

    async def listar(
        self, *, criado_por: str | None, deslocamento: int, limite: int
    ) -> tuple[list[AssinaturaWebhook], int]:
        """Só assinaturas ativas, mais recentes primeiro."""
        ...

    async def listar_ativas(self) -> list[AssinaturaWebhook]: ...


class RepositorioEntregas(Protocol):
    async def adicionar(self, entrega: EntregaWebhook) -> None: ...

    async def listar(
        self, assinatura_id: uuid.UUID, *, deslocamento: int, limite: int
    ) -> tuple[list[EntregaWebhook], int]: ...


class Inbox(Protocol):
    async def registrar(self, envelope: EnvelopeEvento) -> bool:
        """``True`` se a mensagem é nova; ``False`` se já foi processada."""
        ...


class FilaDeTarefas(Protocol):
    async def agendar(self, tarefa: Tarefa) -> None:
        """Grava a tarefa no outbox de tarefas (mesma transação)."""
        ...


class CaixaDeEventosExternos(Protocol):
    async def registrar_se_novo(self, envelope: EnvelopeEvento) -> bool:
        """Grava no outbox de eventos; ``False`` se o ``mensagem_id`` já existe."""
        ...


class UnidadeDeTrabalho(Protocol):
    """Transação única. Sair do ``async with`` sem ``commit`` desfaz tudo."""

    @property
    def notificacoes(self) -> RepositorioNotificacoes: ...

    @property
    def assinaturas(self) -> RepositorioAssinaturas: ...

    @property
    def entregas(self) -> RepositorioEntregas: ...

    @property
    def inbox(self) -> Inbox: ...

    @property
    def tarefas(self) -> FilaDeTarefas: ...

    @property
    def eventos_externos(self) -> CaixaDeEventosExternos: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


FabricaUow = Callable[[], UnidadeDeTrabalho]

# Dependências externas ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Perfil:
    id: str
    email: str
    nome: str | None = None


class PerfilNaoEncontrado(Exception):
    """A Eq. 1 respondeu 404 (falha definitiva)."""


class PerfilInvalido(Exception):
    """A Eq. 1 respondeu um perfil sem e-mail utilizável (falha definitiva)."""


class FalhaNoEnvioDeEmail(Exception):
    """Servidor SMTP indisponível ou recusou a mensagem (falha transitória)."""


class ClientePerfis(Protocol):
    async def obter(self, usuario_id: str) -> Perfil:
        """``PerfilNaoEncontrado``/``PerfilInvalido`` (definitivas) ou
        ``ErroDependenciaIndisponivel`` (transitória)."""
        ...


class EnviadorDeEmail(Protocol):
    async def enviar(self, *, para: str, assunto: str, corpo: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ResultadoEntrega:
    status_http: int | None
    duracao_ms: int
    erro: str | None = None

    @property
    def sucesso(self) -> bool:
        return self.erro is None and self.status_http is not None and 200 <= self.status_http < 300

    def descricao_falha(self) -> str:
        return self.erro or f"HTTP {self.status_http}"


class EntregadorDeWebhook(Protocol):
    async def entregar(
        self, url: str, corpo: bytes, cabecalhos: Mapping[str, str]
    ) -> ResultadoEntrega:
        """Nunca levanta exceção: timeout e erro de rede viram ``ResultadoEntrega.erro``."""
        ...


class CifradorDeSegredos(Protocol):
    def cifrar(self, texto: str) -> str: ...

    def decifrar(self, cifrado: str) -> str: ...
