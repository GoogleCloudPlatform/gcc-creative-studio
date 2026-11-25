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
"""Integration test for the Workbench projects migration.

Runs Alembic revision ``b3f1c9d2e8a4`` (``docs/projects.md``) in-process
against a THROWAWAY database on the configured Postgres server. The database
is recreated for this module and dropped afterwards. The application database
(``DB_NAME``) is never migrated, downgraded or written to. The module is
skipped when Postgres is not reachable (e.g. without the compose stack).

Scenario (run once, asserted by the tests below): upgrade a fresh database to
the previous revision, seed legacy Workbench rows, upgrade, re-apply the
backfill over an edited chat, downgrade, upgrade again. Every snapshot also
runs DELETEs in rolled-back transactions, to show which foreign keys cascade
and which refuse.
"""

import asyncio
import concurrent.futures
import datetime
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple, TypeVar
from unittest.mock import patch

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.config.config_service import config_service
from src.database import get_conn_string

logger = logging.getLogger(__name__)

T = TypeVar("T")

BACKEND_DIR = Path(__file__).resolve().parents[2]
REVISION = "b3f1c9d2e8a4"
DOWN_REVISION = "b7e2d9c4f1a3"
THROWAWAY_DB = "creative_studio_projects_migration_test"
MAINTENANCE_DB = "postgres"
CONNECT_TIMEOUT_SECONDS = 5
DROP_THROWAWAY_SQL = f'DROP DATABASE IF EXISTS "{THROWAWAY_DB}" WITH (FORCE)'

DEFAULT_PROJECT_NAME = "Default project"
LEGACY_TABLES = (
    "storyboards",
    "scenes",
    "timelines",
    "video_clips",
    "audio_clips",
)
NEW_TABLES = ("projects", "agent_sessions")


# --- Legacy rows, seeded at DOWN_REVISION -----------------------------------
#
# Rows are labelled through text columns the migration never reads: the
# users' and workspaces' ``name``, ``storyboards.template_name``,
# ``timelines.title``, ``scenes.topic`` and the clips' ``placeholder``.

USERS = {"admin": "admin", "alice": "user", "bob": "user"}  # name -> role
# name -> (owner, scope)
WORKSPACES = {"public": ("admin", "public"), "team": ("alice", "private")}
# label -> (owner, workspace, session_id). Inserted in this order, so a later
# storyboard of the same chat has a higher id.
STORYBOARDS = {
    "sb-alice-public-1": ("alice", "public", "sess-multi"),
    "sb-alice-public-2": ("alice", "public", "sess-multi"),
    "sb-bob-public": ("bob", "public", "sess-bob"),
    "sb-alice-public-switch": ("alice", "public", "sess-switched"),
    "sb-alice-team-switch": ("alice", "team", "sess-switched"),
    "sb-bob-team-blank": ("bob", "team", ""),
    "sb-bob-team-null": ("bob", "team", None),
}


class LegacyTimeline(NamedTuple):
    """A ``timelines`` row as the pre-projects code wrote it.

    ``workspace_id`` and ``user_id`` are free text. A ``(table, name)`` tuple
    stands for the id of a seeded workspace or user.
    """

    storyboard: str | None = None
    session_id: str | None = None
    workspace_id: str | tuple[str, str] | None = None
    user_id: str | tuple[str, str] | None = None


def _ws(name: str) -> tuple[str, str]:
    return ("workspaces", name)


def _user(name: str) -> tuple[str, str]:
    return ("users", name)


