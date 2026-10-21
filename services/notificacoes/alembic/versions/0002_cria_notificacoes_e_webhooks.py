"""cria notificações, assinaturas e entregas de webhook e outbox de tarefas

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _criado_em() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "assinaturas_webhook",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("eventos", postgresql.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column("segredo_cifrado", sa.Text(), nullable=False),
        sa.Column("ativa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("criado_por", sa.String(length=128), nullable=False),
        sa.Column("somente_proprios", sa.Boolean(), nullable=False),
        _criado_em(),
        sa.PrimaryKeyConstraint("id", name="pk_assinaturas_webhook"),
    )
    op.create_index("ix_assinaturas_webhook_ativa", "assinaturas_webhook", ["ativa"])
    op.create_index("ix_assinaturas_webhook_criado_por", "assinaturas_webhook", ["criado_por"])

    op.create_table(
        "notificacoes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mensagem_id_origem", sa.Uuid(), nullable=False),
        sa.Column("tipo_evento", sa.String(length=100), nullable=False),
        sa.Column("canal", sa.String(length=10), nullable=False),
        sa.Column("destino", sa.Text(), nullable=True),
        sa.Column("destinatario_id", sa.String(length=128), nullable=True),
        sa.Column("assinatura_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("tentativas", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ultimo_erro", sa.Text(), nullable=True),
        _criado_em(),
        sa.Column("enviada_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assinatura_id"],
            ["assinaturas_webhook.id"],
            name="fk_notificacoes_assinatura_id_assinaturas_webhook",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notificacoes"),
    )
    op.create_index("ix_notificacoes_mensagem_id_origem", "notificacoes", ["mensagem_id_origem"])
    op.create_index("ix_notificacoes_destinatario_id", "notificacoes", ["destinatario_id"])
    op.create_index("ix_notificacoes_status", "notificacoes", ["status"])

    op.create_table(
        "entregas_webhook",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assinatura_id", sa.Uuid(), nullable=False),
        sa.Column("mensagem_id", sa.Uuid(), nullable=False),
        sa.Column("tentativa", sa.Integer(), nullable=False),
        sa.Column("status_http", sa.Integer(), nullable=True),
        sa.Column("duracao_ms", sa.Integer(), nullable=False),
        sa.Column("erro", sa.Text(), nullable=True),
        _criado_em(),
        sa.ForeignKeyConstraint(
            ["assinatura_id"],
            ["assinaturas_webhook.id"],
            name="fk_entregas_webhook_assinatura_id_assinaturas_webhook",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entregas_webhook"),
    )
    op.create_index("ix_entregas_webhook_assinatura_id", "entregas_webhook", ["assinatura_id"])
    op.create_index("ix_entregas_webhook_mensagem_id", "entregas_webhook", ["mensagem_id"])

    op.create_table(
        "outbox_tarefas",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("mensagem_id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.String(length=100), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        _criado_em(),
        sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tentativas", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ultimo_erro", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_tarefas"),
        sa.UniqueConstraint("mensagem_id", name="uq_outbox_tarefas_mensagem_id"),
    )
    op.create_index("ix_outbox_tarefas_publicado_em", "outbox_tarefas", ["publicado_em"])


def downgrade() -> None:
    op.drop_index("ix_outbox_tarefas_publicado_em", table_name="outbox_tarefas")
    op.drop_table("outbox_tarefas")
    op.drop_index("ix_entregas_webhook_mensagem_id", table_name="entregas_webhook")
    op.drop_index("ix_entregas_webhook_assinatura_id", table_name="entregas_webhook")
    op.drop_table("entregas_webhook")
    op.drop_index("ix_notificacoes_status", table_name="notificacoes")
    op.drop_index("ix_notificacoes_destinatario_id", table_name="notificacoes")
    op.drop_index("ix_notificacoes_mensagem_id_origem", table_name="notificacoes")
    op.drop_table("notificacoes")
    op.drop_index("ix_assinaturas_webhook_criado_por", table_name="assinaturas_webhook")
    op.drop_index("ix_assinaturas_webhook_ativa", table_name="assinaturas_webhook")
    op.drop_table("assinaturas_webhook")
