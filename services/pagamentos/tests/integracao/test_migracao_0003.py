import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from plataforma.testes.migracoes import desfazer, migrar

pytestmark = pytest.mark.integracao

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


async def test_0003_preenche_o_dono_das_chaves_gravadas_pela_0002(banco_migrado: str) -> None:
    # Banco que já estava na 0002 publicada (sem a coluna dono), com uma chave gravada.
    await asyncio.to_thread(desfazer, ALEMBIC_INI, banco_migrado, "0002")
    engine = create_async_engine(banco_migrado)
    try:
        async with engine.begin() as conexao:
            await conexao.execute(
                text(
                    "INSERT INTO chaves_idempotencia (escopo, chave, hash_requisicao, status,"
                    " criado_em) VALUES ('POST /v1/pagamentos', 'k-antiga', 'h', 'concluida',"
                    " now())"
                )
            )
        await asyncio.to_thread(migrar, ALEMBIC_INI, banco_migrado)
        async with engine.connect() as conexao:
            dono = (
                await conexao.execute(
                    text("SELECT dono FROM chaves_idempotencia WHERE chave = 'k-antiga'")
                )
            ).scalar_one()
            versao = (
                await conexao.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert dono is not None
    assert versao == "0003"
