"""comentarios belong to pasos

Revision ID: b7e2c4d9f0a1
Revises: 1b3910c6311e
Create Date: 2026-09-01 00:00:00.000000

Comments now live on each paso (step) instead of the tarea:

  * adds `comentarios.paso_id` (nullable FK -> pasos_tarea.id, ON DELETE
    CASCADE, indexed). `tarea_id` stays as a denormalized copy for
    cleanup/notifications.
  * purges existing tarea-level comments and their Imagen rows
    (approved one-way data migration — they have no paso to attach to).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2c4d9f0a1'
down_revision: Union[str, Sequence[str], None] = '1b3910c6311e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch_alter_table so the FK works on both SQLite (table recreate)
    # and Postgres.
    with op.batch_alter_table('comentarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paso_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            'fk_comentarios_paso_id_pasos_tarea',
            'pasos_tarea',
            ['paso_id'],
            ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index(op.f('ix_comentarios_paso_id'), ['paso_id'], unique=False)

    # Purge old tarea-level comments: first their polymorphic Imagen rows,
    # then the comments themselves. (Physical comment-image files under
    # storage/comentarios/* are orphaned on disk — clean manually if needed.)
    op.execute("DELETE FROM imagenes WHERE imageable_type = 'Comentario'")
    op.execute("DELETE FROM comentarios")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('comentarios', schema=None) as batch_op:
        batch_op.drop_index(op.f('ix_comentarios_paso_id'))
        batch_op.drop_constraint('fk_comentarios_paso_id_pasos_tarea', type_='foreignkey')
        batch_op.drop_column('paso_id')
