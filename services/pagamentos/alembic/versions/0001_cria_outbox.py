"""cria tabela de outbox

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("mensagem_id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.String(length=100), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tentativas", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ultimo_erro", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox"),
        sa.UniqueConstraint("mensagem_id", name="uq_outbox_mensagem_id"),
    )
    op.create_index("ix_outbox_publicado_em", "outbox", ["publicado_em"])


def downgrade() -> None:
    op.drop_index("ix_outbox_publicado_em", table_name="outbox")
    op.drop_table("outbox")
