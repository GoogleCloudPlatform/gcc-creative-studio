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

"""update_unified_gallery_view_external_url

Revision ID: 7a8b9c0d1e2f
Revises: 582bbd507011
Create Date: 2026-07-15 03:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, None] = "582bbd507011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS unified_gallery_view;")
    op.execute(
        """
    CREATE VIEW unified_gallery_view AS
    WITH unified_base AS (
        SELECT
            mi.id,
            mi.workspace_id,
            mi.user_id,
            mi.created_at,
            'media_item'::text AS item_type,
            mi.status,
            mi.gcs_uris,
            mi.thumbnail_uris,
            mi.deleted_at,
            mi.titles,
            mi.descriptions,
            jsonb_build_object(
                'model', mi.model,
                'prompt', mi.prompt,
                'original_prompt', mi.original_prompt,
                'negative_prompt', mi.negative_prompt,
                'aspect_ratio', mi.aspect_ratio,
                'mime_type', mi.mime_type,
                'style', mi.style,
                'lighting', mi.lighting,
                'num_media', mi.num_media,
                'generation_time', mi.generation_time,
                'file_name', mi.comment,
                'source_assets', mi.source_assets,
                'source_media_items', mi.source_media_items,
                'is_video', (mi.mime_type LIKE 'video%'),
                'is_audio', (mi.mime_type LIKE 'audio%'),
                'tags', (
                    SELECT jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name, 'color', t.color, 'workspace_id', t.workspace_id))
                    FROM media_item_tags mit
                    JOIN tags t ON mit.tag_id = t.id
                    WHERE mit.media_item_id = mi.id
                )
            ) AS metadata
        FROM media_items mi
        UNION ALL
        SELECT
            sa.id,
            sa.workspace_id,
            sa.user_id,
            sa.created_at,
            'source_asset'::text AS item_type,
            'completed'::text AS status,
            CASE
                WHEN (sa.gcs_uri IS NOT NULL) THEN ARRAY[sa.gcs_uri]
                ELSE '{}'::text[]
            END AS gcs_uris,
            CASE
                WHEN (sa.thumbnail_gcs_uri IS NOT NULL) THEN ARRAY[sa.thumbnail_gcs_uri]
                ELSE '{}'::text[]
            END AS thumbnail_uris,
            sa.deleted_at,
            sa.titles,
            sa.descriptions,
            jsonb_build_object(
                'file_name', sa.original_filename,
                'original_filename', sa.original_filename,
                'mime_type', sa.mime_type,
                'aspect_ratio', sa.aspect_ratio,
                'asset_type', sa.asset_type,
                'external_url', sa.external_url,
                'is_video', (sa.mime_type LIKE 'video%' OR sa.asset_type = 'youtube_video' OR sa.external_url IS NOT NULL),
                'is_audio', (sa.mime_type LIKE 'audio%'),
                'tags', (
                    SELECT jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name, 'color', t.color, 'workspace_id', t.workspace_id))
                    FROM source_asset_tags sat
                    JOIN tags t ON sat.tag_id = t.id
                    WHERE sat.source_asset_id = sa.id
                )
            ) AS metadata
        FROM source_assets sa
    )
    SELECT 
        ub.*,
        w.name AS workspace_name,
        u.picture AS user_picture,
        u.email AS user_email
    FROM unified_base ub
    LEFT JOIN workspaces w ON ub.workspace_id = w.id
    LEFT JOIN users u ON ub.user_id = u.id;
    """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS unified_gallery_view;")
    op.execute(
        """
    CREATE VIEW unified_gallery_view AS
    SELECT
        mi.id,
        mi.workspace_id,
        mi.user_id,
        mi.created_at,
        'media_item'::text AS item_type,
        mi.status,
        mi.gcs_uris,
        mi.thumbnail_uris,
        mi.deleted_at,
        w.name AS workspace_name,
        u.picture AS user_picture,
        u.email AS user_email,
        mi.titles,
        mi.descriptions,
        jsonb_build_object(
            'model', mi.model,
            'prompt', mi.prompt,
            'original_prompt', mi.original_prompt,
            'negative_prompt', mi.negative_prompt,
            'aspect_ratio', mi.aspect_ratio,
            'mime_type', mi.mime_type,
            'style', mi.style,
            'lighting', mi.lighting,
            'num_media', mi.num_media,
            'generation_time', mi.generation_time,
            'file_name', mi.comment,
            'source_assets', mi.source_assets,
            'source_media_items', mi.source_media_items,
            'is_video', (mi.mime_type like 'video%'),
            'is_audio', (mi.mime_type like 'audio%'),
            'tags', (
                SELECT jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name, 'color', t.color, 'workspace_id', t.workspace_id))
                FROM media_item_tags mit
                JOIN tags t ON mit.tag_id = t.id
                WHERE mit.media_item_id = mi.id
            )
        ) AS metadata
    FROM media_items mi
    LEFT JOIN workspaces w ON mi.workspace_id = w.id
    LEFT JOIN users u ON mi.user_id = u.id
    UNION ALL
    SELECT
        sa.id,
        sa.workspace_id,
        sa.user_id,
        sa.created_at,
        'source_asset'::text AS item_type,
        'completed'::text AS status,
        ARRAY[sa.gcs_uri] AS gcs_uris,
        CASE
            WHEN (sa.thumbnail_gcs_uri IS NOT NULL) THEN ARRAY[sa.thumbnail_gcs_uri]
            ELSE '{}'::text[]
        END AS thumbnail_uris,
        sa.deleted_at,
        w.name AS workspace_name,
        u.picture AS user_picture,
        u.email AS user_email,
        sa.titles,
        sa.descriptions,
        jsonb_build_object(
            'file_name', sa.original_filename,
            'original_filename', sa.original_filename,
            'mime_type', sa.mime_type,
            'aspect_ratio', sa.aspect_ratio,
            'asset_type', sa.asset_type,
            'is_video', (sa.mime_type like 'video%'),
            'is_audio', (sa.mime_type like 'audio%'),
            'tags', (
                SELECT jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name, 'color', t.color, 'workspace_id', t.workspace_id))
                FROM source_asset_tags sat
                JOIN tags t ON sat.tag_id = t.id
                WHERE sat.source_asset_id = sa.id
            )
        ) AS metadata
    FROM source_assets sa
    LEFT JOIN workspaces w ON sa.workspace_id = w.id
    LEFT JOIN users u ON sa.user_id = u.id;
    """
    )
