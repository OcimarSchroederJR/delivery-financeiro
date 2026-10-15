"""Modelos SQLAlchemy do serviço. Todos herdam de ``Base``."""

from sqlalchemy.orm import DeclarativeBase

from plataforma.db import criar_metadata
from plataforma.inbox import InboxMixin
from plataforma.outbox import OutboxMixin


class Base(DeclarativeBase):
    metadata = criar_metadata()


class MensagemOutbox(OutboxMixin, Base):
    __tablename__ = "outbox"


class MensagemProcessada(InboxMixin, Base):
    __tablename__ = "inbox"