TIMELINES = {
    # Step 2: a timeline follows its storyboard, whatever workspace it names.
    "tl-storyboard": LegacyTimeline(
        storyboard="sb-alice-public-2",
        session_id="sess-multi",
        workspace_id=_ws("team"),
    ),
    "tl-storyboard-keeps-user": LegacyTimeline(
        storyboard="sb-bob-public",
        session_id="sess-bob",
        workspace_id=_ws("public"),
        user_id=_user("alice"),
    ),
    # Step 3: else the newest storyboard of its chat.
    "tl-session": LegacyTimeline(
        session_id="sess-switched", workspace_id=_ws("public")
    ),
    "tl-session-keeps-user": LegacyTimeline(
        session_id="sess-bob", user_id=_user("admin")
    ),
    # Step 4: legacy orphans go to the workspace owner's Default project,
    # even when they carry a user_id.
    "tl-orphan-team": LegacyTimeline(workspace_id=_ws("team")),
    "tl-orphan-public": LegacyTimeline(workspace_id=_ws("public")),
    "tl-orphan-keeps-user": LegacyTimeline(
        session_id="sess-unknown",
        workspace_id=_ws("public"),
        user_id=_user("bob"),
    ),
    # Orphans naming no workspace stay unattributed. "workspace-7" and the
    # oversized id break an unguarded or unanchored integer cast.
    "tl-invalid-text": LegacyTimeline(workspace_id="workspace-7"),
    "tl-invalid-oversized": LegacyTimeline(workspace_id="99999999999"),
    "tl-invalid-unknown": LegacyTimeline(
        workspace_id="424242", user_id=_user("alice")
    ),
    "tl-invalid-empty": LegacyTimeline(workspace_id=""),
    "tl-invalid-null": LegacyTimeline(),
    # '' names no chat, even though a storyboard has session_id = ''.
    "tl-blank-session": LegacyTimeline(session_id=""),
}
SCENES = {"scene-alice-team-switch": "sb-alice-team-switch"}  # -> storyboard
VIDEO_CLIPS = {  # -> timeline
    "vc-storyboard-keeps-user": "tl-storyboard-keeps-user",
    "vc-session": "tl-session",
}
AUDIO_CLIPS = {"ac-orphan-team": "tl-orphan-team"}  # -> timeline


# --- Expected backfill -------------------------------------------------------
#
# A project reads "owner@workspace" when it is a Default project, else
# "owner@workspace/name".

EXPECTED_PROJECTS = [
    "admin@public",  # Step 4 only: the public workspace's orphans.
    "alice@public",
    "alice@team",  # Steps 1 and 4: still one row.
    "bob@public",
    "bob@team",
]
EXPECTED_STORYBOARDS = {
    "sb-alice-public-1": "alice@public",
    "sb-alice-public-2": "alice@public",
    "sb-bob-public": "bob@public",
    "sb-alice-public-switch": "alice@public",
    "sb-alice-team-switch": "alice@team",
    "sb-bob-team-blank": "bob@team",
    "sb-bob-team-null": "bob@team",
}
# label -> (project, user_id read as a user name). A NULL user_id is stamped
# with the owner the project came from; a set one is kept.
EXPECTED_TIMELINES = {
    "tl-storyboard": ("alice@public", "alice"),
    "tl-storyboard-keeps-user": ("bob@public", "alice"),
    "tl-session": ("alice@team", "alice"),
    "tl-session-keeps-user": ("bob@public", "admin"),
    "tl-orphan-team": ("alice@team", "alice"),
    "tl-orphan-public": ("admin@public", "admin"),
    "tl-orphan-keeps-user": ("admin@public", "bob"),
    "tl-invalid-text": (None, None),
    "tl-invalid-oversized": (None, None),
    "tl-invalid-unknown": (None, "alice"),
    "tl-invalid-empty": (None, None),
    "tl-invalid-null": (None, None),
    "tl-blank-session": (None, None),
}
# session_id -> (project, user, workspace) of the chat's newest storyboard.
# Chats named only by timelines, '' and NULL are not registered.
EXPECTED_CHATS = {
    "sess-multi": ("alice@public", "alice", "public"),
    "sess-bob": ("bob@public", "bob", "public"),
    "sess-switched": ("alice@team", "alice", "team"),
}

# Filed in a new project and edited before the backfill is re-applied.
EDITED_CHAT = "sess-bob"
EDITED_PROJECT = "Campaign"
EDITED_TITLE = "Launch chat"
EDITED_LAST_USED_AT = datetime.datetime(
    2026, 10, 20, 9, 30, tzinfo=datetime.UTC
)


# --- Expected schema ---------------------------------------------------------

