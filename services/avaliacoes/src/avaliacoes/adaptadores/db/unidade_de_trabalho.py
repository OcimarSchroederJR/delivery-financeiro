"""Unit of Work com SQLAlchemy: uma sessão/transação; eventos vão para o outbox."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avaliacoes.adaptadores.db.modelos import MensagemOutbox
from avaliacoes.adaptadores.db.repositorios import RepositorioAvaliacoesSql, RepositorioDisputasSql
from avaliacoes.aplicacao.portas import DadosEvento, FabricaUnidadeDeTrabalho
from plataforma.envelope import EnvelopeEvento
from plataforma.outbox import gravar_no_outbox


class UnidadeDeTrabalhoSql:
    def __init__(self, fabrica_sessoes: async_sessionmaker[AsyncSession]) -> None:
        self._fabrica = fabrica_sessoes
        self._sessao: AsyncSession | None = None
        self._avaliacoes: RepositorioAvaliacoesSql | None = None
        self._disputas: RepositorioDisputasSql | None = None

    @property
    def avaliacoes(self) -> RepositorioAvaliacoesSql:
        if self._avaliacoes is None:
            raise RuntimeError("Use a unidade de trabalho dentro de 'async with'.")
        return self._avaliacoes

    @property
    def disputas(self) -> RepositorioDisputasSql:
        if self._disputas is None:
            raise RuntimeError("Use a unidade de trabalho dentro de 'async with'.")
        return self._disputas

    async def __aenter__(self) -> Self:
        self._sessao = self._fabrica()
        self._avaliacoes = RepositorioAvaliacoesSql(self._sessao)
        self._disputas = RepositorioDisputasSql(self._sessao)
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        sessao, self._sessao = self._sessao, None
        self._avaliacoes = self._disputas = None
        if sessao is None:  # pragma: no cover - só se __aenter__ não rodou
            return
        try:
            await sessao.rollback()  # sem commit() nada fica gravado; após commit é no-op
        finally:
            await sessao.close()

    async def commit(self) -> None:
        if self._sessao is None:
            raise RuntimeError("Use a unidade de trabalho dentro de 'async with'.")
        await self._sessao.commit()

    def registrar_evento(self, tipo: str, dados: DadosEvento) -> None:
        if self._sessao is None:
            raise RuntimeError("Use a unidade de trabalho dentro de 'async with'.")
        gravar_no_outbox(self._sessao, MensagemOutbox, EnvelopeEvento.novo(tipo, dados))


def fabrica_uow_sql(fabrica_sessoes: async_sessionmaker[AsyncSession]) -> FabricaUnidadeDeTrabalho:
    return lambda: UnidadeDeTrabalhoSql(fabrica_sessoes)
