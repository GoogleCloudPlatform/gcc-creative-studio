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
"""Integration test for Alembic migration c8d4e2f1a9b0 (item_lineage).

Runs against a throwaway database on the local Postgres server, leaving the
application database untouched, and skips cleanly if Postgres is unavailable.
"""

import asyncio
from collections.abc import Callable, Iterator
import concurrent.futures
import json
import logging
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import asyncpg
import pytest

from src.config.config_service import config_service
from src.database import get_conn_string

logger = logging.getLogger(__name__)
T = TypeVar("T")

BACKEND_DIR = Path(__file__).resolve().parents[2]
REVISION = "c8d4e2f1a9b0"
DOWN_REVISION = "b7e2d9c4f1a3"
THROWAWAY_DB = "creative_studio_lineage_migration_test"
MAINTENANCE_DB = "postgres"
CONNECT_TIMEOUT_SECONDS = 5
DROP_THROWAWAY_SQL = f'DROP DATABASE IF EXISTS "{THROWAWAY_DB}" WITH (FORCE)'

DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


def _in_worker_thread(func: Callable[..., T], *args: Any) -> T:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(func, *args).result()


async def _connect(database: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        user=config_service.DB_USER,
        password=config_service.DB_PASS,
        host=config_service.DB_HOST,
        port=config_service.DB_PORT,
        database=database,
        timeout=CONNECT_TIMEOUT_SECONDS,
    )


async def _recreate_throwaway_db() -> None:
    conn = await _connect(MAINTENANCE_DB)
    try:
        await conn.execute(DROP_THROWAWAY_SQL)
        await conn.execute(f'CREATE DATABASE "{THROWAWAY_DB}"')
    finally:
        await conn.close()


async def _drop_throwaway_db() -> None:
    conn = await _connect(MAINTENANCE_DB)
    try:
        await conn.execute(DROP_THROWAWAY_SQL)
    finally:
        await conn.close()


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _migrate(action: Callable[[Config, str], None], revision: str) -> None:
    with patch.object(config_service, "DB_NAME", THROWAWAY_DB):
        if not get_conn_string().endswith(f"/{THROWAWAY_DB}"):
            raise RuntimeError("Refusing to migrate a non-throwaway database")
        action(_alembic_config(), revision)


