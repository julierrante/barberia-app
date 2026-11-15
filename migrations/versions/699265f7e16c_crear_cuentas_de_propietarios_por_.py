
"""Crear cuentas de propietarios por barberia.

Revision ID: 699265f7e16c
Revises: aa2c921f0b84
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "699265f7e16c"
down_revision: Union[str, Sequence[str], None] = "aa2c921f0b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "owner_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("barberia_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["barberia_id"],
            ["barberias.id"],
        ),
    )

    op.create_index(
        "ix_owner_accounts_barberia_id",
        "owner_accounts",
        ["barberia_id"],
    )

    op.create_index(
        "ix_owner_accounts_email",
        "owner_accounts",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_owner_accounts_email",
        table_name="owner_accounts",
    )

    op.drop_index(
        "ix_owner_accounts_barberia_id",
        table_name="owner_accounts",
    )

    op.drop_table("owner_accounts")
