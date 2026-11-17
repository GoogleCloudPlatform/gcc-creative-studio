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
"""Integration test for the personal workspaces, revisions, and promotions migration.

Runs Alembic revision ``c8f3a1b2d4e5`` in-process against an isolated
THROWAWAY database on the configured Postgres server and exercises a full
``upgrade -> populate/verify -> downgrade -> upgrade`` cycle, proving:
- Per-user personal workspace backfill and idempotency when a personal
  workspace already exists.
- Partial unique index ``uq_workspaces_personal_owner`` uniqueness enforcement.
- Revision/promotion columns, indexes, and ``unified_gallery_view`` revision
  stack + promotion metadata semantics.
- Safe ``downgrade`` with both empty and non-empty personal workspaces (and
  without touching the dropped ``workflows.workspace_id`` column).
"""

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from tests.postgres_harness import (
    connect_throwaway_db,
    drop_throwaway_db,
    in_worker_thread,
    recreate_throwaway_db,
    run_alembic_downgrade,
    run_alembic_upgrade,
)

logger = logging.getLogger(__name__)

REVISION = "c8f3a1b2d4e5"
DOWN_REVISION = "c8f4a2e91d05"
THROWAWAY_DB = "creative_studio_ws_migration_test"

DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


def upgrade(revision: str) -> None:
    """Runs Alembic upgrade against the isolated throwaway DB."""
    run_alembic_upgrade(THROWAWAY_DB, revision)


def downgrade(revision: str) -> None:
    """Runs Alembic downgrade against the isolated throwaway DB."""
    run_alembic_downgrade(THROWAWAY_DB, revision)


async def _columns(
    conn: asyncpg.Connection, table: str
) -> dict[str, dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return {row["column_name"]: dict(row) for row in rows}


async def _seed_legacy_rows() -> dict[str, Any]:
    conn = await connect_throwaway_db(THROWAWAY_DB)
    try:
        user_a = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('alice@example.com', ARRAY['user'], 'Alice', '') RETURNING id"
        )
        user_b = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('bob@example.com', ARRAY['user'], 'Bob', '') RETURNING id"
        )
        user_c = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('carol@example.com', ARRAY['user'], 'Carol', '') "
            "RETURNING id"
        )

        public_ws = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Default Workspace', $1, 'public') RETURNING id",
            user_a,
        )
        carol_existing_personal = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Carol Personal', $1, 'personal') RETURNING id",
            user_c,
        )
        await conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) "
            "VALUES ($1, $2, 'owner')",
            carol_existing_personal,
            user_c,
        )

        folder_id = await conn.fetchval(
            "INSERT INTO folders (workspace_id, user_id, user_email, name) "
            "VALUES ($1, $2, 'alice@example.com', 'Shared Folder') RETURNING id",
            public_ws,
            user_a,
        )
        legacy_media = await conn.fetchval(
            "INSERT INTO media_items ("
            "  workspace_id, folder_id, user_id, user_email, mime_type, "
            "  model, prompt, aspect_ratio, status, gcs_uris, thumbnail_uris"
            ") VALUES ("
            "  $1, $2, $3, 'alice@example.com', 'image/png', "
            "  'imagen-3.0', 'Legacy prompt', '1:1', 'completed', "
            "  ARRAY['gs://b/legacy.png'], ARRAY['gs://b/legacy_thumb.png']"
            ") RETURNING id",
            public_ws,
            folder_id,
            user_a,
        )
        legacy_asset = await conn.fetchval(
            "INSERT INTO source_assets ("
            "  workspace_id, folder_id, user_id, gcs_uri, original_filename, "
            "  mime_type, aspect_ratio, scope, asset_type"
            ") VALUES ("
            "  $1, $2, $3, 'gs://b/asset.png', 'asset.png', "
            "  'image/png', '1:1', 'private', 'generic_image'"
            ") RETURNING id",
            public_ws,
            folder_id,
            user_a,
        )
        # Ensure workflows/storyboards/timelines tables survive upgrade + downgrade.
        await conn.execute(
            "INSERT INTO workflows (id, user_id, name, steps) "
            "VALUES ('wf-1', $1, 'Legacy WF', '[]'::jsonb)",
            user_a,
        )
        storyboard_id = await conn.fetchval(
            "INSERT INTO storyboards (user_id, workspace_id, template_name) "
            "VALUES ($1, $2, 'Storyboard 1') RETURNING id",
            user_a,
            public_ws,
        )
        await conn.execute(
            "INSERT INTO timelines (title, storyboard_id, workspace_id, user_id) "
            "VALUES ('Timeline 1', $1, $2, $3)",
            storyboard_id,
            str(public_ws),
            str(user_a),
        )
        orphan_timeline_id = await conn.fetchval(
            "INSERT INTO timelines (title, storyboard_id, workspace_id, user_id) "
            "VALUES ('Orphan Timeline', $1, NULL, $2) RETURNING id",
            storyboard_id,
            str(user_a),
        )
        return {
            "user_a": user_a,
            "user_b": user_b,
            "user_c": user_c,
            "public_ws": public_ws,
            "carol_existing_personal": carol_existing_personal,
            "legacy_media": legacy_media,
            "legacy_asset": legacy_asset,
            "orphan_timeline_id": orphan_timeline_id,
        }
    finally:
        await conn.close()


