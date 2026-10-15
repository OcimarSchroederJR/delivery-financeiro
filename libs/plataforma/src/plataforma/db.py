"""Fábricas de engine/sessão SQLAlchemy async e convenção de nomes."""

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

CONVENCAO_DE_NOMES: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def criar_metadata() -> MetaData:
    """MetaData com nomes de constraints estáveis (migrações Alembic previsíveis)."""
    return MetaData(naming_convention=CONVENCAO_DE_NOMES)


def criar_engine(url: str, *, eco: bool = False) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, echo=eco)


def criar_fabrica_sessoes(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
