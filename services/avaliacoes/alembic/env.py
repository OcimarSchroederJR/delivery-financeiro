"""Ambiente Alembic assíncrono (asyncpg) do serviço de Avaliações."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from avaliacoes.adaptadores.db.modelos import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configurar_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


def executar_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _executar(conexao: Connection) -> None:
    context.configure(connection=conexao, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def executar_online() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    async with engine.connect() as conexao:
        await conexao.run_sync(_executar)
    await engine.dispose()


if context.is_offline_mode():
    executar_offline()
else:
    asyncio.run(executar_online())
