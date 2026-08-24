"""merge-heads

Revision ID: 9154bbf62cc3
Revises: 1f551ce09b01
Create Date: 2026-08-23 11:27:27.384515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9154bbf62cc3'
down_revision: Union[str, Sequence[str], None] = '1f551ce09b01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
