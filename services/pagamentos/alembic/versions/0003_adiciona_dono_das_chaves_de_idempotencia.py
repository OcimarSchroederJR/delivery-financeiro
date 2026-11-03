"""adiciona o dono (token da reserva) e amplia o escopo das chaves de idempotência

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chaves_idempotencia", sa.Column("dono", sa.Uuid(), nullable=True))
    # Chaves gravadas antes desta migração recebem um dono qualquer: nenhuma
    # requisição em andamento o conhece, então elas só podem ser repetidas ou reassumidas.
    op.execute("UPDATE chaves_idempotencia SET dono = gen_random_uuid() WHERE dono IS NULL")
    op.alter_column("chaves_idempotencia", "dono", nullable=False)
    # O escopo da criação passa a incluir o id do usuário.
    op.alter_column(
        "chaves_idempotencia", "escopo", type_=sa.Text(), existing_type=sa.String(length=200)
    )


def downgrade() -> None:
    op.alter_column(
        "chaves_idempotencia",
        "escopo",
        type_=sa.String(length=200),
        existing_type=sa.Text(),
        postgresql_using="left(escopo, 200)",
    )
    op.drop_column("chaves_idempotencia", "dono")