# "table.column" -> referenced table, for the foreign keys that b3f1c9d2e8a4
# recreates with ON DELETE CASCADE (``_CASCADE_FKS``).
CASCADE_FKS = {
    "scenes.storyboard_id": "storyboards",
    "timelines.storyboard_id": "storyboards",
    "video_clips.timeline_id": "timelines",
    "audio_clips.timeline_id": "timelines",
}
PROJECT_FKS = {
    "storyboards.project_id": "projects",
    "timelines.project_id": "projects",
    "agent_sessions.project_id": "projects",
}
# index -> end of its definition. The "uq_" ones are unique.
NEW_INDEXES = {
    "ix_projects_workspace_owner": (
        "projects USING btree (workspace_id, owner_id)"
    ),
    "uq_projects_default_per_owner": (
        "projects USING btree (workspace_id, owner_id) WHERE is_default"
    ),
    "uq_agent_sessions_session_id": "agent_sessions USING btree (session_id)",
    "ix_agent_sessions_project_id": "agent_sessions USING btree (project_id)",
    "ix_agent_sessions_user_workspace": (
        "agent_sessions USING btree (user_id, workspace_id)"
    ),
    "ix_storyboards_project_id": "storyboards USING btree (project_id)",
    "ix_timelines_project_id": "timelines USING btree (project_id)",
}


# --- Probes, each run in a rolled-back transaction ---------------------------

# name -> (DELETE, arguments). Each one is refused before the upgrade by one
# of the four recreated foreign keys, and cascades after it.
DELETES = {
    "storyboard_with_scene": (
        "DELETE FROM storyboards WHERE template_name = $1",
        ("sb-alice-team-switch",),
    ),
    "storyboard_with_timeline": (
        "DELETE FROM storyboards WHERE template_name = $1",
        ("sb-bob-public",),
    ),
    "timeline_with_video_clip": (
        "DELETE FROM timelines WHERE title = $1",
        ("tl-session",),
    ),
    "timeline_with_audio_clip": (
        "DELETE FROM timelines WHERE title = $1",
        ("tl-orphan-team",),
    ),
}
# Only probed while the projects table exists.
PROJECT_DELETES = {
    "default_project": (
        "DELETE FROM projects p USING users u, workspaces w "
        "WHERE u.id = p.owner_id AND w.id = p.workspace_id "
        "AND p.is_default AND u.name = $1 AND w.name = $2",
        ("alice", "team"),
    ),
}
EXPECTED_REFUSED_DELETES = {
    "storyboard_with_scene": (
        "ForeignKeyViolationError: scenes_storyboard_id_fkey"
    ),
    "storyboard_with_timeline": (
        "ForeignKeyViolationError: timelines_storyboard_id_fkey"
    ),
    "timeline_with_video_clip": (
        "ForeignKeyViolationError: video_clips_timeline_id_fkey"
    ),
    "timeline_with_audio_clip": (
        "ForeignKeyViolationError: audio_clips_timeline_id_fkey"
    ),
}
# name -> labels of the rows the DELETE removed, per table.
EXPECTED_CASCADED_DELETES = {
    "storyboard_with_scene": {
        "storyboards": {"sb-alice-team-switch"},
        "scenes": {"scene-alice-team-switch"},
    },
    "storyboard_with_timeline": {
        "storyboards": {"sb-bob-public"},
        "timelines": {"tl-storyboard-keeps-user"},
        "video_clips": {"vc-storyboard-keeps-user"},
    },
    "timeline_with_video_clip": {
        "timelines": {"tl-session"},
        "video_clips": {"vc-session"},
    },
    "timeline_with_audio_clip": {
        "timelines": {"tl-orphan-team"},
        "audio_clips": {"ac-orphan-team"},
    },
    # Its chats and storyboards go with it, and so do its timelines that
    # have no storyboard.
    "default_project": {
        "projects": {"alice@team"},
        "agent_sessions": {"sess-switched"},
        "storyboards": {"sb-alice-team-switch"},
        "scenes": {"scene-alice-team-switch"},
        "timelines": {"tl-session", "tl-orphan-team"},
        "video_clips": {"vc-session"},
        "audio_clips": {"ac-orphan-team"},
    },
}

