"""Unidade de trabalho SQLAlchemy: uma sessão/transação por ``async with``."""

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pagamentos.adaptadores.db.modelos import MensagemOutbox
from pagamentos.adaptadores.db.repositorios import (
    RepositorioChavesIdempotenciaSql,
    RepositorioPagamentosSql,
)
from plataforma.envelope import EnvelopeEvento
from plataforma.outbox import gravar_no_outbox


class RegistroDeEventosOutbox:
    """Grava o evento no outbox na mesma transação da mudança de estado (spec §3.3)."""

    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    def registrar(self, tipo: str, dados: Mapping[str, Any]) -> None:
        gravar_no_outbox(self._sessao, MensagemOutbox, EnvelopeEvento.novo(tipo, dados))


class UnidadeDeTrabalhoSql:
    pagamentos: RepositorioPagamentosSql
    chaves_idempotencia: RepositorioChavesIdempotenciaSql
    eventos: RegistroDeEventosOutbox

    def __init__(self, fabrica_sessoes: async_sessionmaker[AsyncSession]) -> None:
        self._fabrica = fabrica_sessoes
        self._sessao: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        sessao = self._fabrica()
        self._sessao = sessao
        self.pagamentos = RepositorioPagamentosSql(sessao)
        self.chaves_idempotencia = RepositorioChavesIdempotenciaSql(sessao)
        self.eventos = RegistroDeEventosOutbox(sessao)
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        sessao = self._ativa()
        self._sessao = None
        try:
            await sessao.rollback()  # sem efeito se já houve commit
        finally:
            await sessao.close()

    async def commit(self) -> None:
        await self._ativa().commit()

    def _ativa(self) -> AsyncSession:
        if self._sessao is None:
            raise RuntimeError("use a unidade de trabalho dentro de 'async with'")
        return self._sessao
