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
"""Integration test for the workflow_runs queue/checkpoint migration.

Runs Alembic revision ``31a0c8217a51`` (spec §5.5) in-process against a
THROWAWAY database on the configured Postgres server. The database is
recreated for this module and dropped afterwards. The application database
(``DB_NAME``) is never migrated, downgraded or written to. The module is
skipped when Postgres is not reachable (e.g. without the compose stack).

Scenario (run once, asserted by the tests below): upgrade a fresh database
to the previous head, seed legacy rows, upgrade, re-apply the backfill,
write rows with the new statuses, downgrade, upgrade again.
"""

import asyncio
import concurrent.futures
import datetime
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import patch

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from src.config.config_service import config_service
from src.database import get_conn_string

logger = logging.getLogger(__name__)

T = TypeVar("T")

BACKEND_DIR = Path(__file__).resolve().parents[2]
REVISION = "31a0c8217a51"
DOWN_REVISION = "8fc57c521452"
THROWAWAY_DB = "creative_studio_migration_test"
MAINTENANCE_DB = "postgres"
CONNECT_TIMEOUT_SECONDS = 5
DROP_THROWAWAY_SQL = f'DROP DATABASE IF EXISTS "{THROWAWAY_DB}" WITH (FORCE)'

USER_EMAIL = "migration-test@example.com"
WORKFLOW_ID = "wf-migration-test"

# New workflow_runs columns (spec §5.1) -> information_schema data type.
NEW_RUN_COLUMNS = {
    "input_args": "jsonb",
    "definition_hash": "character varying",
    "queued_at": "timestamp with time zone",
    "dispatched_at": "timestamp with time zone",
    "queue_reason": "character varying",
    "waiting_for_session_since": "timestamp with time zone",
    "session_wait_seconds": "integer",
    "current_step_id": "character varying",
    "attempt_count": "integer",
    "next_retry_at": "timestamp with time zone",
    "last_error_category": "character varying",
    "last_error_detail": "text",
    "execution_ids": "jsonb",
    "step_states": "jsonb",
    "canceled_by_user": "boolean",
}
ZERO_DEFAULT_COLUMNS = ("attempt_count", "session_wait_seconds")
NEW_RUN_INDEXES = {
    "ix_workflow_runs_status_next_retry_at": "(status, next_retry_at)",
    "ix_workflow_runs_user_id_status": "(user_id, status)",
    "ix_workflow_runs_workflow_id_queued_at": "(workflow_id, queued_at DESC)",
    "ix_workflow_runs_workflow_id_status": "(workflow_id, status)",
}
# workflow_user_sessions (spec §5.3) -> (data type, is_nullable).
SESSION_COLUMNS = {
    "user_id": ("integer", "NO"),
    "encrypted_token": ("text", "YES"),
    "token_expires_at": ("timestamp with time zone", "NO"),
    "updated_at": ("timestamp with time zone", "NO"),
    "last_dispatched_at": ("timestamp with time zone", "YES"),
}
SESSION_CONSTRAINTS = {
    "pk_workflow_user_sessions": "PRIMARY KEY (user_id)",
    "fk_workflow_user_sessions_user_id_users": (
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
    ),
}


def _utc(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.UTC)


# Rows seeded at DOWN_REVISION: id -> (legacy status, started_at).
LEGACY_RUNS = {
    "exec-failed": ("failed", _utc(2026, 9, 20, 10)),
    "exec-scheduled": ("scheduled", _utc(2026, 9, 20, 11)),
    "exec-running": ("running", _utc(2026, 9, 20, 12, 0, 0, 123456)),
    "exec-completed": ("completed", _utc(2026, 9, 20, 13)),
    "exec-canceled": ("canceled", _utc(2026, 9, 20, 14)),
}
# Rows written after the upgrade: id -> status.
NEW_RUNS = {
    "run-queued": "queued",
    "run-step-failed": "step_failed",
    "run-needs-attention": "needs_attention",
    "run-running": "running",
    "run-completed": "completed",
}
EXPECTED_UPGRADED = {
    "exec-failed": "needs_attention",
    "exec-scheduled": "needs_attention",
    "exec-running": "running",
    "exec-completed": "completed",
    "exec-canceled": "canceled",
}
# Downgrade is lossy: the origin of needs_attention is not preserved.
EXPECTED_DOWNGRADED = {
    "exec-failed": "failed",
    "exec-scheduled": "failed",
    "exec-running": "running",
    "exec-completed": "completed",
    "exec-canceled": "canceled",
    "run-queued": "canceled",
    "run-step-failed": "failed",
    "run-needs-attention": "failed",
    "run-running": "running",
    "run-completed": "completed",
}
EXPECTED_REUPGRADED = {
    "exec-failed": "needs_attention",
    "exec-scheduled": "needs_attention",
    "exec-running": "running",
    "exec-completed": "completed",
    "exec-canceled": "canceled",
    "run-queued": "canceled",
    "run-step-failed": "needs_attention",
    "run-needs-attention": "needs_attention",
    "run-running": "running",
    "run-completed": "completed",
}
# Value written to one row before the backfill is re-applied.
CUSTOM_EXECUTION_IDS = [
    {
        "execution_id": "exec-running",
        "started_at": "2026-09-20T12:00:00Z",
        "state": "ACTIVE",
    },
    {
        "execution_id": "exec-running-retry",
        "started_at": "2026-09-21T08:00:00Z",
    },
]

DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


# --- Plumbing ---------------------------------------------------------------


def _in_worker_thread(func: Callable[..., T], *args: Any) -> T:
    """Runs ``func`` in a fresh thread and returns its result.

    Alembic's env.py calls ``asyncio.run()``; keeping it (and our own
    ``asyncio.run`` calls) off the main thread leaves the main thread's
    event loop state untouched for the rest of the test session.
    """
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
    # No ini file: env.py would otherwise call fileConfig() and disable the
    # loggers other tests rely on.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _migrate(action: Callable[[Config, str], None], revision: str) -> None:
    """Runs an Alembic command against the throwaway database only."""
    with patch.object(config_service, "DB_NAME", THROWAWAY_DB):
        # env.py builds its URL from get_conn_string(): refuse to run unless
        # it points at the throwaway database.
        if not get_conn_string().endswith(f"/{THROWAWAY_DB}"):
            raise RuntimeError("Refusing to migrate a non-throwaway database")
        action(_alembic_config(), revision)


def _backfill_sql() -> str:
    script = ScriptDirectory.from_config(_alembic_config())
    return script.get_revision(REVISION).module.BACKFILL_EXECUTION_IDS_SQL


def _json(value: str | None) -> Any:
    return None if value is None else json.loads(value)


# --- Scenario steps (run in the worker thread) ------------------------------


async def _seed_legacy_rows() -> None:
    conn = await _connect(THROWAWAY_DB)
    try:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ($1, ARRAY['user'], 'Migration Test', '') RETURNING id",
            USER_EMAIL,
        )
        await conn.execute(
            "INSERT INTO workflows (id, user_id, name, steps) "
            "VALUES ($1, $2, 'Migration test', '[]'::jsonb)",
            WORKFLOW_ID,
            user_id,
        )
        await conn.executemany(
            "INSERT INTO workflow_runs (id, workflow_id, user_id, status, "
            "workflow_snapshot, started_at) "
            "VALUES ($1, $2, $3, $4, '{}'::jsonb, $5)",
            [
                (run_id, WORKFLOW_ID, user_id, status, started_at)
                for run_id, (status, started_at) in LEGACY_RUNS.items()
            ],
        )
    finally:
        await conn.close()


async def _columns(
    conn: asyncpg.Connection, table: str
) -> dict[str, dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable, column_default, "
        "character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return {row["column_name"]: dict(row) for row in rows}


async def _snapshot() -> dict[str, Any]:
    conn = await _connect(THROWAWAY_DB)
    try:
        indexes = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'workflow_runs'"
        )
        constraints = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint "
            "WHERE conrelid = to_regclass('public.workflow_user_sessions')"
        )
        runs = await conn.fetch("SELECT * FROM workflow_runs")
        workflows = await conn.fetch("SELECT * FROM workflows")
        return {
            "version": await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            ),
            "run_columns": await _columns(conn, "workflow_runs"),
            "workflow_columns": await _columns(conn, "workflows"),
            "session_columns": await _columns(conn, "workflow_user_sessions"),
            "sessions_table": await conn.fetchval(
                "SELECT to_regclass('public.workflow_user_sessions')::text"
            ),
            "session_constraints": {
                row["conname"]: row["definition"] for row in constraints
            },
            "indexes": {row["indexname"]: row["indexdef"] for row in indexes},
            "runs": {row["id"]: dict(row) for row in runs},
            "workflows": [dict(row) for row in workflows],
        }
    finally:
        await conn.close()


