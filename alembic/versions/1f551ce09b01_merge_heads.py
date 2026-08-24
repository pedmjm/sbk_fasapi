"""merge-heads

Revision ID: 1f551ce09b01
Revises: xxxx, f9855e965b95
Create Date: 2026-08-23 11:23:10.919867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f551ce09b01'
down_revision: Union[str, Sequence[str], None] = ('xxxx', 'f9855e965b95')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
