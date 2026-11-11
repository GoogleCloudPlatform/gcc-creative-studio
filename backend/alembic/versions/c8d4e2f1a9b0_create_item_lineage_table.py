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

"""create_item_lineage_table

Revision ID: c8d4e2f1a9b0
Revises: b7e2d9c4f1a3
Create Date: 2026-11-11 00:05:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d4e2f1a9b0"
down_revision: str | None = "b7e2d9c4f1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_ITEM_LINEAGE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM item_lineage LIMIT 1) THEN
        INSERT INTO item_lineage (
            workspace_id,
            child_type,
            child_id,
            child_index,
            parent_type,
            parent_id,
            parent_index,
            role,
            is_primary_parent,
            action_summary,
            created_at
        )
        WITH raw_edges AS (
            SELECT
                mi.workspace_id,
                'media_item'::varchar(16) AS child_type,
                mi.id AS child_id,
                'source_asset'::varchar(16) AS parent_type,
                CASE
                    WHEN COALESCE(sa_elem->>'asset_id', sa_elem->>'assetId', '') ~ '^[0-9]{1,10}$' THEN
                        CASE
                            WHEN COALESCE(sa_elem->>'asset_id', sa_elem->>'assetId')::bigint
                                 BETWEEN 1 AND 2147483647
                            THEN COALESCE(sa_elem->>'asset_id', sa_elem->>'assetId')::integer
                        END
                END AS parent_id,
                0 AS parent_index,
                LEFT(
                    COALESCE(NULLIF(btrim(sa_elem->>'role'), ''), 'input'),
                    64
                ) AS raw_role,
                mi.mime_type,
                mi.model,
                mi.original_prompt,
                mi.prompt,
                mi.comment,
                mi.audio_analysis,
                mi.created_at
            FROM media_items mi
            INNER JOIN workspaces w ON w.id = mi.workspace_id
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(mi.source_assets) = 'array' THEN mi.source_assets
                    ELSE '[]'::jsonb
                END
            ) AS sa_elem
            WHERE jsonb_typeof(sa_elem) = 'object'
            UNION ALL
            SELECT
                mi.workspace_id,
                'media_item'::varchar(16) AS child_type,
                mi.id AS child_id,
                'media_item'::varchar(16) AS parent_type,
                CASE
                    WHEN COALESCE(smi_elem->>'media_item_id', smi_elem->>'mediaItemId', '') ~ '^[0-9]{1,10}$' THEN
                        CASE
                            WHEN COALESCE(smi_elem->>'media_item_id', smi_elem->>'mediaItemId')::bigint
                                 BETWEEN 1 AND 2147483647
                            THEN COALESCE(smi_elem->>'media_item_id', smi_elem->>'mediaItemId')::integer
                        END
                END AS parent_id,
                CASE
                    WHEN COALESCE(smi_elem->>'media_index', smi_elem->>'mediaIndex', '') ~ '^[0-9]{1,10}$' THEN
                        CASE
                            WHEN COALESCE(smi_elem->>'media_index', smi_elem->>'mediaIndex')::bigint
                                 BETWEEN 0 AND 2147483647
                            THEN COALESCE(smi_elem->>'media_index', smi_elem->>'mediaIndex')::integer
                            ELSE 0
                        END
                    ELSE 0
                END AS parent_index,
                LEFT(
                    COALESCE(NULLIF(btrim(smi_elem->>'role'), ''), 'input'),
                    64
                ) AS raw_role,
                mi.mime_type,
                mi.model,
                mi.original_prompt,
                mi.prompt,
                mi.comment,
                mi.audio_analysis,
                mi.created_at
            FROM media_items mi
            INNER JOIN workspaces w ON w.id = mi.workspace_id
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(mi.source_media_items) = 'array' THEN mi.source_media_items
                    ELSE '[]'::jsonb
                END
            ) AS smi_elem
            WHERE jsonb_typeof(smi_elem) = 'object'
        ),
        deduped AS (
            SELECT DISTINCT ON (
                workspace_id,
                child_type,
                child_id,
                parent_type,
                parent_id,
                parent_index,
                raw_role
            )
                *
            FROM raw_edges
            WHERE parent_id IS NOT NULL
              AND parent_id > 0
              AND NOT (parent_type = child_type AND parent_id = child_id)
        ),
        counted AS (
            SELECT
                d.*,
                COUNT(*) OVER (
                    PARTITION BY d.workspace_id, d.child_type, d.child_id
                ) AS edge_count,
                COUNT(*) FILTER (WHERE d.raw_role = 'audio_reference') OVER (
                    PARTITION BY d.workspace_id, d.child_type, d.child_id
                ) AS audio_ref_count,
                COUNT(*) FILTER (WHERE d.raw_role = 'video_extension_source') OVER (
                    PARTITION BY d.workspace_id, d.child_type, d.child_id
                ) AS video_ext_count,
                COUNT(*) FILTER (WHERE d.raw_role = 'video_reference') OVER (
                    PARTITION BY d.workspace_id, d.child_type, d.child_id
                ) AS video_ref_count
            FROM deduped d
        ),
        classified AS (
            SELECT
                c.*,
                CASE
                    WHEN c.raw_role IN (
                        'concatenation_source',
                        'vto_person',
                        'vto_top',
                        'vto_bottom',
                        'vto_dress',
                        'vto_shoe',
                        'mask'
                    ) THEN FALSE
                    WHEN c.model IN ('htdemucs_6s', 'htdemucs-6s')
                     AND c.raw_role = 'audio_reference'
                     AND c.audio_ref_count = 1 THEN TRUE
                    WHEN c.mime_type LIKE 'audio/%'
                     AND c.raw_role = 'audio_reference'
                     AND c.audio_ref_count = 1 THEN TRUE
                    WHEN c.mime_type LIKE 'audio/%'
                     AND c.audio_ref_count >= 1
                     AND c.raw_role <> 'audio_reference' THEN FALSE
                    WHEN c.edge_count = 1 THEN TRUE
                    WHEN c.raw_role = 'video_extension_source'
                     AND c.video_ext_count = 1 THEN TRUE
                    WHEN c.mime_type LIKE 'video/%'
                     AND c.video_ext_count = 0
                     AND c.raw_role = 'video_reference'
                     AND c.video_ref_count = 1 THEN TRUE
                    ELSE FALSE
                END AS is_primary
            FROM counted c
        )
        SELECT
            workspace_id,
            child_type,
            child_id,
            NULL::integer AS child_index,
            parent_type,
            parent_id,
            parent_index,
            LEFT(
                CASE
                    WHEN is_primary AND model IN ('htdemucs_6s', 'htdemucs-6s') AND raw_role = 'audio_reference' THEN 'audio_stem_source'
                    WHEN is_primary AND mime_type LIKE 'audio/%' AND raw_role = 'audio_reference' THEN 'audio_iteration_source'
                    WHEN is_primary AND original_prompt = 'Upscale Job' THEN 'upscale_source'
                    WHEN is_primary AND mime_type LIKE 'image/%' AND raw_role = 'input' THEN 'image_edit_source'
                    ELSE raw_role
                END,
                64
            ) AS role,
            is_primary AS is_primary_parent,
            CASE
                WHEN NOT is_primary THEN NULL
                WHEN model IN ('htdemucs_6s', 'htdemucs-6s') THEN COALESCE(
                    CASE
                        WHEN jsonb_typeof(audio_analysis) = 'object' THEN
                            CASE
                                WHEN jsonb_typeof(audio_analysis->'iteration_steps') = 'array'
                                THEN NULLIF(btrim((audio_analysis->'iteration_steps')->>-1), '')
                            END
                    END,
                    NULLIF(btrim(comment), ''),
                    'Isolated audio stems'
                )
                WHEN original_prompt = 'Upscale Job' THEN 'Upscaled image'
                ELSE COALESCE(
                    NULLIF(btrim(original_prompt), ''),
                    NULLIF(btrim(prompt), ''),
                    CASE
                        WHEN raw_role = 'video_extension_source' THEN 'Extended video'
                        ELSE 'Edited media'
                    END
                )
            END AS action_summary,
            created_at
        FROM classified;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'Skipping non-critical item_lineage backfill (%): %', SQLSTATE, SQLERRM;
END
$$;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS item_lineage (
            id SERIAL PRIMARY KEY,
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            child_type VARCHAR(16) NOT NULL,
            child_id INTEGER NOT NULL,
            child_index INTEGER DEFAULT NULL,
            parent_type VARCHAR(16) NOT NULL,
            parent_id INTEGER NOT NULL,
            parent_index INTEGER NOT NULL DEFAULT 0,
            role VARCHAR(64) NOT NULL,
            is_primary_parent BOOLEAN NOT NULL DEFAULT FALSE,
            action_summary TEXT DEFAULT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Best-effort historical backfill isolated in a PL/pgSQL savepoint BEFORE
    # building indexes (avoids per-row B-tree maintenance and guarantees that
    # malformed historical JSONB can never block container startup).
    op.execute(BACKFILL_ITEM_LINEAGE_SQL)

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_item_lineage_child
        ON item_lineage (workspace_id, child_type, child_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_item_lineage_parent
        ON item_lineage (workspace_id, parent_type, parent_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_item_lineage_parent;")
    op.execute("DROP INDEX IF EXISTS ix_item_lineage_child;")
    op.execute("DROP TABLE IF EXISTS item_lineage;")