async def _seed_legacy_media_items() -> dict[str, int]:
    conn = await _connect(THROWAWAY_DB)
    try:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('lineage-mig@example.com', ARRAY['user'], "
            "'Mig User', '') RETURNING id"
        )
        ws_id = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Lineage Test WS', $1, 'PRIVATE') RETURNING id",
            user_id,
        )
        asset_id = await conn.fetchval(
            "INSERT INTO source_assets (workspace_id, user_id, gcs_uri, "
            "original_filename, mime_type, aspect_ratio, file_hash, scope, "
            "asset_type) VALUES ($1, $2, 'gs://b/src.png', 'src.png', "
            "'image/png', '1:1', 'h1', 'private', 'generic_image') "
            "RETURNING id",
            ws_id,
            user_id,
        )

        # 1. Single-input image edit -> primary image_edit_source
        img_edit_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_email, mime_type, "
            "model, aspect_ratio, original_prompt, status, gcs_uris, "
            "thumbnail_uris, source_assets) "
            "VALUES ($1, 'lineage-mig@example.com', 'image/png', "
            "'gemini-2.5-flash-image', '1:1', 'Add warm sunset', 'completed', "
            "ARRAY['gs://b/img1.png'], ARRAY[]::text[], $2::jsonb) "
            "RETURNING id",
            ws_id,
            json.dumps([{"asset_id": asset_id, "role": "input"}]),
        )

        # 2. Single-input cross-modal video -> primary start_frame
        vid_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_email, mime_type, "
            "model, aspect_ratio, original_prompt, status, gcs_uris, "
            "thumbnail_uris, source_assets, source_media_items) "
            "VALUES ($1, 'lineage-mig@example.com', 'video/mp4', "
            "'veo-3.1-generate-001', '16:9', 'Gentle waves crashing', "
            "'completed', ARRAY['gs://b/vid1.mp4'], ARRAY[]::text[], "
            "'null'::jsonb, $2::jsonb) RETURNING id",
            ws_id,
            json.dumps(
                [
                    {
                        "media_item_id": img_edit_id,
                        "media_index": 0,
                        "role": "start_frame",
                    }
                ]
            ),
        )

        # 3. Video extension -> extension source primary, chunk secondary
        ext_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_email, mime_type, "
            "model, aspect_ratio, original_prompt, status, gcs_uris, "
            "thumbnail_uris, source_media_items) "
            "VALUES ($1, 'lineage-mig@example.com', 'video/mp4', "
            "'veo-3.1-generate-001', '16:9', 'Pan up to stars', 'completed', "
            "ARRAY['gs://b/ext1.mp4'], ARRAY[]::text[], $2::jsonb) "
            "RETURNING id",
            ws_id,
            json.dumps(
                [
                    {
                        "media_item_id": vid_id,
                        "media_index": 0,
                        "role": "video_extension_source",
                    },
                    {
                        "media_item_id": img_edit_id,
                        "media_index": 0,
                        "role": "video_extension_chunk",
                    },
                ]
            ),
        )

        # 4. Multi-input composition -> non-primary edges only
        comp_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_email, mime_type, "
            "model, aspect_ratio, original_prompt, status, gcs_uris, "
            "thumbnail_uris, source_assets, source_media_items) "
            "VALUES ($1, 'lineage-mig@example.com', 'image/png', "
            "'gemini-2.5-flash-image', '1:1', 'Blend both', 'completed', "
            "ARRAY['gs://b/comp1.png'], ARRAY[]::text[], $2::jsonb, "
            "$3::jsonb) RETURNING id",
            ws_id,
            json.dumps([{"asset_id": asset_id, "role": "input"}]),
            json.dumps(
                [
                    {
                        "media_item_id": img_edit_id,
                        "media_index": 0,
                        "role": "style_reference",
                    }
                ]
            ),
        )

        # 5. Audio iteration -> audio_iteration_source primary (with JSONB scalar 'null' in source_media_items)
        aud_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_email, mime_type, "
            "model, aspect_ratio, original_prompt, status, gcs_uris, "
            "thumbnail_uris, source_assets, source_media_items) "
            "VALUES ($1, 'lineage-mig@example.com', 'audio/mpeg', "
            "'lyria-3-pro-preview', '16:9', 'Add cello solo', 'completed', "
            "ARRAY['gs://b/aud1.mp3'], ARRAY[]::text[], $2::jsonb, "
            "'null'::jsonb) RETURNING id",
            ws_id,
            json.dumps([{"asset_id": asset_id, "role": "audio_reference"}]),
        )

        # 6. Adversarial legacy row: 13-digit epoch ID, 10-digit >INT32_MAX ID,
        # non-object JSONB scalars/nulls, >64-char role, and array audio_analysis
        long_role = "custom_role_" + ("x" * 90)
        adv_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_email, mime_type, "
            "model, aspect_ratio, original_prompt, status, gcs_uris, "
            "thumbnail_uris, source_assets, source_media_items, "
            "audio_analysis) "
            "VALUES ($1, 'lineage-mig@example.com', 'audio/mpeg', "
            "'htdemucs-6s', '16:9', 'Stem split', 'completed', "
            "ARRAY['gs://b/adv.mp3'], ARRAY[]::text[], "
            "$2::jsonb, $3::jsonb, '[\"not_an_object\"]'::jsonb) RETURNING id",
            ws_id,
            json.dumps(
                [
                    None,
                    "legacy-string-entry",
                    42,
                    {"asset_id": "1719999999999", "role": "input"},
                    {"asset_id": "9999999999", "role": "input"},
                    {"asset_id": asset_id, "role": long_role},
                ]
            ),
            json.dumps(
                [
                    ["nested_array"],
                    {
                        "media_item_id": "2147483648",
                        "media_index": "9999999999",
                        "role": "input",
                    },
                ]
            ),
        )

        return {
            "ws_id": ws_id,
            "asset_id": asset_id,
            "img_edit_id": img_edit_id,
            "vid_id": vid_id,
            "ext_id": ext_id,
            "comp_id": comp_id,
            "aud_id": aud_id,
            "adv_id": adv_id,
        }
    finally:
        await conn.close()


