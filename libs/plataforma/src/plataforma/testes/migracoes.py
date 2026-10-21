"""Ajudantes para testar migrações Alembic dos serviços contra um Postgres real."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as ConfigAlembic
from alembic.migration import MigrationContext
from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine


def config_alembic(arquivo_ini: Path, url: str) -> ConfigAlembic:
    """Config do Alembic apontando para ``url`` e sem reconfigurar o logging."""
    config = ConfigAlembic(str(arquivo_ini))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configurar_logging"] = False
    return config


def migrar(arquivo_ini: Path, url: str, revisao: str = "head") -> None:
    command.upgrade(config_alembic(arquivo_ini, url), revisao)


def desfazer(arquivo_ini: Path, url: str, revisao: str = "base") -> None:
    command.downgrade(config_alembic(arquivo_ini, url), revisao)


async def diferencas_modelo_banco(url: str, metadata: MetaData) -> list[Any]:
    """Diferenças entre os modelos SQLAlchemy e o banco migrado (vazio = em dia)."""

    def comparar(conexao: Connection) -> list[Any]:
        return list(compare_metadata(MigrationContext.configure(conexao), metadata))

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(comparar)
    finally:
        await engine.dispose()