async def _verify_upgraded(seeded: dict[str, Any]) -> dict[str, Any]:
    conn = await connect_throwaway_db(THROWAWAY_DB)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        personal_rows = await conn.fetch(
            "SELECT w.id, w.name, w.owner_id, w.scope, wm.role "
            "FROM workspaces w "
            "LEFT JOIN workspace_members wm "
            "  ON wm.workspace_id = w.id AND wm.user_id = w.owner_id "
            "WHERE w.scope = 'personal' ORDER BY w.owner_id"
        )
        # Verify partial unique index blocks a second personal workspace for Alice.
        duplicate_blocked = False
        try:
            await conn.execute(
                "INSERT INTO workspaces (name, owner_id, scope) "
                "VALUES ('Duplicate Personal', $1, 'personal')",
                seeded["user_a"],
            )
        except asyncpg.UniqueViolationError:
            duplicate_blocked = True

        # Seed a 2-revision stack in Alice's personal workspace and promote v1 to public_ws
        # so unified_gallery_view computes is_latest_revision, revision_count, and promotions
        # AND non-empty vs empty personal workspace downgrade branches are both exercised.
        alice_personal_id = next(
            r["id"] for r in personal_rows if r["owner_id"] == seeded["user_a"]
        )
        rev1_id = await conn.fetchval(
            "INSERT INTO media_items ("
            "  workspace_id, user_id, user_email, mime_type, model, prompt, "
            "  aspect_ratio, status, gcs_uris, thumbnail_uris, revision_number"
            ") VALUES ("
            "  $1, $2, 'alice@example.com', 'image/png', 'imagen-3.0', 'v1', "
            "  '1:1', 'completed', ARRAY['gs://b/v1.png'], "
            "  ARRAY['gs://b/v1_t.png'], 1"
            ") RETURNING id",
            alice_personal_id,
            seeded["user_a"],
        )
        rev2_id = await conn.fetchval(
            "INSERT INTO media_items ("
            "  workspace_id, user_id, user_email, mime_type, model, prompt, "
            "  aspect_ratio, status, gcs_uris, thumbnail_uris, "
            "  revision_root_id, revision_parent_id, revision_number"
            ") VALUES ("
            "  $1, $2, 'alice@example.com', 'image/png', 'imagen-3.0', 'v2', "
            "  '1:1', 'completed', ARRAY['gs://b/v2.png'], "
            "  ARRAY['gs://b/v2_t.png'], $3, $3, 2"
            ") RETURNING id",
            alice_personal_id,
            seeded["user_a"],
            rev1_id,
        )
        promoted_id = await conn.fetchval(
            "INSERT INTO media_items ("
            "  workspace_id, user_id, user_email, mime_type, model, prompt, "
            "  aspect_ratio, status, gcs_uris, thumbnail_uris, "
            "  promoted_from_media_item_id, promoted_from_root_id"
            ") VALUES ("
            "  $1, $2, 'alice@example.com', 'image/png', 'imagen-3.0', 'v1', "
            "  '1:1', 'completed', ARRAY['gs://b/v1.png'], "
            "  ARRAY['gs://b/v1_t.png'], $3, $3"
            ") RETURNING id",
            seeded["public_ws"],
            seeded["user_a"],
            rev1_id,
        )

        view_rows = await conn.fetch(
            "SELECT id, item_type, is_latest_revision, workspace_scope, "
            "workspace_owner_id, metadata "
            "FROM unified_gallery_view "
            "WHERE item_type = 'media_item' AND id = ANY($1::int[]) "
            "ORDER BY id",
            [rev1_id, rev2_id, promoted_id],
        )
        mi_indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'media_items'"
            )
        }
        sa_indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'source_assets'"
            )
        }
        return {
            "version": version,
            "orphan_timeline_ws": await conn.fetchval(
                "SELECT workspace_id FROM timelines WHERE id = $1",
                seeded["orphan_timeline_id"],
            ),
            "personal_rows": [dict(r) for r in personal_rows],
            "alice_personal_id": alice_personal_id,
            "duplicate_blocked": duplicate_blocked,
            "media_columns": await _columns(conn, "media_items"),
            "source_asset_columns": await _columns(conn, "source_assets"),
            "mi_indexes": mi_indexes,
            "sa_indexes": sa_indexes,
            "view_rows": {
                r["id"]: {
                    "is_latest_revision": r["is_latest_revision"],
                    "workspace_scope": r["workspace_scope"],
                    "workspace_owner_id": r["workspace_owner_id"],
                    "metadata": json.loads(r["metadata"]),
                }
                for r in view_rows
            },
            "rev1_id": rev1_id,
            "rev2_id": rev2_id,
            "promoted_id": promoted_id,
        }
    finally:
        await conn.close()


