"""Transactional Outbox (spec §3.3, §7.1).

Uso no serviço::

    class MensagemOutbox(OutboxMixin, Base):
        __tablename__ = "outbox"

    async with fabrica() as sessao, sessao.begin():
        ...  # mudança de estado
        gravar_no_outbox(sessao, MensagemOutbox, EnvelopeEvento.novo("pagamento.aprovado", dados))
"""

import asyncio
import contextlib
import uuid
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from plataforma.correlation import correlation_id_em
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


class OutboxMixin:
    """Colunas da tabela de outbox. Combine com a ``Base`` declarativa do serviço."""

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mensagem_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    tipo: Mapped[str] = mapped_column(String(100))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    ultimo_erro: Mapped[str | None] = mapped_column(Text)


def gravar_no_outbox[M: OutboxMixin](
    sessao: AsyncSession, modelo: type[M], envelope: EnvelopeEvento
) -> M:
    """Adiciona o evento à sessão. O commit é do chamador (mesma transação do estado)."""
    registro = modelo()
    registro.mensagem_id = envelope.mensagem_id
    registro.tipo = envelope.tipo
    registro.envelope = envelope.para_json()
    registro.tentativas = 0
    sessao.add(registro)
    return registro


class Publicador(Protocol):
    async def publicar(self, envelope: EnvelopeEvento) -> None: ...


class RelayOutbox[M: OutboxMixin]:
    """Publica eventos pendentes em ordem, com ``FOR UPDATE SKIP LOCKED``.

    Seguro com várias réplicas: cada lote fica travado pela transação que o leu.
    Se a publicação falha (broker fora), o evento continua pendente, com
    ``tentativas`` incrementado, e o lote é interrompido para preservar a ordem.
    """

    def __init__(
        self,
        fabrica_sessoes: async_sessionmaker[AsyncSession],
        modelo: type[M],
        publicador: Publicador,
        *,
        tamanho_lote: int = 100,
    ) -> None:
        self._fabrica = fabrica_sessoes
        self._modelo = modelo
        self._publicador = publicador
        self._tamanho_lote = tamanho_lote

    async def publicar_pendentes(self) -> int:
        """Processa um lote. Retorna quantos eventos foram publicados."""
        modelo = self._modelo
        publicados = 0
        async with self._fabrica() as sessao, sessao.begin():
            consulta = (
                select(modelo)
                .where(modelo.publicado_em.is_(None))
                .order_by(modelo.id)
                .limit(self._tamanho_lote)
                .with_for_update(skip_locked=True)
            )
            for registro in (await sessao.scalars(consulta)).all():
                envelope = EnvelopeEvento.model_validate(registro.envelope)
                with correlation_id_em(envelope.correlation_id):
                    try:
                        await self._publicador.publicar(envelope)
                    except Exception as erro:
                        registro.tentativas += 1
                        registro.ultimo_erro = f"{type(erro).__name__}: {erro}"[:500]
                        _log.warning(
                            "evento_publicacao_falhou",
                            tipo=envelope.tipo,
                            mensagem_id=str(envelope.mensagem_id),
                            tentativas=registro.tentativas,
                            erro=type(erro).__name__,
                        )
                        break
                    registro.publicado_em = agora_utc()
                    publicados += 1
                    _log.info(
                        "evento_publicado",
                        tipo=envelope.tipo,
                        mensagem_id=str(envelope.mensagem_id),
                    )
        return publicados

    async def executar(self, parar: asyncio.Event, *, intervalo: float = 1.0) -> None:
        """Laço do worker: drena a fila; quando vazia, espera ``intervalo`` segundos."""
        _log.info("relay_outbox_iniciado")
        while not parar.is_set():
            try:
                publicados = await self.publicar_pendentes()
            except Exception:
                _log.exception("relay_outbox_falhou")
                publicados = 0
            if publicados == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(parar.wait(), timeout=intervalo)
        _log.info("relay_outbox_encerrado")