# name -> statement, probed after the upgrade.
WRITES = {
    # uq_projects_default_per_owner allows one Default project per owner...
    "second_default_project": (
        "INSERT INTO projects (workspace_id, owner_id, name, is_default) "
        "SELECT w.id, u.id, 'Second default', true "
        "FROM workspaces w, users u "
        "WHERE w.name = 'public' AND u.name = 'alice'"
    ),
    # ...and any number of other projects.
    "non_default_projects": (
        "INSERT INTO projects (workspace_id, owner_id, name, is_default) "
        "SELECT w.id, u.id, n, false FROM workspaces w, users u, "
        "unnest(ARRAY['Campaign A', 'Campaign B']) AS n "
        "WHERE w.name = 'public' AND u.name = 'alice'"
    ),
    # The constraint behind ON CONFLICT (session_id).
    "duplicate_chat": (
        "INSERT INTO agent_sessions "
        "(session_id, project_id, user_id, workspace_id) "
        "SELECT session_id, project_id, user_id, workspace_id "
        "FROM agent_sessions WHERE session_id = 'sess-bob'"
    ),
    "storyboard_without_project": (
        "INSERT INTO storyboards (user_id, workspace_id) "
        "SELECT u.id, w.id FROM workspaces w, users u "
        "WHERE w.name = 'public' AND u.name = 'alice'"
    ),
    "timeline_without_project": (
        "INSERT INTO timelines (title) VALUES ('tl-new')"
    ),
}
EXPECTED_WRITES = {
    "second_default_project": (
        "UniqueViolationError: uq_projects_default_per_owner"
    ),
    "non_default_projects": "INSERT 0 2",
    "duplicate_chat": "UniqueViolationError: uq_agent_sessions_session_id",
    "storyboard_without_project": "NotNullViolationError: project_id",
    "timeline_without_project": "INSERT 0 1",
}


# --- Introspection SQL -------------------------------------------------------

PROJECTS_SQL = (
    "SELECT p.*, u.name || '@' || w.name "
    "|| CASE WHEN p.is_default THEN '' ELSE '/' || p.name END AS label "
    "FROM projects p JOIN users u ON u.id = p.owner_id "
    "JOIN workspaces w ON w.id = p.workspace_id"
)
# table -> query listing the labels of its rows.
LABELS_SQL = {
    "projects": f"SELECT label FROM ({PROJECTS_SQL}) AS p",
    "agent_sessions": "SELECT session_id FROM agent_sessions",
    "storyboards": "SELECT template_name FROM storyboards",
    "scenes": "SELECT topic FROM scenes",
    "timelines": "SELECT title FROM timelines",
    "video_clips": "SELECT placeholder FROM video_clips",
    "audio_clips": "SELECT placeholder FROM audio_clips",
}
# Single-column foreign keys only: _replace_fk only matches those.
FOREIGN_KEYS_SQL = (
    "SELECT c.conrelid::regclass::text AS table_name, a.attname, c.conname, "
    "pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
    "JOIN pg_attribute a "
    "ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
    "WHERE c.contype = 'f' AND cardinality(c.conkey) = 1 "
    "AND c.conrelid::regclass::text = ANY($1::text[])"
)

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


def _throwaway_url() -> str:
    """The SQLAlchemy URL of the throwaway database, refusing any other."""
    with patch.object(config_service, "DB_NAME", THROWAWAY_DB):
        url = get_conn_string()
    if not url.endswith(f"/{THROWAWAY_DB}"):
        raise RuntimeError("Refusing to migrate a non-throwaway database")
    return url


def _migrate(action: Callable[[Config, str], None], revision: str) -> None:
    """Runs an Alembic command against the throwaway database only."""
    with patch.object(config_service, "DB_NAME", THROWAWAY_DB):
        # env.py builds its URL from get_conn_string(): refuse to run unless
        # it points at the throwaway database.
        _throwaway_url()
        action(_alembic_config(), revision)


def _run_with_op(connection: Connection, func: Callable[[], None]) -> None:
    """Runs ``func`` with Alembic's ``op`` proxy bound to ``connection``."""
    with Operations.context(MigrationContext.configure(connection)):
        func()


def _resolve(
    value: str | tuple[str, str] | None, ids: dict[str, dict[str, int]]
) -> str | None:
    """Turns a ``(table, name)`` reference into that row's id, as text."""
    if isinstance(value, tuple):
        table, name = value
        return str(ids[table][name])
    return value


