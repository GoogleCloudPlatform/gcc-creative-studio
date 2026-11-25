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

"""Add personal workspaces, revision stacks, and promotions schema.

Revision ID: c8f3a1b2d4e5
Revises: c8f4a2e91d05
Create Date: 2026-11-15 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c8f3a1b2d4e5"
down_revision: Union[str, None] = "c8f4a2e91d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enforce one personal workspace per user and backfill existing users.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_workspaces_personal_owner
        ON workspaces (owner_id)
        WHERE scope = 'personal';
        """
    )
    op.execute(
        """
        WITH inserted_ws AS (
            INSERT INTO workspaces (name, owner_id, scope)
            SELECT 'My Workspace', u.id, 'personal'
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1
                FROM workspaces w
                WHERE w.owner_id = u.id AND w.scope = 'personal'
            )
            RETURNING id, owner_id
        )
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT id, owner_id, 'owner'
        FROM inserted_ws
        ON CONFLICT DO NOTHING;
        """
    )

    # 2. Revision & promotion lineage columns on media_items.
    op.add_column(
        "media_items",
        sa.Column(
            "revision_root_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "media_items",
        sa.Column(
            "revision_parent_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "media_items",
        sa.Column(
            "revision_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "media_items",
        sa.Column(
            "promoted_from_media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "media_items",
        sa.Column(
            "promoted_from_root_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_media_items_revision_root_id",
        "media_items",
        ["revision_root_id"],
        unique=False,
    )
    op.create_index(
        "ix_media_items_revision_parent_id",
        "media_items",
        ["revision_parent_id"],
        unique=False,
    )
    op.create_index(
        "ix_media_items_promoted_from_media_item_id",
        "media_items",
        ["promoted_from_media_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_media_items_promoted_from_root_id",
        "media_items",
        ["promoted_from_root_id"],
        unique=False,
    )
    # Supports correlated latest-revision and stack-count lookups per page row
    # without preventing PK/id=ANY(...) predicate pushdown into unified_gallery_view.
    op.execute(
        """
        CREATE INDEX ix_media_items_stack_root_active
        ON media_items (
            workspace_id,
            COALESCE(revision_root_id, id),
            revision_number DESC,
            id DESC
        )
        WHERE deleted_at IS NULL AND status = 'completed';
        """
    )

    # 3. Promotion lineage column on source_assets.
    op.add_column(
        "source_assets",
        sa.Column(
            "promoted_from_source_asset_id",
            sa.Integer(),
            sa.ForeignKey("source_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_source_assets_promoted_from_source_asset_id",
        "source_assets",
        ["promoted_from_source_asset_id"],
        unique=False,
    )

    # 4. Recreate unified_gallery_view with revision stacks, promotions, and workspace scope/owner.
    # Avoids full-table WindowAgg so UnifiedGalleryRepository's branch id=ANY(...) pushes down cleanly.
    op.execute("DROP VIEW IF EXISTS unified_gallery_view;")
    op.execute(
        """
        CREATE VIEW unified_gallery_view AS
        WITH unified_base AS (
            SELECT
                mi.id,
                mi.workspace_id,
                mi.user_id,
                mi.folder_id,
                mi.created_at,
                'media_item'::text AS item_type,
                mi.status,
                mi.gcs_uris,
                mi.thumbnail_uris,
                mi.deleted_at,
                mi.titles,
                mi.descriptions,
                CASE
                    WHEN mi.deleted_at IS NULL AND mi.status = 'completed'
                    THEN NOT EXISTS (
                        SELECT 1
                        FROM media_items newer
                        WHERE newer.workspace_id = mi.workspace_id
                          AND COALESCE(newer.revision_root_id, newer.id) = COALESCE(mi.revision_root_id, mi.id)
                          AND newer.deleted_at IS NULL
                          AND newer.status = 'completed'
                          AND (
                              newer.revision_number > mi.revision_number
                              OR (
                                  newer.revision_number = mi.revision_number
                                  AND newer.id > mi.id
                              )
                          )
                    )
                    ELSE TRUE
                END AS is_latest_revision,
                mw.name AS workspace_name,
                mw.scope AS workspace_scope,
                mw.owner_id AS workspace_owner_id,
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
                    'revision_root_id', COALESCE(mi.revision_root_id, mi.id),
                    'revision_parent_id', mi.revision_parent_id,
                    'revision_number', mi.revision_number,
                    'revision_count', (
                        SELECT COUNT(*)::int
                        FROM media_items sibling
                        WHERE sibling.workspace_id = mi.workspace_id
                          AND COALESCE(sibling.revision_root_id, sibling.id) = COALESCE(mi.revision_root_id, mi.id)
                          AND sibling.deleted_at IS NULL
                          AND sibling.status = 'completed'
                    ),
                    'promotions', CASE
                        WHEN mw.scope = 'personal' THEN COALESCE(
                            (
                                SELECT jsonb_agg(
                                    jsonb_build_object(
                                        'target_workspace_id', pmi.workspace_id,
                                        'target_workspace_name', tw.name,
                                        'target_item_id', pmi.id,
                                        'target_folder_id', pmi.folder_id,
                                        'promoted_revision_number', src_mi.revision_number
                                    )
                                    ORDER BY pmi.updated_at DESC, pmi.id DESC
                                )
                                FROM media_items pmi
                                JOIN workspaces tw ON tw.id = pmi.workspace_id
                                LEFT JOIN media_items src_mi ON src_mi.id = pmi.promoted_from_media_item_id
                                WHERE pmi.promoted_from_root_id = COALESCE(mi.revision_root_id, mi.id)
                                  AND pmi.deleted_at IS NULL
                            ),
                            '[]'::jsonb
                        )
                        ELSE '[]'::jsonb
                    END,
                    'tags', (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'id', t.id,
                                'name', t.name,
                                'color', t.color,
                                'workspace_id', t.workspace_id
                            )
                        )
                        FROM media_item_tags mit
                        JOIN tags t ON mit.tag_id = t.id
                        WHERE mit.media_item_id = mi.id
                    )
                ) AS metadata
            FROM media_items mi
            LEFT JOIN workspaces mw ON mw.id = mi.workspace_id
            UNION ALL
            SELECT
                sa.id,
                sa.workspace_id,
                sa.user_id,
                sa.folder_id,
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
                TRUE AS is_latest_revision,
                sw.name AS workspace_name,
                sw.scope AS workspace_scope,
                sw.owner_id AS workspace_owner_id,
                jsonb_build_object(
                    'file_name', sa.original_filename,
                    'original_filename', sa.original_filename,
                    'mime_type', sa.mime_type,
                    'aspect_ratio', sa.aspect_ratio,
                    'asset_type', sa.asset_type,
                    'external_url', sa.external_url,
                    'is_video', (
                        sa.mime_type LIKE 'video%'
                        OR sa.asset_type = 'youtube_video'
                        OR sa.external_url IS NOT NULL
                    ),
                    'is_audio', (sa.mime_type LIKE 'audio%'),
                    'promotions', CASE
                        WHEN sw.scope = 'personal' THEN COALESCE(
                            (
                                SELECT jsonb_agg(
                                    jsonb_build_object(
                                        'target_workspace_id', psa.workspace_id,
                                        'target_workspace_name', tw.name,
                                        'target_item_id', psa.id,
                                        'target_folder_id', psa.folder_id,
                                        'promoted_revision_number', NULL
                                    )
                                    ORDER BY psa.updated_at DESC, psa.id DESC
                                )
                                FROM source_assets psa
                                JOIN workspaces tw ON tw.id = psa.workspace_id
                                WHERE psa.promoted_from_source_asset_id = sa.id
                                  AND psa.deleted_at IS NULL
                            ),
                            '[]'::jsonb
                        )
                        ELSE '[]'::jsonb
                    END,
                    'tags', (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'id', t.id,
                                'name', t.name,
                                'color', t.color,
                                'workspace_id', t.workspace_id
                            )
                        )
                        FROM source_asset_tags sat
                        JOIN tags t ON sat.tag_id = t.id
                        WHERE sat.source_asset_id = sa.id
                    )
                ) AS metadata
            FROM source_assets sa
            LEFT JOIN workspaces sw ON sw.id = sa.workspace_id
        )
        SELECT
            ub.*,
            u.picture AS user_picture,
            u.email AS user_email
        FROM unified_base ub
        LEFT JOIN users u ON ub.user_id = u.id;
        """
    )

    op.execute(
        """
        UPDATE timelines t
        SET workspace_id = s.workspace_id::text
        FROM storyboards s
        WHERE t.storyboard_id = s.id
          AND (t.workspace_id IS NULL OR BTRIM(t.workspace_id) = '');
        """
    )


def downgrade() -> None:
    # 1. Restore previous unified_gallery_view (as of d4e5f6a7b8c9 / c8f4a2e91d05).
    op.execute("DROP VIEW IF EXISTS unified_gallery_view;")
    op.execute(
        """
        CREATE VIEW unified_gallery_view AS
        WITH unified_base AS (
            SELECT
                mi.id,
                mi.workspace_id,
                mi.user_id,
                mi.folder_id,
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
                sa.folder_id,
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

    # 2. Drop promotion lineage column on source_assets.
    op.drop_index(
        "ix_source_assets_promoted_from_source_asset_id",
        table_name="source_assets",
    )
    op.drop_column("source_assets", "promoted_from_source_asset_id")

    # 3. Drop revision & promotion lineage indexes and columns on media_items.
    op.execute("DROP INDEX IF EXISTS ix_media_items_stack_root_active;")
    op.drop_index(
        "ix_media_items_promoted_from_root_id", table_name="media_items"
    )
    op.drop_index(
        "ix_media_items_promoted_from_media_item_id",
        table_name="media_items",
    )
    op.drop_index("ix_media_items_revision_parent_id", table_name="media_items")
    op.drop_index("ix_media_items_revision_root_id", table_name="media_items")
    op.drop_column("media_items", "promoted_from_root_id")
    op.drop_column("media_items", "promoted_from_media_item_id")
    op.drop_column("media_items", "revision_number")
    op.drop_column("media_items", "revision_parent_id")
    op.drop_column("media_items", "revision_root_id")

    # 4. Clean up personal workspaces before dropping personal unique index.
    # Keep non-empty personal workspaces as 'private' and ensure owner membership exists.
    # Note: workflows.workspace_id was dropped in revision 488846b86e90.
    inspector = sa.inspect(op.get_bind())
    extra_empty_clauses = []
    if inspector.has_table("projects"):
        extra_empty_clauses.append(
            "        AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.workspace_id = w.id)"
        )
    if inspector.has_table("agent_sessions"):
        extra_empty_clauses.append(
            "        AND NOT EXISTS (SELECT 1 FROM agent_sessions ags WHERE ags.workspace_id = w.id)"
        )
    extra_sql = ("\n" + "\n".join(extra_empty_clauses)) if extra_empty_clauses else ""
    _empty_personal_ws_filter = f"""
        w.scope = 'personal'
        AND NOT EXISTS (SELECT 1 FROM media_items mi WHERE mi.workspace_id = w.id)
        AND NOT EXISTS (SELECT 1 FROM source_assets sa WHERE sa.workspace_id = w.id)
        AND NOT EXISTS (SELECT 1 FROM folders f WHERE f.workspace_id = w.id)
        AND NOT EXISTS (SELECT 1 FROM tags t WHERE t.workspace_id = w.id)
        AND NOT EXISTS (SELECT 1 FROM brand_guidelines bg WHERE bg.workspace_id = w.id)
        AND NOT EXISTS (SELECT 1 FROM storyboards sb WHERE sb.workspace_id = w.id)
        AND NOT EXISTS (SELECT 1 FROM timelines tl WHERE tl.workspace_id = w.id::text){extra_sql}
    """
    op.execute(
        f"""
        DELETE FROM workspace_members
        WHERE workspace_id IN (
            SELECT w.id
            FROM workspaces w
            WHERE {_empty_personal_ws_filter}
        );
        """
    )
    op.execute(
        f"""
        DELETE FROM workspaces w
        WHERE {_empty_personal_ws_filter};
        """
    )
    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT w.id, w.owner_id, 'owner'
        FROM workspaces w
        WHERE w.scope = 'personal'
          AND w.owner_id IS NOT NULL
        ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = 'owner';
        """
    )
    op.execute(
        """
        UPDATE workspaces
        SET scope = 'private'
        WHERE scope = 'personal';
        """
    )

    # 5. Drop personal workspace partial unique index.
    op.execute("DROP INDEX IF EXISTS uq_workspaces_personal_owner;")