async def _inspect_upgraded(ids: dict[str, int]) -> dict[str, Any]:
    backfill_sql = (
        ScriptDirectory.from_config(_alembic_config())
        .get_revision(REVISION)
        .module.BACKFILL_ITEM_LINEAGE_SQL
    )
    conn = await _connect(THROWAWAY_DB)
    try:
        count_before_rerun = await conn.fetchval(
            "SELECT COUNT(*) FROM item_lineage"
        )
        # Re-executing the backfill SQL must be a strict no-op
        await conn.execute(backfill_sql)
        count_after_rerun = await conn.fetchval(
            "SELECT COUNT(*) FROM item_lineage"
        )

        rows = await conn.fetch(
            "SELECT child_type, child_id, parent_type, parent_id, "
            "parent_index, role, is_primary_parent, action_summary "
            "FROM item_lineage ORDER BY id ASC"
        )
        indexes = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'item_lineage'"
        )
        # Verify cycle protection on the recursive CTE directly
        await conn.execute(
            "INSERT INTO item_lineage (workspace_id, child_type, child_id, "
            "parent_type, parent_id, parent_index, role, is_primary_parent) "
            "VALUES ($1, 'media_item', 9001, 'media_item', 9002, 0, "
            "'input', TRUE), "
            "($1, 'media_item', 9002, 'media_item', 9001, 0, 'input', TRUE)",
            ids["ws_id"],
        )
        cte_sql = """
            WITH RECURSIVE primary_chain AS (
                SELECT il.id, il.child_type, il.child_id,
                       il.parent_type, il.parent_id, 1 AS depth,
                       ARRAY[
                           il.child_type || ':' || il.child_id::text,
                           il.parent_type || ':' || il.parent_id::text
                       ] AS visited
                FROM item_lineage il
                WHERE il.workspace_id = $1
                  AND il.child_type = 'media_item'
                  AND il.child_id = $2
                  AND il.is_primary_parent = TRUE
                UNION ALL
                SELECT p.id, p.child_type, p.child_id,
                       p.parent_type, p.parent_id, pc.depth + 1,
                       pc.visited || (
                           p.parent_type || ':' || p.parent_id::text
                       )
                FROM item_lineage p
                JOIN primary_chain pc
                  ON p.workspace_id = $1
                 AND p.child_type = pc.parent_type
                 AND p.child_id = pc.parent_id
                 AND p.is_primary_parent = TRUE
                WHERE pc.depth < 25
                  AND NOT (
                      (p.parent_type || ':' || p.parent_id::text)
                      = ANY(pc.visited)
                  )
            )
            SELECT child_type, child_id, parent_type, parent_id, depth
            FROM primary_chain ORDER BY depth DESC
        """
        cte_rows = await conn.fetch(cte_sql, ids["ws_id"], ids["ext_id"])
        cycle_rows = await conn.fetch(cte_sql, ids["ws_id"], 9001)
        return {
            "rows": [dict(r) for r in rows],
            "indexes": {r["indexname"] for r in indexes},
            "cte_rows": [dict(r) for r in cte_rows],
            "cycle_len": len(cycle_rows),
            "count_before_rerun": count_before_rerun,
            "count_after_rerun": count_after_rerun,
        }
    finally:
        await conn.close()


async def _table_exists() -> str | None:
    conn = await _connect(THROWAWAY_DB)
    try:
        return await conn.fetchval(
            "SELECT to_regclass('public.item_lineage')::text"
        )
    finally:
        await conn.close()


def _run_scenario() -> dict[str, Any]:
    _migrate(command.upgrade, DOWN_REVISION)
    ids = asyncio.run(_seed_legacy_media_items())

    _migrate(command.upgrade, REVISION)
    upgraded = asyncio.run(_inspect_upgraded(ids))

    _migrate(command.downgrade, DOWN_REVISION)
    downgraded_table = asyncio.run(_table_exists())

    _migrate(command.upgrade, REVISION)
    reupgraded_table = asyncio.run(_table_exists())

    return {
        "ids": ids,
        "upgraded": upgraded,
        "downgraded_table": downgraded_table,
        "reupgraded_table": reupgraded_table,
    }