async def _verify_downgraded(
    seeded: dict[str, Any], alice_personal_id: int
) -> dict[str, Any]:
    conn = await connect_throwaway_db(THROWAWAY_DB)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        workspaces = await conn.fetch(
            "SELECT id, owner_id, scope FROM workspaces ORDER BY id"
        )
        ws_indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'workspaces'"
            )
        }
        view_cols = await _columns(conn, "unified_gallery_view")
        alice_ws = next(
            (r for r in workspaces if r["id"] == alice_personal_id), None
        )
        alice_member_role = await conn.fetchval(
            "SELECT role FROM workspace_members "
            "WHERE workspace_id = $1 AND user_id = $2",
            alice_personal_id,
            seeded["user_a"],
        )
        return {
            "version": version,
            "workspaces": [dict(r) for r in workspaces],
            "alice_ws": dict(alice_ws) if alice_ws else None,
            "alice_member_role": alice_member_role,
            "ws_indexes": ws_indexes,
            "media_columns": await _columns(conn, "media_items"),
            "source_asset_columns": await _columns(conn, "source_assets"),
            "view_cols": set(view_cols.keys()),
        }
    finally:
        await conn.close()


def _run_scenario() -> dict[str, Any]:
    upgrade(DOWN_REVISION)
    seeded = asyncio.run(_seed_legacy_rows())

    upgrade(REVISION)
    upgraded = asyncio.run(_verify_upgraded(seeded))

    downgrade(DOWN_REVISION)
    downgraded = asyncio.run(
        _verify_downgraded(seeded, upgraded["alice_personal_id"])
    )

    upgrade(REVISION)
    reupgraded = asyncio.run(_verify_upgraded(seeded))
    return {
        "seeded": seeded,
        "upgraded": upgraded,
        "downgraded": downgraded,
        "reupgraded": reupgraded,
    }


@pytest.fixture(scope="module")
def migration_snapshots() -> Iterator[dict[str, Any]]:
    in_worker_thread(lambda: asyncio.run(recreate_throwaway_db(THROWAWAY_DB)))
    try:
        yield in_worker_thread(_run_scenario)
    finally:
        try:
            in_worker_thread(
                lambda: asyncio.run(drop_throwaway_db(THROWAWAY_DB))
            )
        except DB_ERRORS:
            logger.warning(
                "Failed to drop throwaway DB %s after test", THROWAWAY_DB
            )


