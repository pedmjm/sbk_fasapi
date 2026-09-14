"""estado en_revision (tareas + visitas)

Revision ID: f2b8d1e6a4c9
Revises: e1a9c5d3f7b2
Create Date: 2026-09-09 00:00:00.000000

Adds the EN_REVISION value to the native Postgres enums `estado_tarea`
and `estado_visita` — the middle step between en_progreso and
completada/finalizada that only reviewers (nivel >= 2) can close.

SQLite stores enums as VARCHAR → no-op there.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b8d1e6a4c9'
down_revision: Union[str, Sequence[str], None] = 'e1a9c5d3f7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ALTER TYPE ... ADD VALUE can't run inside the same transaction
        # that uses the value — we only add it, alembic's autocommit
        # block keeps this safe across PG versions.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE estado_tarea ADD VALUE IF NOT EXISTS 'EN_REVISION'")
            op.execute("ALTER TYPE estado_visita ADD VALUE IF NOT EXISTS 'EN_REVISION'")


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no `ALTER TYPE ... DROP VALUE`; removing the value
    requires recreating the enum type (not attempted here). The value
    simply stays unused after downgrade.
    """
    pass
