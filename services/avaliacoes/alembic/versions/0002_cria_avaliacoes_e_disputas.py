"""cria tabelas de avaliações e disputas

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "avaliacoes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pedido_id", sa.String(length=100), nullable=False),
        sa.Column("cliente_id", sa.String(length=100), nullable=False),
        sa.Column("restaurante_id", sa.String(length=100), nullable=False),
        sa.Column("nota_restaurante", sa.SmallInteger(), nullable=False),
        sa.Column("nota_entrega", sa.SmallInteger(), nullable=True),
        sa.Column("comentario", sa.String(length=1000), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "nota_restaurante BETWEEN 1 AND 5",
            name=op.f("ck_avaliacoes_nota_restaurante_faixa"),
        ),
        sa.CheckConstraint(
            "nota_entrega IS NULL OR nota_entrega BETWEEN 1 AND 5",
            name=op.f("ck_avaliacoes_nota_entrega_faixa"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_avaliacoes")),
        sa.UniqueConstraint("pedido_id", name=op.f("uq_avaliacoes_pedido_id")),
    )
    op.create_index(op.f("ix_avaliacoes_restaurante_id"), "avaliacoes", ["restaurante_id"])

    op.create_table(
        "disputas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pedido_id", sa.String(length=100), nullable=False),
        sa.Column("pagamento_id", sa.String(length=100), nullable=False),
        sa.Column("cliente_id", sa.String(length=100), nullable=False),
        sa.Column("motivo", sa.String(length=20), nullable=False),
        sa.Column("descricao", sa.String(length=2000), nullable=True),
        sa.Column("valor_solicitado_centavos", sa.Integer(), nullable=False),
        sa.Column("valor_aprovado_centavos", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("parecer", sa.String(length=2000), nullable=True),
        sa.Column("estorno_id", sa.String(length=100), nullable=True),
        sa.Column("tentativas_estorno", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("proxima_tentativa_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_falha_estorno", sa.String(length=200), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "valor_solicitado_centavos > 0",
            name=op.f("ck_disputas_valor_solicitado_positivo"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disputas")),
    )
    op.create_index(op.f("ix_disputas_pedido_id"), "disputas", ["pedido_id"])
    op.create_index(op.f("ix_disputas_cliente_id"), "disputas", ["cliente_id"])
    op.create_index(
        "ix_disputas_pedido_id_nao_terminal",
        "disputas",
        ["pedido_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('aberta', 'estorno_pendente')"),
    )
    op.create_index(
        "ix_disputas_status_proxima_tentativa_em",
        "disputas",
        ["status", "proxima_tentativa_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_disputas_status_proxima_tentativa_em", table_name="disputas")
    op.drop_index("ix_disputas_pedido_id_nao_terminal", table_name="disputas")
    op.drop_index(op.f("ix_disputas_cliente_id"), table_name="disputas")
    op.drop_index(op.f("ix_disputas_pedido_id"), table_name="disputas")
    op.drop_table("disputas")
    op.drop_index(op.f("ix_avaliacoes_restaurante_id"), table_name="avaliacoes")
    op.drop_table("avaliacoes")
