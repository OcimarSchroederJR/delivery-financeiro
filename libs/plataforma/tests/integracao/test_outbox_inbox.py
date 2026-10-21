import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from plataforma.db import criar_engine, criar_fabrica_sessoes, criar_metadata
from plataforma.envelope import EnvelopeEvento
from plataforma.inbox import InboxMixin, registrar_na_inbox
from plataforma.outbox import OutboxMixin, RelayOutbox, gravar_no_outbox

pytestmark = pytest.mark.integracao


class Base(DeclarativeBase):
    metadata = criar_metadata()


class MensagemOutbox(OutboxMixin, Base):
    __tablename__ = "outbox"


class MensagemProcessada(InboxMixin, Base):
    __tablename__ = "inbox"


class PublicadorFake:
    def __init__(self) -> None:
        self.publicados: list[EnvelopeEvento] = []
        self.falhar = False

    async def publicar(self, envelope: EnvelopeEvento) -> None:
        if self.falhar:
            raise ConnectionError("broker fora")
        self.publicados.append(envelope)


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = criar_engine(postgres_url)
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.drop_all)
        await conexao.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def fabrica(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return criar_fabrica_sessoes(engine)


async def _gravar(fabrica: async_sessionmaker[AsyncSession], *tipos: str) -> list[EnvelopeEvento]:
    envelopes = [EnvelopeEvento.novo(tipo, {"n": i}) for i, tipo in enumerate(tipos)]
    async with fabrica() as sessao, sessao.begin():
        for envelope in envelopes:
            gravar_no_outbox(sessao, MensagemOutbox, envelope)
    return envelopes


async def test_rollback_descarta_o_evento(fabrica: async_sessionmaker[AsyncSession]) -> None:
    async def mudar_estado_e_falhar() -> None:
        async with fabrica() as sessao, sessao.begin():
            gravar_no_outbox(sessao, MensagemOutbox, EnvelopeEvento.novo("pagamento.aprovado", {}))
            raise RuntimeError("falha na regra de negócio")

    with pytest.raises(RuntimeError):
        await mudar_estado_e_falhar()
    async with fabrica() as sessao:
        assert await sessao.scalar(select(func.count()).select_from(MensagemOutbox)) == 0


async def test_relay_publica_em_ordem_e_marca_publicado(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    gravados = await _gravar(fabrica, "pagamento.aprovado", "pagamento.estornado")
    publicador = PublicadorFake()
    relay = RelayOutbox(fabrica, MensagemOutbox, publicador)
    assert await relay.publicar_pendentes() == 2
    assert [e.mensagem_id for e in publicador.publicados] == [e.mensagem_id for e in gravados]
    assert publicador.publicados[0].para_json() == gravados[0].para_json()
    assert await relay.publicar_pendentes() == 0


async def test_broker_fora_mantem_pendente_e_conta_tentativas(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    await _gravar(fabrica, "pagamento.aprovado", "pagamento.recusado")
    publicador = PublicadorFake()
    publicador.falhar = True
    relay = RelayOutbox(fabrica, MensagemOutbox, publicador)
    assert await relay.publicar_pendentes() == 0
    async with fabrica() as sessao:
        registros = (await sessao.scalars(select(MensagemOutbox).order_by(MensagemOutbox.id))).all()
    assert [r.tentativas for r in registros] == [1, 0]
    assert registros[0].ultimo_erro == "ConnectionError: broker fora"
    publicador.falhar = False
    assert await relay.publicar_pendentes() == 2


async def test_duas_replicas_nao_publicam_o_mesmo_evento(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    await _gravar(fabrica, *["avaliacao.registrada"] * 20)
    publicador = PublicadorFake()

    class PublicadorLento(PublicadorFake):
        async def publicar(self, envelope: EnvelopeEvento) -> None:
            await asyncio.sleep(0.01)
            publicador.publicados.append(envelope)

    relays = [
        RelayOutbox(fabrica, MensagemOutbox, PublicadorLento(), tamanho_lote=5) for _ in range(2)
    ]
    while sum(await asyncio.gather(*(r.publicar_pendentes() for r in relays))):
        pass
    ids = [e.mensagem_id for e in publicador.publicados]
    assert len(ids) == 20
    assert len(set(ids)) == 20


async def test_executar_para_quando_sinalizado(fabrica: async_sessionmaker[AsyncSession]) -> None:
    await _gravar(fabrica, "disputa.aberta")
    publicador = PublicadorFake()
    parar = asyncio.Event()
    tarefa = asyncio.create_task(
        RelayOutbox(fabrica, MensagemOutbox, publicador).executar(parar, intervalo=0.05)
    )
    for _ in range(100):
        if publicador.publicados:
            break
        await asyncio.sleep(0.02)
    parar.set()
    await asyncio.wait_for(tarefa, timeout=2)
    assert len(publicador.publicados) == 1


async def test_inbox_detecta_duplicata(fabrica: async_sessionmaker[AsyncSession]) -> None:
    envelope = EnvelopeEvento.novo("pagamento.aprovado", {})
    async with fabrica() as sessao, sessao.begin():
        assert await registrar_na_inbox(sessao, MensagemProcessada, envelope) is True
    async with fabrica() as sessao, sessao.begin():
        assert await registrar_na_inbox(sessao, MensagemProcessada, envelope) is False


async def test_inbox_desfeita_com_rollback_do_efeito(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    envelope = EnvelopeEvento.novo("pagamento.aprovado", {})

    async def consumir_e_falhar() -> None:
        async with fabrica() as sessao, sessao.begin():
            await registrar_na_inbox(sessao, MensagemProcessada, envelope)
            raise RuntimeError("efeito falhou")

    with pytest.raises(RuntimeError):
        await consumir_e_falhar()
    async with fabrica() as sessao, sessao.begin():
        assert await registrar_na_inbox(sessao, MensagemProcessada, envelope) is True


async def test_publicacao_travada_expira_e_mantem_pendente(
    fabrica: async_sessionmaker[AsyncSession],
) -> None:
    await _gravar(fabrica, "pagamento.aprovado")

    class PublicadorTravado(PublicadorFake):
        async def publicar(self, envelope: EnvelopeEvento) -> None:
            await asyncio.Event().wait()

    relay = RelayOutbox(fabrica, MensagemOutbox, PublicadorTravado(), timeout_publicacao=0.1)
    assert await asyncio.wait_for(relay.publicar_pendentes(), timeout=5) == 0
    async with fabrica() as sessao:
        registro = await sessao.scalar(select(MensagemOutbox))
    assert registro is not None
    assert registro.publicado_em is None
    assert registro.tentativas == 1
    assert registro.ultimo_erro is not None
    assert registro.ultimo_erro.startswith("TimeoutError")
