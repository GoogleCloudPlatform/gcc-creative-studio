# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""enforce_unique_folder_names

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-26 07:35:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Disambiguate any existing duplicate active subfolder names (parent_id IS NOT NULL)
    op.execute(
        """
        WITH numbered_subfolders AS (
            SELECT 
                id, 
                name, 
                ROW_NUMBER() OVER (
                    PARTITION BY workspace_id, parent_id, LOWER(TRIM(name)) 
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM folders
            WHERE parent_id IS NOT NULL AND deleted_at IS NULL
        )
        UPDATE folders
        SET name = numbered_subfolders.name || ' (' || (numbered_subfolders.rn - 1) || ')'
        FROM numbered_subfolders
        WHERE folders.id = numbered_subfolders.id AND numbered_subfolders.rn > 1;
        """
    )

    # 2. Disambiguate any existing duplicate active root folder names (parent_id IS NULL)
    op.execute(
        """
        WITH numbered_root_folders AS (
            SELECT 
                id, 
                name, 
                ROW_NUMBER() OVER (
                    PARTITION BY workspace_id, LOWER(TRIM(name)) 
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM folders
            WHERE parent_id IS NULL AND deleted_at IS NULL
        )
        UPDATE folders
        SET name = numbered_root_folders.name || ' (' || (numbered_root_folders.rn - 1) || ')'
        FROM numbered_root_folders
        WHERE folders.id = numbered_root_folders.id AND numbered_root_folders.rn > 1;
        """
    )

    # 3. Create partial unique index for active subfolders
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_folders_workspace_parent_name_active
        ON folders (workspace_id, parent_id, LOWER(TRIM(name)))
        WHERE parent_id IS NOT NULL AND deleted_at IS NULL;
        """
    )

    # 4. Create partial unique index for active root folders
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_folders_workspace_root_name_active
        ON folders (workspace_id, LOWER(TRIM(name)))
        WHERE parent_id IS NULL AND deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_folders_workspace_parent_name_active;")
    op.execute("DROP INDEX IF EXISTS uq_folders_workspace_root_name_active;")
