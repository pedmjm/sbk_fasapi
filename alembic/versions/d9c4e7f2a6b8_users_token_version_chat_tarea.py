"""users token_version + chat por tarea

Revision ID: d9c4e7f2a6b8
Revises: 920487cf0ac1
Create Date: 2026-09-02 00:00:00.000000

  * `users.token_version` (Integer, NOT NULL, default 0) — bumped to
    invalidate all of a user's outstanding JWTs (deactivation / password
    change). Tokens minted before the `ver` claim count as version 0.
  * `chat_mensajes` — persistent history of the per-tarea chat rooms
    (WebSocket `/ws/tareas/{tarea_id}` in `routers/chat.py`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9c4e7f2a6b8'
down_revision: Union[str, Sequence[str], None] = '920487cf0ac1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch mode so it works on SQLite (table recreate) and Postgres alike.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('token_version', sa.Integer(), nullable=False, server_default='0')
        )

    op.create_table('chat_mensajes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tarea_id', sa.Uuid(), nullable=False),
    sa.Column('autor_id', sa.Uuid(), nullable=False),
    sa.Column('contenido', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tarea_id'], ['tareas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['autor_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chat_mensajes_tarea_id'), 'chat_mensajes', ['tarea_id'], unique=False)
    op.create_index(op.f('ix_chat_mensajes_autor_id'), 'chat_mensajes', ['autor_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_chat_mensajes_autor_id'), table_name='chat_mensajes')
    op.drop_index(op.f('ix_chat_mensajes_tarea_id'), table_name='chat_mensajes')
    op.drop_table('chat_mensajes')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('token_version')
