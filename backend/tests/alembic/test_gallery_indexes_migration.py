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
"""Integration test for the gallery performance index Alembic migration.

Runs Alembic revision ``c8f4a2e91d05`` against a THROWAWAY database on the
configured Postgres server. The throwaway database is recreated before the
module runs and dropped afterwards; the application ``DB_NAME`` is never
touched.
"""

import asyncio
import contextlib
import datetime
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from src.config.config_service import config_service
from tests.postgres_harness import (
    connect_throwaway_db,
    drop_throwaway_db,
    in_worker_thread,
    recreate_throwaway_db,
    run_alembic_downgrade,
    run_alembic_upgrade,
)

REVISION = "c8f4a2e91d05"
DOWN_REVISION = "b7e2d9c4f1a3"
THROWAWAY_DB = "creative_studio_gallery_mig_test"

EXPECTED_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ix_media_items_ws_created_active": (
        "media_items",
        ("workspace_id", "created_at DESC", "id DESC", "deleted_at IS NULL"),
    ),
    "ix_media_items_ws_folder_created_active": (
        "media_items",
        (
            "workspace_id",
            "folder_id",
            "created_at DESC",
            "id DESC",
            "deleted_at IS NULL",
        ),
    ),
    "ix_media_items_ws_folder_status_created_active": (
        "media_items",
        (
            "workspace_id",
            "folder_id",
            "status",
            "created_at DESC",
            "id DESC",
            "deleted_at IS NULL",
        ),
    ),
    "ix_media_items_ws_status_created_active": (
        "media_items",
        (
            "workspace_id",
            "status",
            "created_at DESC",
            "id DESC",
            "deleted_at IS NULL",
        ),
    ),
    "ix_source_assets_ws_created_active": (
        "source_assets",
        ("workspace_id", "created_at DESC", "id DESC", "deleted_at IS NULL"),
    ),
    "ix_source_assets_ws_folder_created_active": (
        "source_assets",
        (
            "workspace_id",
            "folder_id",
            "created_at DESC",
            "id DESC",
            "deleted_at IS NULL",
        ),
    ),
    "ix_media_item_tags_tag_id": (
        "media_item_tags",
        ("tag_id", "media_item_id"),
    ),
    "ix_source_asset_tags_tag_id": (
        "source_asset_tags",
        ("tag_id", "source_asset_id"),
    ),
}

DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


async def _seed_sample_rows() -> None:
    conn = await connect_throwaway_db(THROWAWAY_DB)
    try:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('mig-gallery@example.com', ARRAY['user'], 'Mig User', '') "
            "RETURNING id"
        )
        ws_id = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Mig Workspace', $1, 'public') RETURNING id",
            user_id,
        )
        folder_id = await conn.fetchval(
            "INSERT INTO folders (workspace_id, user_id, user_email, name) "
            "VALUES ($1, $2, 'mig-gallery@example.com', 'Folder A') "
            "RETURNING id",
            ws_id,
            user_id,
        )
        tag_id = await conn.fetchval(
            "INSERT INTO tags (workspace_id, name, color) "
            "VALUES ($1, 'hero', '#1a73e8') RETURNING id",
            ws_id,
        )
        now = datetime.datetime(2026, 2, 1, 12, 0, tzinfo=datetime.UTC)
        media_id = await conn.fetchval(
            "INSERT INTO media_items (workspace_id, user_id, user_email, "
            "folder_id, created_at, status, model, prompt, mime_type, "
            "aspect_ratio, gcs_uris, thumbnail_uris) "
            "VALUES ($1, $2, 'mig-gallery@example.com', $3, $4, 'completed', "
            "'imagen-3.0-generate-001', 'A sunset', 'image/png', '1:1', "
            "ARRAY['gs://b/m.png'], ARRAY['gs://b/m_thumb.webp']) RETURNING id",
            ws_id,
            user_id,
            folder_id,
            now,
        )
        asset_id = await conn.fetchval(
            "INSERT INTO source_assets (workspace_id, user_id, folder_id, "
            "created_at, original_filename, mime_type, aspect_ratio, gcs_uri, "
            "thumbnail_gcs_uri, file_hash, scope, asset_type) "
            "VALUES ($1, $2, $3, $4, 'logo.png', 'image/png', '1:1', "
            "'gs://b/a.png', 'gs://b/a_thumb.webp', 'hash-1', 'private', "
            "'generic_image') RETURNING id",
            ws_id,
            user_id,
            folder_id,
            now + datetime.timedelta(seconds=30),
        )
        await conn.execute(
            "INSERT INTO media_item_tags (media_item_id, tag_id) "
            "VALUES ($1, $2)",
            media_id,
            tag_id,
        )
        await conn.execute(
            "INSERT INTO source_asset_tags (source_asset_id, tag_id) "
            "VALUES ($1, $2)",
            asset_id,
            tag_id,
        )
    finally:
        await conn.close()


