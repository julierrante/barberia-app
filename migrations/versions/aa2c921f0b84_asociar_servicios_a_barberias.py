
"""Asociar servicios a barberias.

Revision ID: aa2c921f0b84
Revises: 58b2fd53299b
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores de Alembic.
revision: str = "aa2c921f0b84"
down_revision: Union[str, Sequence[str], None] = "58b2fd53299b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FK_SERVICIOS_BARBERIA = "fk_services_barberia_id_barberias"


def upgrade() -> None:
    """Agregar la relacion opcional entre servicios y barberias."""

    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(
            sa.Column("barberia_id", sa.Integer(), nullable=True)
        )

        batch_op.create_index(
            "ix_services_barberia_id",
            ["barberia_id"],
            unique=False,
        )

        batch_op.create_foreign_key(
            FK_SERVICIOS_BARBERIA,
            "barberias",
            ["barberia_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """Eliminar la relacion entre servicios y barberias."""

    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_constraint(
            FK_SERVICIOS_BARBERIA,
            type_="foreignkey",
        )

        batch_op.drop_index("ix_services_barberia_id")
        batch_op.drop_column("barberia_id")
