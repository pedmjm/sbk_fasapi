"""add tarea_herramienta_estado table

Revision ID: xxxx
Revises: d745d4f9b22b
Create Date: 2026-08-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'xxxx'
down_revision: Union[str, Sequence[str], None] = 'd745d4f9b22b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # op.create_table(
    #     'tarea_herramienta_estado',
    #     sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
    #     sa.Column('tarea_id', UUID(as_uuid=True), nullable=False),
    #     sa.Column('herramienta_id', UUID(as_uuid=True), nullable=False),
    #     sa.Column('personal_id', UUID(as_uuid=True), nullable=True),
    #     sa.Column('estado', sa.String(50), nullable=False, server_default='asignada'),
    #     sa.Column('fecha_inicio', sa.DateTime(timezone=True), server_default=sa.func.now()),
    #     sa.Column('fecha_fin', sa.DateTime(timezone=True), nullable=True),
    #     sa.Column('observaciones', sa.Text, nullable=True),
    #     sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    #     sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    #     sa.ForeignKeyConstraint(['tarea_id'], ['tareas.id'], ondelete='CASCADE'),
    #     sa.ForeignKeyConstraint(['herramienta_id'], ['herramientas.id'], ondelete='CASCADE'),
    #     sa.ForeignKeyConstraint(['personal_id'], ['personals.id'], ondelete='SET NULL'),
    # )
    op.create_index('ix_tarea_herramienta_estado_tarea_id', 'tarea_herramienta_estado', ['tarea_id'])
    op.create_index('ix_tarea_herramienta_estado_herramienta_id', 'tarea_herramienta_estado', ['herramienta_id'])
    op.create_index('ix_tarea_herramienta_estado_estado', 'tarea_herramienta_estado', ['estado'])

    # Tabla similar para consumibles
    op.create_table(
        'tarea_consumible_estado',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('tarea_id', UUID(as_uuid=True), nullable=False),
        sa.Column('consumible_id', UUID(as_uuid=True), nullable=False),
        sa.Column('personal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('estado', sa.String(50), nullable=False, server_default='asignado'),
        sa.Column('fecha_inicio', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('fecha_fin', sa.DateTime(timezone=True), nullable=True),
        sa.Column('observaciones', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['tarea_id'], ['tareas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['consumible_id'], ['consumibles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['personal_id'], ['personals.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_tarea_consumible_estado_tarea_id', 'tarea_consumible_estado', ['tarea_id'])
    op.create_index('ix_tarea_consumible_estado_consumible_id', 'tarea_consumible_estado', ['consumible_id'])
    op.create_index('ix_tarea_consumible_estado_estado', 'tarea_consumible_estado', ['estado'])

def downgrade() -> None:
    op.drop_table('tarea_consumible_estado')
    op.drop_table('tarea_herramienta_estado')