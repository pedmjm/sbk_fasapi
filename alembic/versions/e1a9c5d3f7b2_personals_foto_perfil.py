"""personals.foto_perfil mirror

Revision ID: e1a9c5d3f7b2
Revises: d9c4e7f2a6b8
Create Date: 2026-09-02 00:00:00.000000

  * `personals.foto_perfil` (String(255), nullable) — mirror of the linked
    User's photo (User.id == Personal.id), written through
    `POST /perfil/imagen`.
  * Backfill: copies any existing users.foto_perfil onto its personal.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a9c5d3f7b2'
down_revision: Union[str, Sequence[str], None] = 'd9c4e7f2a6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch mode: works on SQLite (recreate) and Postgres alike.
    with op.batch_alter_table('personals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('foto_perfil', sa.String(length=255), nullable=True))

    # Backfill from linked users (same UUID).
    op.execute(
        "UPDATE personals SET foto_perfil = u.foto_perfil "
        "FROM users u WHERE u.id = personals.id AND u.foto_perfil IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('personals', schema=None) as batch_op:
        batch_op.drop_column('foto_perfil')
