"""add tarea_consumible table

Revision ID: d745d4f9b22b
Revises: c9c07b578bab
Create Date: 2026-08-22 22:34:02.954981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd745d4f9b22b'
down_revision: Union[str, Sequence[str], None] = 'c9c07b578bab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    ...


def downgrade() -> None:
    ...