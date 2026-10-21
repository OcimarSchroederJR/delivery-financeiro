import pytest

from pagamentos.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql
from plataforma.db import criar_engine, criar_fabrica_sessoes


async def test_commit_fora_do_async_with_e_erro_de_programacao() -> None:
    engine = criar_engine("postgresql+asyncpg://x:x@127.0.0.1:1/x")
    try:
        with pytest.raises(RuntimeError, match="async with"):
            await UnidadeDeTrabalhoSql(criar_fabrica_sessoes(engine)).commit()
    finally:
        await engine.dispose()
