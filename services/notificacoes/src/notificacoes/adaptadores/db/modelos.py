"""Modelos SQLAlchemy do serviço. Todos herdam de ``Base``."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from plataforma.db import criar_metadata
from plataforma.inbox import InboxMixin
from plataforma.outbox import OutboxMixin


class Base(DeclarativeBase):
    metadata = criar_metadata()


class MensagemOutbox(OutboxMixin, Base):
    """Eventos externos (``POST /v1/eventos``) a publicar em ``financeiro.eventos``."""

    __tablename__ = "outbox"


class MensagemProcessada(InboxMixin, Base):
    __tablename__ = "inbox"


class TarefaSaida(OutboxMixin, Base):
    """Tarefas de e-mail/webhook a publicar nas filas internas (outbox de tarefas)."""

    __tablename__ = "outbox_tarefas"


class AssinaturaWebhookLinha(Base):
    __tablename__ = "assinaturas_webhook"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    eventos: Mapped[list[str]] = mapped_column(ARRAY(String(100)))
    segredo_cifrado: Mapped[str] = mapped_column(Text)
    ativa: Mapped[bool] = mapped_column(Boolean, index=True, server_default=text("true"))
    criado_por: Mapped[str] = mapped_column(String(128), index=True)
    somente_proprios: Mapped[bool] = mapped_column(Boolean)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificacaoLinha(Base):
    __tablename__ = "notificacoes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    mensagem_id_origem: Mapped[uuid.UUID] = mapped_column(index=True)
    tipo_evento: Mapped[str] = mapped_column(String(100))
    canal: Mapped[str] = mapped_column(String(10))
    destino: Mapped[str | None] = mapped_column(Text)
    destinatario_id: Mapped[str | None] = mapped_column(String(128), index=True)
    assinatura_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assinaturas_webhook.id"))
    status: Mapped[str] = mapped_column(String(10), index=True)
    tentativas: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntregaWebhookLinha(Base):
    __tablename__ = "entregas_webhook"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    assinatura_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assinaturas_webhook.id"), index=True
    )
    mensagem_id: Mapped[uuid.UUID] = mapped_column(index=True)
    tentativa: Mapped[int] = mapped_column(Integer)
    status_http: Mapped[int | None] = mapped_column(Integer)
    duracao_ms: Mapped[int] = mapped_column(Integer)
    erro: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
