import asyncio
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from plataforma.testes.migracoes import desfazer, migrar

pytestmark = pytest.mark.integracao

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
INSERIR_PAGAMENTO = text(
    "INSERT INTO pagamentos (id, pedido_id, cliente_id, valor_centavos, metodo, status,"
    " motivo_recusa, criado_em, atualizado_em) VALUES (gen_random_uuid(), :pedido,"
    " 'cliente-1', :valor, 'pix', :status, :motivo, now(), now())"
)


async def _tabelas(url: str) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conexao:
        nomes = await conexao.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    return set(nomes)


async def _inserir(
    engine: AsyncEngine, pedido: str, status: str, valor: int = 100, motivo: str | None = None
) -> None:
    async with engine.begin() as conexao:
        await conexao.execute(
            INSERIR_PAGAMENTO,
            {"pedido": pedido, "valor": valor, "status": status, "motivo": motivo},
        )


async def test_cria_as_tabelas_do_servico(banco_migrado: str) -> None:
    assert {"outbox", "pagamentos", "estornos", "chaves_idempotencia"} <= await _tabelas(
        banco_migrado
    )


async def test_um_unico_pagamento_efetivado_por_pedido(banco_migrado: str) -> None:
    engine = create_async_engine(banco_migrado)
    try:
        await _inserir(engine, "ped-1", "recusado", motivo="saldo_insuficiente")
        await _inserir(engine, "ped-1", "recusado", motivo="saldo_insuficiente")
        await _inserir(engine, "ped-1", "aprovado")
        with pytest.raises(IntegrityError, match="uq_pagamentos_pedido_id_efetivado"):
            await _inserir(engine, "ped-1", "estornado")
        await _inserir(engine, "ped-2", "aprovado")
    finally:
        await engine.dispose()


async def test_valor_do_pagamento_precisa_ser_positivo(banco_migrado: str) -> None:
    engine = create_async_engine(banco_migrado)
    try:
        with pytest.raises(IntegrityError, match="ck_pagamentos_valor_positivo"):
            await _inserir(engine, "ped-1", "aprovado", valor=0)
    finally:
        await engine.dispose()


async def test_downgrade_para_0001_remove_so_as_tabelas_novas(banco_migrado: str) -> None:
    # O env.py do Alembic usa asyncio.run: dentro de um teste async, roda em outra thread.
    await asyncio.to_thread(desfazer, ALEMBIC_INI, banco_migrado, "0001")
    tabelas = await _tabelas(banco_migrado)
    assert "outbox" in tabelas
    assert not {"pagamentos", "estornos", "chaves_idempotencia"} & tabelas
    await asyncio.to_thread(migrar, ALEMBIC_INI, banco_migrado)
    assert "pagamentos" in await _tabelas(banco_migrado)
