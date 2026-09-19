"""eliminacion en dos pasos (tareas + visitas)

Revision ID: a4c7e9f1b3d6
Revises: f2b8d1e6a4c9
Create Date: 2026-09-09 00:00:00.000000

Two-step (4-eyes) deletion: admins mark, a DIFFERENT admin confirms.

  * tareas.eliminar_marcada        (bool, NOT NULL, default false)
  * tareas.eliminar_marcada_por_id (UUID? FK users ON DELETE SET NULL)
  * visitas.eliminar_marcada        (bool, NOT NULL, default false)
  * visitas.eliminar_marcada_por_id (UUID? FK users ON DELETE SET NULL)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c7e9f1b3d6'
down_revision: Union[str, Sequence[str], None] = 'f2b8d1e6a4c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch mode: works on SQLite (recreate) and Postgres alike.
    for table in ("tareas", "visitas"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("eliminar_marcada", sa.Boolean(), nullable=False, server_default="false")
            )
            batch_op.add_column(sa.Column("eliminar_marcada_por_id", sa.Uuid(), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table}_eliminar_marcada_por_id_users",
                "users",
                ["eliminar_marcada_por_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("tareas", "visitas"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_eliminar_marcada_por_id_users", type_="foreignkey")
            batch_op.drop_column("eliminar_marcada_por_id")
            batch_op.drop_column("eliminar_marcada")
