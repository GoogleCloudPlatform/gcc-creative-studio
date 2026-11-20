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

"""Add composite partial indexes for gallery load queries.

Revision ID: c8f4a2e91d05
Revises: b7e2d9c4f1a3
Create Date: 2026-11-15 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f4a2e91d05"
down_revision: Union[str, None] = "b7e2d9c4f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GALLERY_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_media_items_ws_created_active",
        """
        CREATE INDEX IF NOT EXISTS ix_media_items_ws_created_active
        ON media_items (workspace_id, created_at DESC, id DESC)
        WHERE deleted_at IS NULL
        """,
    ),
    (
        "ix_media_items_ws_folder_created_active",
        """
        CREATE INDEX IF NOT EXISTS ix_media_items_ws_folder_created_active
        ON media_items (workspace_id, folder_id, created_at DESC, id DESC)
        WHERE deleted_at IS NULL
        """,
    ),
    (
        "ix_media_items_ws_folder_status_created_active",
        """
        CREATE INDEX IF NOT EXISTS
            ix_media_items_ws_folder_status_created_active
        ON media_items (
            workspace_id, folder_id, status, created_at DESC, id DESC
        )
        WHERE deleted_at IS NULL
        """,
    ),
    (
        "ix_media_items_ws_status_created_active",
        """
        CREATE INDEX IF NOT EXISTS ix_media_items_ws_status_created_active
        ON media_items (workspace_id, status, created_at DESC, id DESC)
        WHERE deleted_at IS NULL
        """,
    ),
    (
        "ix_source_assets_ws_created_active",
        """
        CREATE INDEX IF NOT EXISTS ix_source_assets_ws_created_active
        ON source_assets (workspace_id, created_at DESC, id DESC)
        WHERE deleted_at IS NULL
        """,
    ),
    (
        "ix_source_assets_ws_folder_created_active",
        """
        CREATE INDEX IF NOT EXISTS ix_source_assets_ws_folder_created_active
        ON source_assets (workspace_id, folder_id, created_at DESC, id DESC)
        WHERE deleted_at IS NULL
        """,
    ),
    (
        "ix_media_item_tags_tag_id",
        """
        CREATE INDEX IF NOT EXISTS ix_media_item_tags_tag_id
        ON media_item_tags (tag_id, media_item_id)
        """,
    ),
    (
        "ix_source_asset_tags_tag_id",
        """
        CREATE INDEX IF NOT EXISTS ix_source_asset_tags_tag_id
        ON source_asset_tags (tag_id, source_asset_id)
        """,
    ),
)


def upgrade() -> None:
    """Create partial composite and tag-lookup indexes for gallery queries."""
    for _, create_sql in _GALLERY_INDEXES:
        op.execute(create_sql)


def downgrade() -> None:
    """Drop gallery performance indexes."""
    for index_name, _ in reversed(_GALLERY_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
