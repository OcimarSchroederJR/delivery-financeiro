"""Inbox: consumidor idempotente por ``mensagem_id`` (spec §3.3).

Uso no consumidor::

    class MensagemProcessada(InboxMixin, Base):
        __tablename__ = "inbox"

    async with fabrica() as sessao, sessao.begin():
        if not await registrar_na_inbox(sessao, MensagemProcessada, envelope):
            return  # duplicada: confirma (ack) sem refazer o efeito
        ...  # efeito, na mesma transação
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger

_log = obter_logger(__name__)


class InboxMixin:
    """Colunas da tabela de inbox. Combine com a ``Base`` declarativa do serviço."""

    mensagem_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    processada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def registrar_na_inbox(
    sessao: AsyncSession, modelo: type[InboxMixin], envelope: EnvelopeEvento
) -> bool:
    """Registra a mensagem. ``True`` se é nova; ``False`` se já foi processada."""
    comando = (
        insert(modelo)
        .values(mensagem_id=envelope.mensagem_id)
        .on_conflict_do_nothing(index_elements=["mensagem_id"])
        .returning(modelo.mensagem_id)
    )
    nova = (await sessao.execute(comando)).scalar_one_or_none() is not None
    _log.info(
        "evento_consumido",
        tipo=envelope.tipo,
        mensagem_id=str(envelope.mensagem_id),
        inbox="nova" if nova else "duplicada",
    )
    return nova