# --- Scenario steps (run in the worker thread) ------------------------------


async def _seed(conn: asyncpg.Connection) -> None:
    ids: dict[str, dict[str, int]] = {"users": {}, "workspaces": {}}
    for name, role in USERS.items():
        ids["users"][name] = await conn.fetchval(
            "INSERT INTO users (name, email, roles, picture) "
            "VALUES ($1, $2, $3, '') RETURNING id",
            name,
            f"{name}@projects-migration.test",
            [role],
        )
    for name, (owner, scope) in WORKSPACES.items():
        ids["workspaces"][name] = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ($1, $2, $3) RETURNING id",
            name,
            ids["users"][owner],
            scope,
        )
    storyboards = {}
    for label, (owner, workspace, session_id) in STORYBOARDS.items():
        storyboards[label] = await conn.fetchval(
            "INSERT INTO storyboards "
            "(template_name, user_id, workspace_id, session_id) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            label,
            ids["users"][owner],
            ids["workspaces"][workspace],
            session_id,
        )
    timelines = {}
    for label, timeline in TIMELINES.items():
        timelines[label] = await conn.fetchval(
            "INSERT INTO timelines "
            "(title, storyboard_id, session_id, workspace_id, user_id) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            label,
            storyboards.get(timeline.storyboard),
            timeline.session_id,
            _resolve(timeline.workspace_id, ids),
            _resolve(timeline.user_id, ids),
        )
    await conn.executemany(
        "INSERT INTO scenes (topic, storyboard_id) VALUES ($1, $2)",
        [(label, storyboards[sb]) for label, sb in SCENES.items()],
    )
    await conn.executemany(
        "INSERT INTO video_clips (placeholder, timeline_id, volume, speed) "
        "VALUES ($1, $2, 1, 1)",
        [(label, timelines[tl]) for label, tl in VIDEO_CLIPS.items()],
    )
    await conn.executemany(
        "INSERT INTO audio_clips (placeholder, timeline_id, volume) "
        "VALUES ($1, $2, 1)",
        [(label, timelines[tl]) for label, tl in AUDIO_CLIPS.items()],
    )


async def _seed_legacy_rows() -> None:
    conn = await _connect(THROWAWAY_DB)
    try:
        async with conn.transaction():
            await _seed(conn)
    finally:
        await conn.close()


async def _exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval(
        "SELECT to_regclass($1::text) IS NOT NULL", f"public.{table}"
    )


async def _rows(
    conn: asyncpg.Connection, table: str
) -> list[dict[str, Any]] | None:
    if not await _exists(conn, table):
        return None
    if table == "projects":
        sql = f"{PROJECTS_SQL} ORDER BY p.id"
    else:
        sql = f"SELECT * FROM {table} ORDER BY id"
    return [dict(row) for row in await conn.fetch(sql)]


async def _labels(conn: asyncpg.Connection) -> dict[str, set[str]]:
    return {
        table: {row[0] for row in await conn.fetch(sql)}
        for table, sql in LABELS_SQL.items()
        if await _exists(conn, table)
    }


async def _delete(
    conn: asyncpg.Connection, sql: str, args: tuple[str, ...]
) -> dict[str, set[str]] | str:
    """Runs a DELETE, then rolls it back.

    Returns the labels of the rows it removed, per table, or the foreign key
    that refused it.
    """
    transaction = conn.transaction()
    await transaction.start()
    try:
        before = await _labels(conn)
        try:
            await conn.execute(sql, *args)
        except asyncpg.ForeignKeyViolationError as exc:
            return f"{type(exc).__name__}: {exc.constraint_name}"
        after = await _labels(conn)
    finally:
        await transaction.rollback()
    return {
        table: before[table] - after[table]
        for table in before
        if before[table] - after[table]
    }


async def _write(conn: asyncpg.Connection, sql: str) -> str:
    """Runs a write, then rolls it back: its status, or the violation."""
    transaction = conn.transaction()
    await transaction.start()
    try:
        return await conn.execute(sql)
    except asyncpg.IntegrityConstraintViolationError as exc:
        # column_name first: newer servers also name NOT NULL constraints.
        name = exc.column_name or exc.constraint_name
        return f"{type(exc).__name__}: {name}"
    finally:
        await transaction.rollback()


