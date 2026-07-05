"""merge_test_and_workflows_ui

Revision ID: f7df23ff0c1d
Revises: 0f876fc3e07a, cb3c4680571b
Create Date: 2026-07-05 17:28:38.494637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7df23ff0c1d'
down_revision: Union[str, None] = ('0f876fc3e07a', 'cb3c4680571b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