def _skip_reason() -> str | None:
    if (
        config_service.INSTANCE_CONNECTION_NAME
        and not config_service.USE_CLOUD_SQL_AUTH_PROXY
    ):
        return "Cloud SQL connector configured; needs a direct Postgres."
    if config_service.DB_NAME == THROWAWAY_DB:
        return "DB_NAME is the throwaway database; refusing to recreate it."
    try:
        _in_worker_thread(asyncio.run, _recreate_throwaway_db())
    except DB_ERRORS as exc:
        return f"Postgres unavailable ({type(exc).__name__})."
    return None


@pytest.fixture(name="scenario", scope="module")
def fixture_scenario() -> Iterator[dict[str, Any]]:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    try:
        yield _in_worker_thread(_run_scenario)
    finally:
        try:
            _in_worker_thread(asyncio.run, _drop_throwaway_db())
        except DB_ERRORS as exc:
            logger.warning("Could not drop %s: %s", THROWAWAY_DB, exc)


def test_item_lineage_migration_backfill_cte_and_downgrade(scenario):
    ids = scenario["ids"]
    upgraded = scenario["upgraded"]

    assert {
        "ix_item_lineage_child",
        "ix_item_lineage_parent",
    } <= upgraded["indexes"]

    by_child: dict[int, list[dict[str, Any]]] = {}
    for row in upgraded["rows"]:
        by_child.setdefault(row["child_id"], []).append(row)

    # 1. Single-input image edit -> image_edit_source primary
    img_edges = by_child[ids["img_edit_id"]]
    assert len(img_edges) == 1
    assert img_edges[0]["role"] == "image_edit_source"
    assert img_edges[0]["is_primary_parent"] is True
    assert img_edges[0]["action_summary"] == "Add warm sunset"

    # 2. Cross-modal start_frame -> primary
    vid_edges = by_child[ids["vid_id"]]
    assert len(vid_edges) == 1
    assert vid_edges[0]["role"] == "start_frame"
    assert vid_edges[0]["is_primary_parent"] is True

    # 3. Video extension -> source is primary, chunk is secondary
    ext_edges = by_child[ids["ext_id"]]
    assert len(ext_edges) == 2
    primary_ext = [e for e in ext_edges if e["is_primary_parent"]]
    assert len(primary_ext) == 1
    assert primary_ext[0]["role"] == "video_extension_source"
    assert primary_ext[0]["action_summary"] == "Pan up to stars"

    # 4. Multi-input composition -> all non-primary
    comp_edges = by_child[ids["comp_id"]]
    assert len(comp_edges) == 2
    assert all(not e["is_primary_parent"] for e in comp_edges)

    # 5. Audio iteration -> audio_iteration_source primary
    aud_edges = by_child[ids["aud_id"]]
    assert len(aud_edges) == 1
    assert aud_edges[0]["role"] == "audio_iteration_source"
    assert aud_edges[0]["is_primary_parent"] is True

    # 6. Adversarial legacy row: overflow IDs & non-objects skipped, >64-char
    # role truncated to 64 chars, array audio_analysis handled safely
    adv_edges = by_child[ids["adv_id"]]
    assert len(adv_edges) == 1
    assert adv_edges[0]["parent_id"] == ids["asset_id"]
    assert len(adv_edges[0]["role"]) == 64
    assert adv_edges[0]["action_summary"] == "Isolated audio stems"

    # 7. Re-running BACKFILL_ITEM_LINEAGE_SQL is an idempotent no-op
    assert upgraded["count_before_rerun"] > 0
    assert upgraded["count_after_rerun"] == upgraded["count_before_rerun"]

    # 8. Recursive CTE walks 3-hop chain (asset -> img_edit -> vid -> ext)
    assert [
        (r["parent_type"], r["parent_id"], r["child_id"])
        for r in upgraded["cte_rows"]
    ] == [
        ("source_asset", ids["asset_id"], ids["img_edit_id"]),
        ("media_item", ids["img_edit_id"], ids["vid_id"]),
        ("media_item", ids["vid_id"], ids["ext_id"]),
    ]

    # 9. Cycle protection terminates cleanly at 1 hop instead of looping
    assert upgraded["cycle_len"] == 1

    # 10. Downgrade drops table and re-upgrade restores it
    assert scenario["downgraded_table"] is None
    assert scenario["reupgraded_table"] == "item_lineage"
