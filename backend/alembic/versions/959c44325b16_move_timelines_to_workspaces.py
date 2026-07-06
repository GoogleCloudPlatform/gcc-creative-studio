"""move_timelines_to_workspaces

Revision ID: 959c44325b16
Revises: 0f876fc3e07a
Create Date: 2026-07-03 18:25:46.555173

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '959c44325b16'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the pre-existing workspace_id String column added by c3d4e5f6a7b8
    op.drop_column('timelines', 'workspace_id')

    # 2. Add workspace_id column as Integer FK nullable initially
    op.add_column('timelines', sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', name='timelines_workspace_id_fkey'), nullable=True))
    
    # 3. Populate workspace_id from storyboards
    op.execute(
        "UPDATE timelines SET workspace_id = storyboards.workspace_id "
        "FROM storyboards WHERE timelines.storyboard_id = storyboards.id"
    )
    
    # 4. Alter workspace_id to NOT NULL
    op.alter_column('timelines', 'workspace_id', nullable=False)
    
    # 5. Make storyboard_id nullable
    op.alter_column('timelines', 'storyboard_id', nullable=True)
    
    # 6. Add unique constraint on storyboard_id
    op.create_unique_constraint('uq_timelines_storyboard_id', 'timelines', ['storyboard_id'])


def downgrade() -> None:
    # 1. Drop unique constraint
    op.drop_constraint('uq_timelines_storyboard_id', 'timelines', type_='unique')
    
    # 2. Clean up timelines that have null storyboard_id
    op.execute("DELETE FROM timelines WHERE storyboard_id IS NULL")
    
    # 3. Make storyboard_id NOT NULL
    op.alter_column('timelines', 'storyboard_id', nullable=False)
    
    # 4. Drop workspace_id column
    op.drop_constraint('timelines_workspace_id_fkey', 'timelines', type_='foreignkey')
    op.drop_column('timelines', 'workspace_id')

    # 5. Re-add workspace_id as String to restore c3d4e5f6a7b8 state
    op.add_column('timelines', sa.Column('workspace_id', sa.String(), nullable=True))