def test_personal_workspaces_backfill_and_uniqueness(
    migration_snapshots: dict[str, Any],
) -> None:
    seeded = migration_snapshots["seeded"]
    up = migration_snapshots["upgraded"]

    assert up["version"] == REVISION
    assert up["orphan_timeline_ws"] == str(seeded["public_ws"])
    assert up["duplicate_blocked"] is True

    by_owner = {r["owner_id"]: r for r in up["personal_rows"]}
    assert set(by_owner.keys()) == {
        seeded["user_a"],
        seeded["user_b"],
        seeded["user_c"],
    }
    assert by_owner[seeded["user_a"]]["name"] == "My Workspace"
    assert by_owner[seeded["user_a"]]["role"] == "owner"
    assert by_owner[seeded["user_b"]]["name"] == "My Workspace"
    assert by_owner[seeded["user_b"]]["role"] == "owner"
    assert by_owner[seeded["user_c"]]["id"] == seeded["carol_existing_personal"]
    assert by_owner[seeded["user_c"]]["name"] == "Carol Personal"


def test_schema_indexes_and_unified_gallery_view(
    migration_snapshots: dict[str, Any],
) -> None:
    up = migration_snapshots["upgraded"]
    assert {
        "revision_root_id",
        "revision_parent_id",
        "revision_number",
        "promoted_from_media_item_id",
        "promoted_from_root_id",
    }.issubset(up["media_columns"].keys())
    assert up["media_columns"]["revision_number"]["is_nullable"] == "NO"
    assert "promoted_from_source_asset_id" in up["source_asset_columns"]

    assert {
        "ix_media_items_revision_root_id",
        "ix_media_items_revision_parent_id",
        "ix_media_items_promoted_from_media_item_id",
        "ix_media_items_promoted_from_root_id",
        "ix_media_items_stack_root_active",
    }.issubset(up["mi_indexes"])
    assert "ix_source_assets_promoted_from_source_asset_id" in up["sa_indexes"]

    rev1 = up["view_rows"][up["rev1_id"]]
    rev2 = up["view_rows"][up["rev2_id"]]
    assert rev1["is_latest_revision"] is False
    assert rev1["workspace_scope"] == "personal"
    assert rev1["metadata"]["revision_count"] == 2
    assert rev1["metadata"]["revision_root_id"] == up["rev1_id"]
    assert len(rev1["metadata"]["promotions"]) == 1
    assert (
        rev1["metadata"]["promotions"][0]["target_item_id"] == up["promoted_id"]
    )

    assert rev2["is_latest_revision"] is True
    assert rev2["metadata"]["revision_count"] == 2
    assert rev2["metadata"]["revision_parent_id"] == up["rev1_id"]


def test_downgrade_and_reupgrade_preserve_data(
    migration_snapshots: dict[str, Any],
) -> None:
    seeded = migration_snapshots["seeded"]
    down = migration_snapshots["downgraded"]
    reup = migration_snapshots["reupgraded"]

    assert down["version"] == DOWN_REVISION
    assert "uq_workspaces_personal_owner" not in down["ws_indexes"]
    assert "revision_root_id" not in down["media_columns"]
    assert "promoted_from_source_asset_id" not in down["source_asset_columns"]
    assert "is_latest_revision" not in down["view_cols"]

    # Non-empty Alice workspace converted to private with owner membership preserved;
    # empty Bob & Carol personal workspaces removed cleanly.
    assert down["alice_ws"] is not None
    assert down["alice_ws"]["scope"] == "private"
    assert down["alice_member_role"] == "owner"
    remaining_owners = {(w["owner_id"], w["scope"]) for w in down["workspaces"]}
    assert (seeded["user_b"], "personal") not in remaining_owners
    assert (seeded["user_c"], "personal") not in remaining_owners

    assert reup["version"] == REVISION
    assert {r["owner_id"] for r in reup["personal_rows"]} == {
        seeded["user_a"],
        seeded["user_b"],
        seeded["user_c"],
    }