async def _columns(
    conn: asyncpg.Connection, tables: list[str]
) -> dict[str, dict[str, tuple[str, str]]]:
    rows = await conn.fetch(
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name::text = ANY($1::text[])",
        tables,
    )
    columns: dict[str, dict[str, tuple[str, str]]] = {t: {} for t in tables}
    for row in rows:
        columns[row["table_name"]][row["column_name"]] = (
            row["data_type"],
            row["is_nullable"],
        )
    return columns


async def _foreign_keys(
    conn: asyncpg.Connection, tables: list[str]
) -> dict[str, list[tuple[str, str]]]:
    """Maps "table.column" to the (name, definition) of its foreign keys."""
    keys: dict[str, list[tuple[str, str]]] = {}
    for row in await conn.fetch(FOREIGN_KEYS_SQL, tables):
        column = ".".join((row["table_name"], row["attname"]))
        keys.setdefault(column, []).append((row["conname"], row["definition"]))
    return {column: sorted(fks) for column, fks in keys.items()}


async def _indexes(
    conn: asyncpg.Connection, tables: list[str]
) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename::text = ANY($1::text[])",
        tables,
    )
    return {row["indexname"]: row["indexdef"] for row in rows}


async def _snapshot() -> dict[str, Any]:
    tables = [*LEGACY_TABLES, *NEW_TABLES]
    conn = await _connect(THROWAWAY_DB)
    try:
        rows = {table: await _rows(conn, table) for table in tables}
        deletes = DELETES
        if rows["projects"] is not None:
            deletes = {**DELETES, **PROJECT_DELETES}
        users = await conn.fetch("SELECT id, name FROM users")
        workspaces = await conn.fetch("SELECT id, name FROM workspaces")
        return {
            "version": await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            ),
            "users": {row["id"]: row["name"] for row in users},
            "workspaces": {row["id"]: row["name"] for row in workspaces},
            "rows": rows,
            "columns": await _columns(conn, tables),
            "foreign_keys": await _foreign_keys(conn, tables),
            "indexes": await _indexes(conn, tables),
            "deletes": {
                name: await _delete(conn, sql, args)
                for name, (sql, args) in deletes.items()
            },
        }
    finally:
        await conn.close()


async def _probe_writes() -> dict[str, str]:
    conn = await _connect(THROWAWAY_DB)
    try:
        return {name: await _write(conn, sql) for name, sql in WRITES.items()}
    finally:
        await conn.close()


async def _edit_chat() -> None:
    """Files one chat in a new non-default project and gives it activity."""
    conn = await _connect(THROWAWAY_DB)
    try:
        async with conn.transaction():
            project_id = await conn.fetchval(
                "INSERT INTO projects "
                "(workspace_id, owner_id, name, is_default) "
                "SELECT w.id, u.id, $1::text, false "
                "FROM workspaces w, users u "
                "WHERE w.name = 'public' AND u.name = 'bob' RETURNING id",
                EDITED_PROJECT,
            )
            await conn.execute(
                "UPDATE agent_sessions SET project_id = $1, title = $2, "
                "last_used_at = $3 WHERE session_id = $4",
                project_id,
                EDITED_TITLE,
                EDITED_LAST_USED_AT,
                EDITED_CHAT,
            )
    finally:
        await conn.close()


async def _reapply_backfill() -> None:
    """Runs the migration's backfill again over the upgraded database."""
    script = ScriptDirectory.from_config(_alembic_config())
    # The backfill is private to the migration; this test pins it.
    # pylint: disable-next=protected-access
    backfill = script.get_revision(REVISION).module._backfill
    engine = create_async_engine(_throwaway_url(), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_run_with_op, backfill)
    finally:
        await engine.dispose()


def _run_scenario() -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    _migrate(command.upgrade, DOWN_REVISION)
    asyncio.run(_seed_legacy_rows())
    snapshots["seeded"] = asyncio.run(_snapshot())

    _migrate(command.upgrade, REVISION)
    snapshots["upgraded"] = asyncio.run(_snapshot())
    snapshots["writes"] = asyncio.run(_probe_writes())

    asyncio.run(_edit_chat())
    asyncio.run(_reapply_backfill())
    snapshots["backfill"] = asyncio.run(_snapshot())

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


