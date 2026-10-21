"""Unit of Work SQLAlchemy: uma sessão/transação por ``async with``."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notificacoes.adaptadores.db.repositorios import (
    CaixaDeEventosExternosSql,
    FilaDeTarefasSql,
    InboxSql,
    RepositorioAssinaturasSql,
    RepositorioEntregasSql,
    RepositorioNotificacoesSql,
)
from notificacoes.aplicacao.portas import CifradorDeSegredos, FabricaUow, UnidadeDeTrabalho


class UnidadeDeTrabalhoSql:
    notificacoes: RepositorioNotificacoesSql
    assinaturas: RepositorioAssinaturasSql
    entregas: RepositorioEntregasSql
    inbox: InboxSql
    tarefas: FilaDeTarefasSql
    eventos_externos: CaixaDeEventosExternosSql

    def __init__(
        self, fabrica_sessoes: async_sessionmaker[AsyncSession], cifrador: CifradorDeSegredos
    ) -> None:
        self._fabrica_sessoes = fabrica_sessoes
        self._cifrador = cifrador

    async def __aenter__(self) -> Self:
        self._sessao = self._fabrica_sessoes()
        self.notificacoes = RepositorioNotificacoesSql(self._sessao)
        self.assinaturas = RepositorioAssinaturasSql(self._sessao, self._cifrador)
        self.entregas = RepositorioEntregasSql(self._sessao)
        self.inbox = InboxSql(self._sessao)
        self.tarefas = FilaDeTarefasSql(self._sessao)
        self.eventos_externos = CaixaDeEventosExternosSql(self._sessao)
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        try:
            await self._sessao.rollback()  # sem efeito depois do commit
        finally:
            await self._sessao.close()

    async def commit(self) -> None:
        await self._sessao.commit()


def fabrica_sql(
    fabrica_sessoes: async_sessionmaker[AsyncSession], cifrador: CifradorDeSegredos
) -> FabricaUow:
    def fabrica() -> UnidadeDeTrabalho:
        return UnidadeDeTrabalhoSql(fabrica_sessoes, cifrador)

    return fabrica
