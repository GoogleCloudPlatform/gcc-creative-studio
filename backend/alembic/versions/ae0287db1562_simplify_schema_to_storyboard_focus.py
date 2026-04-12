"""simplify schema to storyboard focus

Revision ID: ae0287db1562
Revises: 6fe30cbfe2c2
Create Date: 2026-04-12 16:05:05.696898

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae0287db1562'
down_revision: Union[str, Sequence[str], None] = ('6fe30cbfe2c2', '5ec709cf70e9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alter kept tables
    op.add_column('storyboards', sa.Column('user_id', sa.Integer(), nullable=False))
    op.add_column('storyboards', sa.Column('workspace_id', sa.Integer(), nullable=False))
    op.create_foreign_key('storyboards_workspace_id_fkey', 'storyboards', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('storyboards_user_id_fkey', 'storyboards', 'users', ['user_id'], ['id'])
    op.drop_column('storyboards', 'project_id')
    
    op.add_column('timelines', sa.Column('storyboard_id', sa.Integer(), nullable=False))
    op.create_foreign_key('timelines_storyboard_id_fkey', 'timelines', 'storyboards', ['storyboard_id'], ['id'])
    op.drop_column('timelines', 'project_id')



def downgrade() -> None:
    # Restore timelines columns and constraints
    op.add_column('timelines', sa.Column('project_id', sa.INTEGER(), autoincrement=False, nullable=False))
    op.drop_constraint('timelines_storyboard_id_fkey', 'timelines', type_='foreignkey')
    op.create_foreign_key('timelines_project_id_fkey', 'timelines', 'projects', ['project_id'], ['id'])
    op.drop_column('timelines', 'storyboard_id')

    # Restore storyboards columns and constraints
    op.add_column('storyboards', sa.Column('project_id', sa.INTEGER(), autoincrement=False, nullable=False))
    op.drop_constraint('storyboards_workspace_id_fkey', 'storyboards', type_='foreignkey')
    op.drop_constraint('storyboards_user_id_fkey', 'storyboards', type_='foreignkey')
    op.create_foreign_key('storyboards_project_id_fkey', 'storyboards', 'projects', ['project_id'], ['id'])
    op.drop_column('storyboards', 'workspace_id')
    op.drop_column('storyboards', 'user_id')