async def _snapshot() -> dict[str, Any]:
    conn = await connect_throwaway_db(THROWAWAY_DB)
    try:
        idx_rows = await conn.fetch(
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "AND tablename = ANY(ARRAY["
            "'media_items', 'source_assets', "
            "'media_item_tags', 'source_asset_tags'])"
        )
        view_rows = await conn.fetch(
            "SELECT item_type, id, workspace_id, folder_id, status "
            "FROM unified_gallery_view ORDER BY created_at DESC, id DESC"
        )
        return {
            "version": await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            ),
            "indexes": {
                row["indexname"]: (row["tablename"], row["indexdef"])
                for row in idx_rows
            },
            "view_name": await conn.fetchval(
                "SELECT to_regclass('public.unified_gallery_view')::text"
            ),
            "view_rows": [dict(row) for row in view_rows],
        }
    finally:
        await conn.close()


def _run_scenario() -> dict[str, Any]:
    snapshots: dict[str, Any] = {}

    def upgrade(revision: str) -> None:
        run_alembic_upgrade(THROWAWAY_DB, revision)

    def downgrade(revision: str) -> None:
        run_alembic_downgrade(THROWAWAY_DB, revision)

    upgrade(DOWN_REVISION)
    asyncio.run(_seed_sample_rows())
    snapshots["baseline"] = asyncio.run(_snapshot())

    upgrade(REVISION)
    snapshots["upgraded"] = asyncio.run(_snapshot())

    downgrade(DOWN_REVISION)
    snapshots["downgraded"] = asyncio.run(_snapshot())

    upgrade(REVISION)
    snapshots["reupgraded"] = asyncio.run(_snapshot())
    return snapshots


@pytest.fixture(name="snapshots", scope="module")
def fixture_snapshots() -> Iterator[dict[str, Any]]:
    """Runs upgrade -> downgrade -> upgrade once and cleans up the DB."""
    if config_service.DB_NAME == THROWAWAY_DB:
        pytest.skip(
            "DB_NAME is the throwaway database; refusing to recreate it."
        )
    in_worker_thread(asyncio.run, recreate_throwaway_db(THROWAWAY_DB))
    try:
        yield in_worker_thread(_run_scenario)
    finally:
        with contextlib.suppress(DB_ERRORS):
            in_worker_thread(asyncio.run, drop_throwaway_db(THROWAWAY_DB))


def _assert_gallery_indexes_present(snapshot: dict[str, Any]) -> None:
    indexes = snapshot["indexes"]
    for idx_name, (table_name, required_clauses) in EXPECTED_INDEXES.items():
        assert idx_name in indexes, f"Missing index {idx_name}"
        actual_table, index_def = indexes[idx_name]
        assert actual_table == table_name
        for clause in required_clauses:
            assert clause in index_def, f"{clause!r} not in {index_def}"


def test_upgrade_creates_gallery_indexes_and_preserves_view(
    snapshots: dict[str, Any],
) -> None:
    """Upgrading creates all 8 gallery indexes while preserving view rows."""
    upgraded = snapshots["upgraded"]
    assert upgraded["version"] == REVISION
    assert upgraded["view_name"] == "unified_gallery_view"
    _assert_gallery_indexes_present(upgraded)
    assert upgraded["view_rows"] == snapshots["baseline"]["view_rows"]
    assert len(upgraded["view_rows"]) == 2


def test_downgrade_drops_gallery_indexes_and_preserves_view(
    snapshots: dict[str, Any],
) -> None:
    """Downgrading drops all 8 gallery indexes while preserving view rows."""
    downgraded = snapshots["downgraded"]
    assert downgraded["version"] == DOWN_REVISION
    assert downgraded["view_name"] == "unified_gallery_view"
    assert set(EXPECTED_INDEXES).isdisjoint(downgraded["indexes"])
    assert downgraded["view_rows"] == snapshots["baseline"]["view_rows"]


def test_reupgrade_after_downgrade_is_repeatable(
    snapshots: dict[str, Any],
) -> None:
    """Re-upgrading after downgrade restores all 8 indexes cleanly."""
    reupgraded = snapshots["reupgraded"]
    assert reupgraded["version"] == REVISION
    assert reupgraded["view_name"] == "unified_gallery_view"
    _assert_gallery_indexes_present(reupgraded)
    assert reupgraded["view_rows"] == snapshots["baseline"]["view_rows"]
