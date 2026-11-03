"""adiciona o dono (token da reserva) às chaves de idempotência

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


def downgrade() -> None:
    op.drop_column("chaves_idempotencia", "dono")
