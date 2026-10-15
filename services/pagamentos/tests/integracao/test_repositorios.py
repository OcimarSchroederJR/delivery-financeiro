from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pagamentos.adaptadores.db.modelos import MensagemOutbox
from pagamentos.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql
from pagamentos.dominio.erros import IdempotencyEmProcessamento, PedidoJaPago
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave
from pagamentos.dominio.pagamento import MetodoPagamento, StatusPagamento
from pagamentos.testes.fakes import INSTANTE, pagamento_aprovado, pagamento_recusado
from plataforma.correlation import correlation_id_em
from plataforma.db import criar_engine, criar_fabrica_sessoes

pytestmark = pytest.mark.integracao


@pytest.fixture
async def sessoes(banco_migrado: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = criar_engine(banco_migrado)
    yield criar_fabrica_sessoes(engine)
    await engine.dispose()


@pytest.fixture
def uow(sessoes: async_sessionmaker[AsyncSession]):  # retorna a fábrica de unidades
    return lambda: UnidadeDeTrabalhoSql(sessoes)


async def _gravar(uow, *pagamentos) -> None:
    async with uow() as unidade:
        for pagamento in pagamentos:
            await unidade.pagamentos.adicionar(pagamento)
        await unidade.commit()


async def test_adiciona_e_obtem_ida_e_volta(uow) -> None:
    pagamento = pagamento_aprovado(metodo=MetodoPagamento.CARTAO_CREDITO)
    await _gravar(uow, pagamento)
    async with uow() as unidade:
        assert await unidade.pagamentos.obter(pagamento.id) == pagamento
        assert await unidade.pagamentos.obter(uuid4()) is None


async def test_sem_commit_nada_e_gravado(uow) -> None:
    pagamento = pagamento_aprovado()
    async with uow() as unidade:
        await unidade.pagamentos.adicionar(pagamento)
    async with uow() as unidade:
        assert await unidade.pagamentos.obter(pagamento.id) is None


async def test_salva_estornos_e_status(uow) -> None:
    pagamento = pagamento_aprovado()
    await _gravar(uow, pagamento)
    async with uow() as unidade:
        obtido = await unidade.pagamentos.obter(pagamento.id, para_atualizar=True)
        assert obtido is not None
        obtido.estornar(valor_centavos=1000, motivo="a", estorno_id=uuid4(), agora=INSTANTE)
        obtido.estornar(
            valor_centavos=500, motivo="b", estorno_id=uuid4(), agora=INSTANTE + timedelta(days=1)
        )
        await unidade.pagamentos.salvar(obtido)
        await unidade.commit()
    async with uow() as unidade:
        relido = await unidade.pagamentos.obter(pagamento.id)
    assert relido == obtido
    assert relido is not None
    assert relido.status == StatusPagamento.PARCIALMENTE_ESTORNADO
    assert [e.motivo for e in relido.estornos] == ["a", "b"]


async def test_salvar_pagamento_que_nao_existe_e_erro(uow) -> None:
    async with uow() as unidade:
        with pytest.raises(ValueError, match="persistido"):
            await unidade.pagamentos.salvar(pagamento_aprovado())


async def test_um_efetivado_por_pedido(uow) -> None:
    await _gravar(uow, pagamento_recusado(), pagamento_recusado(), pagamento_aprovado())
    with pytest.raises(PedidoJaPago):
        await _gravar(uow, pagamento_aprovado())
    async with uow() as unidade:
        assert await unidade.pagamentos.existe_efetivado("ped-1")
        assert not await unidade.pagamentos.existe_efetivado("ped-4")


async def test_lista_com_filtros_ordem_total_e_pagina(uow) -> None:
    antigo = pagamento_aprovado(pedido_id="ped-1", agora=INSTANTE)
    novo = pagamento_aprovado(pedido_id="ped-4", agora=INSTANTE + timedelta(minutes=5))
    alheio = pagamento_aprovado(pedido_id="ped-3", cliente_id="cliente-2")
    await _gravar(uow, antigo, novo, alheio)
    async with uow() as unidade:
        listar = unidade.pagamentos.listar
        assert await listar(pedido_id=None, cliente_id="cliente-1", deslocamento=0, limite=20) == (
            [novo, antigo],
            2,
        )
        assert await listar(pedido_id=None, cliente_id="cliente-1", deslocamento=1, limite=1) == (
            [antigo],
            2,
        )
        assert await listar(pedido_id="ped-3", cliente_id=None, deslocamento=0, limite=20) == (
            [alheio],
            1,
        )


async def test_eventos_vao_para_o_outbox_com_correlation_id(uow, sessoes) -> None:
    with correlation_id_em("cid-repositorio"):
        async with uow() as unidade:
            unidade.eventos.registrar("pagamento.aprovado", {"pagamento_id": "p-1"})
            await unidade.commit()
    async with sessoes() as sessao:
        registros = (await sessao.scalars(select(MensagemOutbox))).all()
    assert len(registros) == 1
    envelope = registros[0].envelope
    assert (registros[0].tipo, envelope["tipo"]) == ("pagamento.aprovado", "pagamento.aprovado")
    assert envelope["dados"] == {"pagamento_id": "p-1"}
    assert envelope["correlation_id"] == "cid-repositorio"


async def test_chaves_reservar_obter_e_concluir(uow) -> None:
    reserva = RegistroIdempotencia.reservar(
        escopo="POST /v1/pagamentos", chave="k-1", hash_requisicao="h" * 64, agora=INSTANTE
    )
    async with uow() as unidade:
        await unidade.chaves_idempotencia.reservar(reserva)
        await unidade.commit()
    with pytest.raises(IdempotencyEmProcessamento):
        async with uow() as unidade:
            await unidade.chaves_idempotencia.reservar(reserva)
    async with uow() as unidade:
        chaves = unidade.chaves_idempotencia
        assert await chaves.obter("POST /v1/pagamentos", "k-1", para_atualizar=True) == reserva
        await chaves.concluir(
            "POST /v1/pagamentos", "k-1", status_resposta=201, corpo_resposta={"id": "x"}
        )
        await chaves.concluir("POST /v1/pagamentos", "k-1", status_resposta=409, corpo_resposta={})
        await unidade.commit()
    async with uow() as unidade:
        registro = await unidade.chaves_idempotencia.obter("POST /v1/pagamentos", "k-1")
    assert registro is not None
    assert registro.status == StatusChave.CONCLUIDA
    assert registro.resposta() == (201, {"id": "x"})


async def test_chaves_substituir_remover_e_expirar(uow) -> None:
    antiga = RegistroIdempotencia.reservar(
        escopo="e", chave="velha", hash_requisicao="h1", agora=INSTANTE
    )
    recente = RegistroIdempotencia.reservar(
        escopo="e", chave="nova", hash_requisicao="h2", agora=INSTANTE + timedelta(days=1)
    )
    async with uow() as unidade:
        await unidade.chaves_idempotencia.reservar(antiga)
        await unidade.chaves_idempotencia.reservar(recente)
        await unidade.commit()
    substituta = RegistroIdempotencia.reservar(
        escopo="e", chave="nova", hash_requisicao="h3", agora=INSTANTE + timedelta(days=2)
    )
    async with uow() as unidade:
        await unidade.chaves_idempotencia.substituir(substituta)
        assert (
            await unidade.chaves_idempotencia.remover_expiradas(INSTANTE + timedelta(hours=1)) == 1
        )
        await unidade.commit()
    async with uow() as unidade:
        assert await unidade.chaves_idempotencia.obter("e", "velha") is None
        assert await unidade.chaves_idempotencia.obter("e", "nova") == substituta
        await unidade.chaves_idempotencia.remover("e", "nova")
        await unidade.commit()
    async with uow() as unidade:
        assert await unidade.chaves_idempotencia.obter("e", "nova") is None


async def test_remover_nao_apaga_chave_concluida(uow) -> None:
    reserva = RegistroIdempotencia.reservar(
        escopo="e", chave="feita", hash_requisicao="h", agora=INSTANTE
    )
    async with uow() as unidade:
        await unidade.chaves_idempotencia.reservar(reserva)
        await unidade.chaves_idempotencia.concluir(
            "e", "feita", status_resposta=201, corpo_resposta={"id": "x"}
        )
        await unidade.commit()
    async with uow() as unidade:
        await unidade.chaves_idempotencia.remover("e", "feita")
        await unidade.commit()
    async with uow() as unidade:
        registro = await unidade.chaves_idempotencia.obter("e", "feita")
    assert registro is not None
    assert registro.resposta() == (201, {"id": "x"})
