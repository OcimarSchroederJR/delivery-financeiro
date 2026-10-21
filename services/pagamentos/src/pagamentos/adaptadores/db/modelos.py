"""Modelos SQLAlchemy do serviço. Todos herdam de ``Base``.

Nunca há coluna para número do cartão, CVV, titular ou validade: só ``cartao_final``.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from plataforma.db import criar_metadata
from plataforma.outbox import OutboxMixin

INDICE_PEDIDO_EFETIVADO = "uq_pagamentos_pedido_id_efetivado"


class Base(DeclarativeBase):
    metadata = criar_metadata()


class MensagemOutbox(OutboxMixin, Base):
    __tablename__ = "outbox"


class PagamentoModelo(Base):
    __tablename__ = "pagamentos"
    __table_args__ = (
        CheckConstraint("valor_centavos > 0", name="valor_positivo"),
        CheckConstraint("metodo IN ('cartao_credito', 'pix')", name="metodo_valido"),
        CheckConstraint(
            "status IN ('aprovado', 'recusado', 'parcialmente_estornado', 'estornado')",
            name="status_valido",
        ),
        # Regra 3: um único pagamento efetivado (aprovado, mesmo que estornado) por pedido.
        Index(
            INDICE_PEDIDO_EFETIVADO,
            "pedido_id",
            unique=True,
            postgresql_where=sql("status <> 'recusado'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    pedido_id: Mapped[str] = mapped_column(String(64), index=True)
    cliente_id: Mapped[str] = mapped_column(String(128), index=True)
    valor_centavos: Mapped[int] = mapped_column(BigInteger)
    metodo: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    motivo_recusa: Mapped[str | None] = mapped_column(String(50))
    cartao_final: Mapped[str | None] = mapped_column(String(4))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estornos: Mapped[list["EstornoModelo"]] = relationship(
        lazy="selectin", order_by="EstornoModelo.criado_em"
    )


class EstornoModelo(Base):
    __tablename__ = "estornos"
    __table_args__ = (CheckConstraint("valor_centavos > 0", name="valor_positivo"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    pagamento_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pagamentos.id"), index=True)
    valor_centavos: Mapped[int] = mapped_column(BigInteger)
    motivo: Mapped[str] = mapped_column(String(500))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChaveIdempotenciaModelo(Base):
    __tablename__ = "chaves_idempotencia"
    __table_args__ = (
        CheckConstraint("status IN ('em_processamento', 'concluida')", name="status_valido"),
    )

    escopo: Mapped[str] = mapped_column(String(200), primary_key=True)
    chave: Mapped[str] = mapped_column(String(255), primary_key=True)
    hash_requisicao: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    status_resposta: Mapped[int | None] = mapped_column(Integer)
    corpo_resposta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