async def _reapply_backfill(backfill_sql: str) -> dict[str, dict[str, Any]]:
    """Re-runs the backfill with one NULL and one non-NULL row."""
    conn = await _connect(THROWAWAY_DB)
    try:
        await conn.execute(
            "UPDATE workflow_runs SET execution_ids = $1::jsonb WHERE id = $2",
            json.dumps(CUSTOM_EXECUTION_IDS),
            "exec-running",
        )
        await conn.execute(
            "UPDATE workflow_runs SET execution_ids = NULL WHERE id = $1",
            "exec-completed",
        )
        await conn.execute(backfill_sql)
        rows = await conn.fetch(
            "SELECT id, started_at, execution_ids FROM workflow_runs"
        )
        return {row["id"]: dict(row) for row in rows}
    finally:
        await conn.close()


async def _write_rows_with_new_statuses() -> dict[str, Any]:
    conn = await _connect(THROWAWAY_DB)
    try:
        user_id = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", USER_EMAIL
        )
        await conn.executemany(
            "INSERT INTO workflow_runs (id, workflow_id, user_id, status, "
            "workflow_snapshot) VALUES ($1, $2, $3, $4, '{}'::jsonb)",
            [
                (run_id, WORKFLOW_ID, user_id, status)
                for run_id, status in NEW_RUNS.items()
            ],
        )
        await conn.execute(
            "INSERT INTO workflow_user_sessions "
            "(user_id, encrypted_token, token_expires_at) "
            "VALUES ($1, 'ciphertext', now() + interval '1 hour')",
            user_id,
        )
        runs = await conn.fetch(
            "SELECT id, attempt_count, session_wait_seconds, execution_ids "
            "FROM workflow_runs WHERE id = ANY($1::text[])",
            list(NEW_RUNS),
        )
        session = await conn.fetchrow(
            "SELECT * FROM workflow_user_sessions WHERE user_id = $1", user_id
        )
        return {
            "runs": {row["id"]: dict(row) for row in runs},
            "session": dict(session),
        }
    finally:
        await conn.close()


def _run_scenario() -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    _migrate(command.upgrade, DOWN_REVISION)
    asyncio.run(_seed_legacy_rows())

    _migrate(command.upgrade, REVISION)
    snapshots["upgraded"] = asyncio.run(_snapshot())
    snapshots["backfill"] = asyncio.run(_reapply_backfill(_backfill_sql()))
    snapshots["new_rows"] = asyncio.run(_write_rows_with_new_statuses())

    _migrate(command.downgrade, DOWN_REVISION)
    snapshots["downgraded"] = asyncio.run(_snapshot())

    _migrate(command.upgrade, REVISION)
    snapshots["reupgraded"] = asyncio.run(_snapshot())
    return snapshots


def _skip_reason() -> str | None:
    """Recreates the throwaway DB; returns why the test can't run, if so."""
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
        return (
            "Postgres not available for the throwaway migration database "
            f"({type(exc).__name__})."
        )
    return None


@pytest.fixture(name="snapshots", scope="module")
def fixture_snapshots() -> Iterator[dict[str, Any]]:
    """Runs the migration scenario once and yields per-phase snapshots."""
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    try:
        yield _in_worker_thread(_run_scenario)
    finally:
        try:
            _in_worker_thread(asyncio.run, _drop_throwaway_db())
        except DB_ERRORS as exc:
            logger.warning(
                "Could not drop %s: %s", THROWAWAY_DB, type(exc).__name__
            )


# --- Assertion helpers ------------------------------------------------------


def _statuses(snapshot: dict[str, Any]) -> dict[str, str]:
    return {run_id: run["status"] for run_id, run in snapshot["runs"].items()}


def _assert_backfilled(run: dict[str, Any]) -> None:
    entries = _json(run["execution_ids"])
    assert isinstance(entries, list) and len(entries) == 1, run["id"]
    assert set(entries[0]) == {"execution_id", "started_at"}
    assert entries[0]["execution_id"] == run["id"]
    started_at = datetime.datetime.fromisoformat(entries[0]["started_at"])
    assert started_at == run["started_at"]


