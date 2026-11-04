"""Saga de disputa sob concorrência real no Postgres (spec §4.3 e §5; revisão do PR #21).

- ``PATCH /v1/disputas/{id}`` e o worker concluem a mesma disputa ao mesmo tempo:
  o ``FOR UPDATE`` deve garantir uma única transição e um único ``disputa.resolvida``.
- Commit perdido: Pagamentos gravou o estorno, mas a disputa ficou em
  ``estorno_pendente``. A nova tentativa (mesma ``Idempotency-Key``) recebe o ``201``
  gravado e resolve a disputa sem estorno duplicado.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avaliacoes.adaptadores.db.modelos import MensagemOutbox
from avaliacoes.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql, fabrica_uow_sql
from avaliacoes.api import criar_app
from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho
from avaliacoes.config import Config
from avaliacoes.dominio.disputa import Disputa, MotivoDisputa, StatusDisputa
from avaliacoes.worker import executar
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.tempo import agora_utc
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
    GeradorDeTokens,
    criar_verificador_de_teste,
)

pytestmark = pytest.mark.integracao

URL_PAGAMENTOS = "http://pagamentos.teste"
ROTA_ESTORNOS = "/v1/pagamentos/pag-1/estornos"


@dataclass
class PagamentosIdempotente:
    """Simula o ``POST /estornos`` de Pagamentos: a mesma chave devolve o 201 gravado."""

    criados: dict[str, str] = field(default_factory=dict)
    chaves_recebidas: list[str] = field(default_factory=list)
    em_voo: int = 0
    duas_em_voo: asyncio.Event = field(default_factory=asyncio.Event)
    segurar_ate_duas_em_voo: bool = False

    async def responder(self, requisicao: httpx.Request) -> httpx.Response:
        chave = requisicao.headers["Idempotency-Key"]
        self.chaves_recebidas.append(chave)
        self.em_voo += 1
        if self.em_voo >= 2:
            self.duas_em_voo.set()
        try:
            if self.segurar_ate_duas_em_voo:
                # Só responde quando o PATCH e o worker estão os dois esperando Pagamentos.
                await asyncio.wait_for(self.duas_em_voo.wait(), timeout=5)
            estorno_id = self.criados.setdefault(chave, f"est-{len(self.criados) + 1}")
            return httpx.Response(201, json={"id": estorno_id, "status": "concluido"})
        finally:
            self.em_voo -= 1


def _config(banco: str, rabbitmq_url: str) -> Config:
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        database_url=banco,
        rabbitmq_url=rabbitmq_url,
        pagamentos_url=URL_PAGAMENTOS,
        saga_atraso_inicial_segundos=0,
        worker_intervalo_segundos=0.01,
    )


def _disputa_aberta() -> Disputa:
    return Disputa.abrir(
        pedido_id="ped-4",
        pagamento_id="pag-1",
        cliente_id="cliente-1",
        motivo=MotivoDisputa.ITEM_FALTANDO,
        descricao=None,
        valor_solicitado_centavos=1000,
        valor_pago_centavos=3200,
        agora=agora_utc() - timedelta(minutes=1),
    )


@pytest.fixture
async def fabrica(banco_migrado: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = criar_engine(banco_migrado)
    yield criar_fabrica_sessoes(engine)
    await engine.dispose()


async def _gravar(uow: FabricaUnidadeDeTrabalho, disputa: Disputa) -> None:
    async with uow() as u:
        await u.disputas.adicionar(disputa)
        await u.commit()


async def _eventos(fabrica: async_sessionmaker[AsyncSession], tipo: str) -> int:
    async with fabrica() as sessao:
        total = await sessao.scalar(
            select(func.count()).select_from(MensagemOutbox).where(MensagemOutbox.tipo == tipo)
        )
    return int(total or 0)


async def _final(uow: FabricaUnidadeDeTrabalho, disputa_id: uuid.UUID) -> Disputa:
    async with uow() as u:
        disputa = await u.disputas.obter(disputa_id)
    assert disputa is not None
    return disputa


async def test_patch_e_worker_concluem_a_mesma_disputa_uma_unica_vez(
    banco_migrado: str, rabbitmq_url: str, fabrica: async_sessionmaker[AsyncSession]
) -> None:
    uow = fabrica_uow_sql(fabrica)
    disputa = _disputa_aberta()
    await _gravar(uow, disputa)
    config = _config(banco_migrado, rabbitmq_url)
    gerador = GeradorDeTokens()
    app = criar_app(config, verificador=criar_verificador_de_teste(gerador))
    pagamentos = PagamentosIdempotente(segurar_ate_duas_em_voo=True)

    parar = asyncio.Event()
    with respx.mock(base_url=URL_PAGAMENTOS) as mock:
        rota = mock.post(ROTA_ESTORNOS).mock(side_effect=pagamentos.responder)
        worker = asyncio.create_task(executar(config, parar))
        try:
            async with LifespanManager(app) as gerenciador:
                transporte = httpx.ASGITransport(app=gerenciador.app)
                async with httpx.AsyncClient(transport=transporte, base_url="http://t") as api:
                    resposta = await api.patch(
                        f"/v1/disputas/{disputa.id}",
                        json={"status": "procedente", "parecer": "ok"},
                        headers={"Authorization": f"Bearer {gerador.emitir('admin-1', 'admin')}"},
                    )
        finally:
            # O laço do worker termina o lote em curso antes de olhar ``parar``.
            parar.set()
            await asyncio.wait_for(worker, timeout=10)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == StatusDisputa.RESOLVIDA.value
    # As duas tentativas chegaram a Pagamentos ao mesmo tempo, com a mesma chave.
    assert rota.call_count == 2
    assert pagamentos.chaves_recebidas == [f"disputa-{disputa.id}"] * 2
    assert len(pagamentos.criados) == 1
    final = await _final(uow, disputa.id)
    assert final.status is StatusDisputa.RESOLVIDA
    assert final.estorno_id == "est-1"
    assert final.tentativas_estorno == 1
    assert await _eventos(fabrica, "disputa.resolvida") == 1


class _UowQueCaiNoCommit(UnidadeDeTrabalhoSql):
    """Perde a conexão no commit: o que a transação fez é desfeito."""

    async def commit(self) -> None:
        raise ConnectionResetError("conexão com o banco caiu no commit")
