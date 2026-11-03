"""cria pagamentos, estornos e chaves de idempotência

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


def upgrade() -> None:
    op.create_table(
        "pagamentos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pedido_id", sa.String(length=64), nullable=False),
        sa.Column("cliente_id", sa.String(length=128), nullable=False),
        sa.Column("valor_centavos", sa.BigInteger(), nullable=False),
        sa.Column("metodo", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("motivo_recusa", sa.String(length=50), nullable=True),
        sa.Column("cartao_final", sa.String(length=4), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("valor_centavos > 0", name="ck_pagamentos_valor_positivo"),
        sa.CheckConstraint(
            "metodo IN ('cartao_credito', 'pix')", name="ck_pagamentos_metodo_valido"
        ),
        sa.CheckConstraint(
            "status IN ('aprovado', 'recusado', 'parcialmente_estornado', 'estornado')",
            name="ck_pagamentos_status_valido",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pagamentos"),
    )
    op.create_index("ix_pagamentos_pedido_id", "pagamentos", ["pedido_id"])
    op.create_index("ix_pagamentos_cliente_id", "pagamentos", ["cliente_id"])
    op.create_index(
        "uq_pagamentos_pedido_id_efetivado",
        "pagamentos",
        ["pedido_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'recusado'"),
    )
    op.create_table(
        "estornos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pagamento_id", sa.Uuid(), nullable=False),
        sa.Column("valor_centavos", sa.BigInteger(), nullable=False),
        sa.Column("motivo", sa.String(length=500), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("valor_centavos > 0", name="ck_estornos_valor_positivo"),
        sa.ForeignKeyConstraint(
            ["pagamento_id"], ["pagamentos.id"], name="fk_estornos_pagamento_id_pagamentos"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estornos"),
    )
    op.create_index("ix_estornos_pagamento_id", "estornos", ["pagamento_id"])
    op.create_table(
        "chaves_idempotencia",
        sa.Column("escopo", sa.String(length=200), nullable=False),
        sa.Column("chave", sa.String(length=255), nullable=False),
        sa.Column("hash_requisicao", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_resposta", sa.Integer(), nullable=True),
        sa.Column("corpo_resposta", postgresql.JSONB(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('em_processamento', 'concluida')",
            name="ck_chaves_idempotencia_status_valido",
        ),
        sa.PrimaryKeyConstraint("escopo", "chave", name="pk_chaves_idempotencia"),
    )
    op.create_index("ix_chaves_idempotencia_criado_em", "chaves_idempotencia", ["criado_em"])


def downgrade() -> None:
    op.drop_index("ix_chaves_idempotencia_criado_em", table_name="chaves_idempotencia")
    op.drop_table("chaves_idempotencia")
    op.drop_index("ix_estornos_pagamento_id", table_name="estornos")
    op.drop_table("estornos")
    op.drop_index("uq_pagamentos_pedido_id_efetivado", table_name="pagamentos")
    op.drop_index("ix_pagamentos_cliente_id", table_name="pagamentos")
    op.drop_index("ix_pagamentos_pedido_id", table_name="pagamentos")
    op.drop_table("pagamentos")