def _projects(snapshot: dict[str, Any]) -> dict[int, str]:
    return {row["id"]: row["label"] for row in snapshot["rows"]["projects"]}


def _storyboard_projects(snapshot: dict[str, Any]) -> dict[str, str]:
    projects = _projects(snapshot)
    return {
        row["template_name"]: projects[row["project_id"]]
        for row in snapshot["rows"]["storyboards"]
    }


def _timeline_owners(
    snapshot: dict[str, Any],
) -> dict[str, tuple[str | None, str | None]]:
    projects = _projects(snapshot)
    users = {str(user_id): name for user_id, name in snapshot["users"].items()}
    return {
        row["title"]: (
            projects.get(row["project_id"]),
            users.get(row["user_id"], row["user_id"]),
        )
        for row in snapshot["rows"]["timelines"]
    }


def _chats(snapshot: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    projects = _projects(snapshot)
    return {
        row["session_id"]: (
            projects[row["project_id"]],
            snapshot["users"][row["user_id"]],
            snapshot["workspaces"][row["workspace_id"]],
        )
        for row in snapshot["rows"]["agent_sessions"]
    }


def _chat_rows(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["session_id"]: row for row in snapshot["rows"]["agent_sessions"]
    }


def _without(rows: list[dict[str, Any]], *columns: str) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k not in columns} for row in rows]


def _fk(column: str, ref_table: str, cascade: bool) -> list[tuple[str, str]]:
    """The one foreign key expected on ``column`` ("table.column")."""
    table, name = column.split(".")
    definition = f"FOREIGN KEY ({name}) REFERENCES {ref_table}(id)"
    if cascade:
        definition += " ON DELETE CASCADE"
    return [(f"{table}_{name}_fkey", definition)]


