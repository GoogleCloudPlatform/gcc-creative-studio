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
"""Shared ephemeral PostgreSQL lifecycle and Alembic helpers for tests."""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import re
from typing import Callable, TypeVar
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import asyncpg
import pytest
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.config.config_service import config_service
from src.database import get_conn_string

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
CONNECT_TIMEOUT_SECONDS = 5
_SAFE_DB_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,62}$")
_RESERVED_DBS = frozenset({"postgres", "template0", "template1"})
_DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)
T = TypeVar("T")


def _validate_db_name(db_name: str) -> str:
    if db_name in _RESERVED_DBS or not _SAFE_DB_NAME_RE.match(db_name):
        raise ValueError(
            f"Refusing unsafe throwaway database name: {db_name!r}"
        )
    return db_name


def get_pg_admin_params() -> dict[str, str]:
    """Resolve Postgres connection parameters from env or config_service."""
    password = (
        os.environ["DB_PASS"]
        if "DB_PASS" in os.environ
        else str(config_service.DB_PASS or "")
    )
    return {
        "host": os.environ.get("DB_HOST") or str(config_service.DB_HOST),
        "port": os.environ.get("DB_PORT") or str(config_service.DB_PORT),
        "user": os.environ.get("DB_USER") or str(config_service.DB_USER),
        "password": password,
    }


def _require_postgres_or_skip(exc: Exception) -> None:
    if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
        raise RuntimeError(
            f"Postgres required (REQUIRE_POSTGRES_TESTS=1) but failed: {exc}"
        ) from exc
    pytest.skip(f"Postgres unavailable for harness test: {exc}")


async def _connect_admin(maintenance_db: str) -> asyncpg.Connection:
    params = get_pg_admin_params()
    try:
        return await asyncpg.connect(
            user=params["user"],
            password=params["password"],
            host=params["host"],
            port=params["port"],
            database=maintenance_db,
            timeout=CONNECT_TIMEOUT_SECONDS,
            ssl=False,
        )
    except _DB_ERRORS as exc:
        _require_postgres_or_skip(exc)
        raise AssertionError("unreachable") from exc


async def recreate_throwaway_db(
    db_name: str, maintenance_db: str = "postgres"
) -> None:
    """Drop and recreate an isolated throwaway Postgres database."""
    safe_name = _validate_db_name(db_name)
    conn = await _connect_admin(maintenance_db)
    try:
        await conn.execute(
            f'DROP DATABASE IF EXISTS "{safe_name}" WITH (FORCE)'
        )
        await conn.execute(f'CREATE DATABASE "{safe_name}"')
    finally:
        await conn.close()


async def drop_throwaway_db(
    db_name: str, maintenance_db: str = "postgres"
) -> None:
    """Drop an isolated throwaway Postgres database."""
    safe_name = _validate_db_name(db_name)
    conn = await _connect_admin(maintenance_db)
    try:
        await conn.execute(
            f'DROP DATABASE IF EXISTS "{safe_name}" WITH (FORCE)'
        )
    finally:
        await conn.close()


def _in_worker_thread(func: Callable[..., T], *args: object) -> T:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(func, *args).result()


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _run_alembic(
    action: Callable[[Config, str], None], db_name: str, revision: str
) -> None:
    safe_name = _validate_db_name(db_name)
    params = get_pg_admin_params()
    with (
        patch.object(config_service, "DB_HOST", params["host"]),
        patch.object(config_service, "DB_PORT", params["port"]),
        patch.object(config_service, "DB_USER", params["user"]),
        patch.object(config_service, "DB_PASS", params["password"]),
        patch.object(config_service, "DB_NAME", safe_name),
        patch.object(config_service, "INSTANCE_CONNECTION_NAME", ""),
        patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", False),
    ):
        if not get_conn_string().endswith(f"/{safe_name}"):
            raise RuntimeError("Refusing to migrate a non-throwaway database")
        action(_alembic_config(), revision)


def run_alembic_upgrade(db_name: str, revision: str = "head") -> None:
    """Upgrade a throwaway Postgres database to target revision on a worker."""
    _in_worker_thread(_run_alembic, command.upgrade, db_name, revision)


def run_alembic_downgrade(db_name: str, revision: str) -> None:
    """Downgrade a throwaway Postgres DB to target revision on a worker."""
    _in_worker_thread(_run_alembic, command.downgrade, db_name, revision)


def make_nullpool_session_factory(
    db_name: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build a NullPool async engine + session factory bound to db_name."""
    safe_name = _validate_db_name(db_name)
    params = get_pg_admin_params()
    url = URL.create(
        drivername="postgresql+asyncpg",
        username=params["user"],
        password=params["password"],
        host=params["host"],
        port=int(params["port"]),
        database=safe_name,
    )
    engine = create_async_engine(url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory
