"""Saga de disputa sob concorrência real no Postgres (spec §4.3 e §5; revisão do PR #21).

- ``PATCH /v1/disputas/{id}`` e o worker concluem a mesma disputa ao mesmo tempo:
  o ``FOR UPDATE`` deve garantir uma única transição e um único ``disputa.resolvida``.
- Commit perdido: Pagamentos gravou o estorno, mas a disputa ficou em
  ``estorno_pendente``. A nova tentativa (mesma ``Idempotency-Key``) recebe o ``201``
  gravado e resolve a disputa sem estorno duplicado.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avaliacoes.config import Config
from avaliacoes.dominio.disputa import Disputa, MotivoDisputa
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.tempo import agora_utc
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
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