def _untouched_fks(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Legacy-table foreign keys that b3f1c9d2e8a4 leaves alone."""
    touched = CASCADE_FKS.keys() | PROJECT_FKS.keys()
    return {
        column: fks
        for column, fks in snapshot["foreign_keys"].items()
        if column.split(".")[0] in LEGACY_TABLES and column not in touched
    }


# --- Tests -------------------------------------------------------------------


def test_seeded_database_has_no_cascades(snapshots):
    seeded = snapshots["seeded"]
    assert seeded["version"] == DOWN_REVISION
    assert seeded["rows"]["projects"] is None
    assert seeded["rows"]["agent_sessions"] is None
    for column, ref_table in CASCADE_FKS.items():
        assert seeded["foreign_keys"][column] == _fk(
            column, ref_table, cascade=False
        ), column
    assert seeded["deletes"] == EXPECTED_REFUSED_DELETES


def test_upgrade_adds_projects_schema(snapshots):
    seeded, upgraded = snapshots["seeded"], snapshots["upgraded"]
    assert upgraded["version"] == REVISION

    columns = upgraded["columns"]
    assert columns["storyboards"]["project_id"] == ("integer", "NO")
    assert columns["timelines"]["project_id"] == ("integer", "YES")
    for table in LEGACY_TABLES:
        others = {c: v for c, v in columns[table].items() if c != "project_id"}
        assert others == seeded["columns"][table], table

    for name, definition in NEW_INDEXES.items():
        indexdef = upgraded["indexes"][name]
        assert indexdef.endswith(definition), name
        unique = indexdef.startswith("CREATE UNIQUE INDEX ")
        assert unique == name.startswith("uq_"), name

    for column, ref_table in (CASCADE_FKS | PROJECT_FKS).items():
        assert upgraded["foreign_keys"][column] == _fk(
            column, ref_table, cascade=True
        ), column
    # _replace_fk only swaps the foreign key on its own column.
    assert _untouched_fks(seeded)
    assert _untouched_fks(upgraded) == _untouched_fks(seeded)


def test_upgrade_gives_each_owner_one_default_project(snapshots):
    upgraded = snapshots["upgraded"]
    assert sorted(_projects(upgraded).values()) == EXPECTED_PROJECTS
    assert {
        (row["name"], row["is_default"]) for row in upgraded["rows"]["projects"]
    } == {(DEFAULT_PROJECT_NAME, True)}
    assert _storyboard_projects(upgraded) == EXPECTED_STORYBOARDS


def test_upgrade_attributes_legacy_timelines(snapshots):
    seeded, upgraded = snapshots["seeded"], snapshots["upgraded"]
    assert _timeline_owners(upgraded) == EXPECTED_TIMELINES
    # Only project_id and the NULL user_ids are written.
    assert _without(
        upgraded["rows"]["timelines"], "project_id", "user_id"
    ) == _without(seeded["rows"]["timelines"], "user_id")


def test_upgrade_registers_each_storyboard_chat_once(snapshots):
    upgraded = snapshots["upgraded"]
    assert _chats(upgraded) == EXPECTED_CHATS
    for row in upgraded["rows"]["agent_sessions"]:
        assert row["app_name"] == "ads_x", row["session_id"]
        # No activity time yet: docs/projects.md, "Chat activity".
        assert row["last_used_at"] is None, row["session_id"]
        assert row["title"] is None and row["summary"] is None


def test_upgrade_enforces_project_constraints(snapshots):
    assert snapshots["writes"] == EXPECTED_WRITES


def test_upgrade_makes_deletes_cascade(snapshots):
    assert snapshots["upgraded"]["deletes"] == EXPECTED_CASCADED_DELETES


def test_reapplied_backfill_keeps_existing_rows(snapshots):
    upgraded, backfill = snapshots["upgraded"], snapshots["backfill"]
    for table in LEGACY_TABLES:
        assert backfill["rows"][table] == upgraded["rows"][table], table

    # ON CONFLICT DO NOTHING: no second Default project for anyone.
    projects = backfill["rows"]["projects"]
    edited = [row for row in projects if not row["is_default"]]
    assert [row["label"] for row in edited] == [f"bob@public/{EDITED_PROJECT}"]
    defaults = [row for row in projects if row["is_default"]]
    assert defaults == upgraded["rows"]["projects"]

    # ON CONFLICT (session_id) DO NOTHING: the edited chat is left as it is.
    expected = _chat_rows(upgraded)
    expected[EDITED_CHAT] = {
        **expected[EDITED_CHAT],
        "project_id": edited[0]["id"],
        "title": EDITED_TITLE,
        "last_used_at": EDITED_LAST_USED_AT,
    }
    assert _chat_rows(backfill) == expected


def test_downgrade_restores_legacy_schema_and_rows(snapshots):
    seeded, downgraded = snapshots["seeded"], snapshots["downgraded"]
    assert downgraded["version"] == DOWN_REVISION
    for key in ("columns", "foreign_keys", "indexes", "deletes"):
        assert downgraded[key] == seeded[key], key
    for table in NEW_TABLES:
        assert downgraded["rows"][table] is None, table
    for table in ("storyboards", "scenes", "video_clips", "audio_clips"):
        assert downgraded["rows"][table] == seeded["rows"][table], table

    # Lossy: timelines keep the user_id the backfill stamped.
    timelines = downgraded["rows"]["timelines"]
    assert _without(timelines, "user_id") == _without(
        seeded["rows"]["timelines"], "user_id"
    )
    assert [row["user_id"] for row in timelines] == [
        row["user_id"] for row in snapshots["upgraded"]["rows"]["timelines"]
    ]


def test_upgrade_after_downgrade_is_repeatable(snapshots):
    upgraded, reupgraded = snapshots["upgraded"], snapshots["reupgraded"]
    assert reupgraded["version"] == REVISION
    for key in ("columns", "foreign_keys", "indexes", "deletes"):
        assert reupgraded[key] == upgraded[key], key

    # A fresh backfill: the edited chat's project and activity are gone.
    assert sorted(_projects(reupgraded).values()) == EXPECTED_PROJECTS
    assert _storyboard_projects(reupgraded) == EXPECTED_STORYBOARDS
    assert _timeline_owners(reupgraded) == EXPECTED_TIMELINES
    assert _chats(reupgraded) == EXPECTED_CHATS
    edited = _chat_rows(reupgraded)[EDITED_CHAT]
    assert (edited["title"], edited["last_used_at"]) == (None, None)