def _assert_other_new_columns_null(run: dict[str, Any]) -> None:
    others = set(NEW_RUN_COLUMNS) - {"execution_ids"}
    assert {name: run[name] for name in others} == dict.fromkeys(others)


def _assert_new_schema_present(snapshot: dict[str, Any]) -> None:
    columns = snapshot["run_columns"]
    assert set(NEW_RUN_COLUMNS) <= set(columns)
    for name, data_type in NEW_RUN_COLUMNS.items():
        assert columns[name]["data_type"] == data_type, name
        assert columns[name]["is_nullable"] == "YES", name
        expected_default = "0" if name in ZERO_DEFAULT_COLUMNS else None
        assert columns[name]["column_default"] == expected_default, name
    assert columns["definition_hash"]["character_maximum_length"] == 64

    assert set(NEW_RUN_INDEXES) <= set(snapshot["indexes"])
    for name, definition in NEW_RUN_INDEXES.items():
        assert definition in snapshot["indexes"][name], name

    assert "yaml_version" not in snapshot["workflow_columns"]

    session_columns = snapshot["session_columns"]
    assert {
        name: (column["data_type"], column["is_nullable"])
        for name, column in session_columns.items()
    } == SESSION_COLUMNS
    assert session_columns["updated_at"]["column_default"] == "now()"
    assert snapshot["session_constraints"] == SESSION_CONSTRAINTS


# --- Tests -------------------------------------------------------------------


def test_upgrade_adds_new_schema(snapshots):
    upgraded = snapshots["upgraded"]
    assert upgraded["version"] == REVISION
    _assert_new_schema_present(upgraded)
    assert upgraded["sessions_table"] == "workflow_user_sessions"
    assert (
        upgraded["workflow_columns"]
        == snapshots["downgraded"]["workflow_columns"]
    )


def test_upgrade_migrates_existing_rows(snapshots):
    upgraded = snapshots["upgraded"]
    assert _statuses(upgraded) == EXPECTED_UPGRADED
    for run in upgraded["runs"].values():
        _assert_backfilled(run)
        # attempt_count / session_wait_seconds too: no DEFAULT on old rows.
        _assert_other_new_columns_null(run)


def test_backfill_only_fills_null_execution_ids(snapshots):
    before = snapshots["upgraded"]["runs"]
    after = snapshots["backfill"]
    assert _json(after["exec-running"]["execution_ids"]) == (
        CUSTOM_EXECUTION_IDS
    )
    _assert_backfilled(after["exec-completed"])
    for run_id in set(LEGACY_RUNS) - {"exec-running", "exec-completed"}:
        assert _json(after[run_id]["execution_ids"]) == _json(
            before[run_id]["execution_ids"]
        )


def test_rows_written_after_upgrade_get_defaults(snapshots):
    new_rows = snapshots["new_rows"]
    assert set(new_rows["runs"]) == set(NEW_RUNS)
    for run in new_rows["runs"].values():
        assert run["attempt_count"] == 0
        assert run["session_wait_seconds"] == 0
        assert run["execution_ids"] is None
    assert new_rows["session"]["updated_at"] is not None
    assert new_rows["session"]["last_dispatched_at"] is None


def test_downgrade_is_lossy_and_drops_new_schema(snapshots):
    downgraded = snapshots["downgraded"]
    assert downgraded["version"] == DOWN_REVISION
    assert _statuses(downgraded) == EXPECTED_DOWNGRADED
    assert set(NEW_RUN_COLUMNS).isdisjoint(downgraded["run_columns"])
    assert set(NEW_RUN_INDEXES).isdisjoint(downgraded["indexes"])
    assert "yaml_version" not in downgraded["workflow_columns"]
    assert downgraded["sessions_table"] is None
    assert not downgraded["session_columns"]


def test_upgrade_after_downgrade_is_repeatable(snapshots):
    reupgraded = snapshots["reupgraded"]
    assert reupgraded["version"] == REVISION
    _assert_new_schema_present(reupgraded)
    assert _statuses(reupgraded) == EXPECTED_REUPGRADED
    for run in reupgraded["runs"].values():
        _assert_backfilled(run)
        _assert_other_new_columns_null(run)
    assert (
        reupgraded["workflow_columns"]
        == snapshots["downgraded"]["workflow_columns"]
    )
