import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avaliacoes.adaptadores.db.modelos import MensagemOutbox
from avaliacoes.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql, fabrica_uow_sql
from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho
from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import Disputa, MotivoDisputa, StatusDisputa
from avaliacoes.dominio.erros import AvaliacaoDuplicada, DisputaJaAberta
from plataforma.db import criar_engine, criar_fabrica_sessoes

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
async def fabrica(banco_migrado: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = criar_engine(banco_migrado)
    yield criar_fabrica_sessoes(engine)
    await engine.dispose()


@pytest.fixture
def uow(fabrica: async_sessionmaker[AsyncSession]) -> FabricaUnidadeDeTrabalho:
    return fabrica_uow_sql(fabrica)


def _avaliacao(pedido_id: str, restaurante_id: str, nota: int, entrega: int | None) -> Avaliacao:
    return Avaliacao.registrar(
        pedido_id=pedido_id,
        cliente_id="cliente-1",
        restaurante_id=restaurante_id,
        nota_restaurante=nota,
        nota_entrega=entrega,
        comentario=None,
        agora=AGORA + timedelta(seconds=nota),
    )


def _disputa(pedido_id: str = "ped-4", cliente_id: str = "cliente-1") -> Disputa:
    return Disputa.abrir(
        pedido_id=pedido_id,
        pagamento_id="pag-1",
        cliente_id=cliente_id,
        motivo=MotivoDisputa.QUALIDADE,
        descricao="fria",
        valor_solicitado_centavos=1000,
        valor_pago_centavos=3200,
        agora=AGORA,
    )


async def test_avaliacoes_gravam_listam_e_resumem(uow: FabricaUnidadeDeTrabalho) -> None:
    async with uow() as u:
        for pedido, restaurante, nota, entrega in [
            ("p1", "rest-1", 5, 4),
            ("p2", "rest-1", 4, None),
            ("p3", "rest-1", 2, 3),
            ("p4", "rest-2", 1, 1),
        ]:
            await u.avaliacoes.adicionar(_avaliacao(pedido, restaurante, nota, entrega))
        await u.commit()
    async with uow() as u:
        itens, total = await u.avaliacoes.listar(
            restaurante_id="rest-1", pedido_id=None, deslocamento=0, limite=2
        )
        assert total == 3
        assert [a.pedido_id for a in itens] == ["p1", "p2"]  # criado_em desc
        assert (await u.avaliacoes.obter(itens[0].id)) == itens[0]
        resumo = await u.avaliacoes.resumir("rest-1")
        vazio = await u.avaliacoes.resumir("rest-x")
    assert (resumo.media_restaurante, resumo.media_entrega, resumo.total) == (3.67, 3.5, 3)
    assert (vazio.media_restaurante, vazio.media_entrega, vazio.total) == (None, None, 0)


async def test_avaliacao_duplicada_concorrente_vira_409(uow: FabricaUnidadeDeTrabalho) -> None:
    async def registrar() -> None:
        async with uow() as u:
            await u.avaliacoes.adicionar(_avaliacao("p-concorrente", "rest-1", 5, None))
            await u.commit()

    resultados = await asyncio.gather(registrar(), registrar(), return_exceptions=True)
    assert sum(isinstance(r, AvaliacaoDuplicada) for r in resultados) == 1
    assert sum(r is None for r in resultados) == 1


async def test_disputa_nao_terminal_unica_mesmo_sob_concorrencia(
    uow: FabricaUnidadeDeTrabalho,
) -> None:
    async def abrir() -> None:
        async with uow() as u:
            await u.disputas.adicionar(_disputa("ped-concorrente"))
            await u.commit()

    resultados = await asyncio.gather(abrir(), abrir(), return_exceptions=True)
    assert sum(isinstance(r, DisputaJaAberta) for r in resultados) == 1
    async with uow() as u:
        assert await u.disputas.existe_nao_terminal("ped-concorrente")
        [aberta], _ = await u.disputas.listar(
            status=None, cliente_id="cliente-1", deslocamento=0, limite=10
        )
        aberta.julgar_improcedente(parecer=None, valor_aprovado_centavos=None, agora=AGORA)
        await u.disputas.salvar(aberta)
        await u.commit()
    async with uow() as u:
        assert not await u.disputas.existe_nao_terminal("ped-concorrente")
        await u.disputas.adicionar(_disputa("ped-concorrente"))  # terminal não bloqueia
        await u.commit()


async def test_disputa_ida_e_volta_e_filtros(uow: FabricaUnidadeDeTrabalho) -> None:
    original = _disputa("ped-ida-volta", cliente_id="cliente-7")
    async with uow() as u:
        await u.disputas.adicionar(original)
        await u.commit()
    async with uow() as u:
        disputa = await u.disputas.obter(original.id, para_atualizar=True)
        assert disputa == original
        disputa.aprovar(
            valor_aprovado_centavos=None,
            parecer="ok",
            agora=AGORA,
            primeira_tentativa_em=AGORA + timedelta(seconds=30),
        )
        disputa.contar_tentativa()
        await u.disputas.salvar(disputa)
        await u.commit()
    async with uow() as u:
        relida = await u.disputas.obter(original.id)
        pendentes, total = await u.disputas.listar(
            status=StatusDisputa.ESTORNO_PENDENTE,
            cliente_id="cliente-7",
            deslocamento=0,
            limite=10,
        )
    assert relida == disputa
    assert (total, pendentes) == (1, [disputa])


async def test_reserva_para_retentativa_respeita_horario_e_nao_repete(
    uow: FabricaUnidadeDeTrabalho,
) -> None:
    disputa = _disputa("ped-reserva")
    disputa.aprovar(
        valor_aprovado_centavos=None,
        parecer=None,
        agora=AGORA,
        primeira_tentativa_em=AGORA + timedelta(seconds=30),
    )
    async with uow() as u:
        await u.disputas.adicionar(disputa)
        await u.commit()

    async def reservar(agora: datetime) -> list[object]:
        async with uow() as u:
            ids = await u.disputas.reservar_para_retentativa(
                agora=agora, reservar_ate=agora + timedelta(seconds=60), limite=10
            )
            await u.commit()
        return list(ids)

    assert await reservar(AGORA) == []
    assert await reservar(AGORA + timedelta(seconds=30)) == [disputa.id]
    assert await reservar(AGORA + timedelta(seconds=31)) == []  # reservada por 60 s
    assert await reservar(AGORA + timedelta(seconds=91)) == [disputa.id]


async def test_evento_vai_para_o_outbox_so_com_commit(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    async with UnidadeDeTrabalhoSql(fabrica) as u:
        u.registrar_evento("disputa.aberta", {"disputa_id": "d-sem-commit"})
    async with UnidadeDeTrabalhoSql(fabrica) as u:
        u.registrar_evento("disputa.aberta", {"disputa_id": "d-com-commit"})
        await u.commit()
    async with fabrica() as sessao:
        envelopes = (await sessao.scalars(select(MensagemOutbox.envelope))).all()
    ids = [e["dados"]["disputa_id"] for e in envelopes]
    assert "d-com-commit" in ids
    assert "d-sem-commit" not in ids


async def test_usar_fora_do_async_with_e_erro(fabrica: async_sessionmaker[AsyncSession]) -> None:
    unidade = UnidadeDeTrabalhoSql(fabrica)
    with pytest.raises(RuntimeError):
        _ = unidade.avaliacoes
    with pytest.raises(RuntimeError):
        _ = unidade.disputas
    with pytest.raises(RuntimeError):
        await unidade.commit()
    with pytest.raises(RuntimeError):
        unidade.registrar_evento("disputa.aberta", {})
