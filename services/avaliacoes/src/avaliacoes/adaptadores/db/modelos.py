"""Modelos SQLAlchemy do serviço. Todos herdam de ``Base``."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from plataforma.db import criar_metadata
from plataforma.outbox import OutboxMixin

CONDICAO_NAO_TERMINAL = "status IN ('aberta', 'estorno_pendente')"


class Base(DeclarativeBase):
    metadata = criar_metadata()


class MensagemOutbox(OutboxMixin, Base):
    __tablename__ = "outbox"


class AvaliacaoModelo(Base):
    __tablename__ = "avaliacoes"
    __table_args__ = (
        CheckConstraint("nota_restaurante BETWEEN 1 AND 5", name="nota_restaurante_faixa"),
        CheckConstraint(
            "nota_entrega IS NULL OR nota_entrega BETWEEN 1 AND 5", name="nota_entrega_faixa"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    pedido_id: Mapped[str] = mapped_column(String(100), unique=True)
    cliente_id: Mapped[str] = mapped_column(String(100))
    restaurante_id: Mapped[str] = mapped_column(String(100), index=True)
    nota_restaurante: Mapped[int] = mapped_column(SmallInteger)
    nota_entrega: Mapped[int | None] = mapped_column(SmallInteger)
    comentario: Mapped[str | None] = mapped_column(String(1000))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DisputaModelo(Base):
    __tablename__ = "disputas"
    __table_args__ = (
        # Regra 3: no máximo uma disputa não-terminal por pedido (também sob concorrência).
        Index(
            "ix_disputas_pedido_id_nao_terminal",
            "pedido_id",
            unique=True,
            postgresql_where=text(CONDICAO_NAO_TERMINAL),
        ),
        # Worker: busca as sagas pendentes cujo horário de retentativa chegou.
        Index("ix_disputas_status_proxima_tentativa_em", "status", "proxima_tentativa_em"),
        CheckConstraint("valor_solicitado_centavos > 0", name="valor_solicitado_positivo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    pedido_id: Mapped[str] = mapped_column(String(100), index=True)
    pagamento_id: Mapped[str] = mapped_column(String(100))
    cliente_id: Mapped[str] = mapped_column(String(100), index=True)
    motivo: Mapped[str] = mapped_column(String(20))
    descricao: Mapped[str | None] = mapped_column(String(2000))
    valor_solicitado_centavos: Mapped[int] = mapped_column(Integer)
    valor_aprovado_centavos: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    parecer: Mapped[str | None] = mapped_column(String(2000))
    estorno_id: Mapped[str | None] = mapped_column(String(100))
    tentativas_estorno: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    proxima_tentativa_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_falha_estorno: Mapped[str | None] = mapped_column(String(200))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
