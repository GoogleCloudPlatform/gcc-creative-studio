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
"""Tests for shared throwaway PostgreSQL harness and fail-closed env gate."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.postgres_harness import (
    drop_throwaway_db,
    get_pg_admin_params,
    make_nullpool_session_factory,
    recreate_throwaway_db,
    run_alembic_downgrade,
    run_alembic_upgrade,
)

HARNESS_TEST_DB = "creative_studio_harness_smoke_test"


@pytest.mark.anyio
async def test_postgres_harness_lifecycle_and_alembic() -> None:
    """Throwaway DB supports create, alembic upgrade/downgrade, query, drop."""
    await recreate_throwaway_db(HARNESS_TEST_DB)
    try:
        run_alembic_upgrade(HARNESS_TEST_DB, "head")
        engine, session_factory = make_nullpool_session_factory(HARNESS_TEST_DB)
        try:
            async with session_factory() as session:
                res = await session.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                ver = res.scalar_one()
                assert isinstance(ver, str) and len(ver) > 4
        finally:
            await engine.dispose()

        run_alembic_downgrade(HARNESS_TEST_DB, "e5f6a7b8c9d0")
        run_alembic_upgrade(HARNESS_TEST_DB, "head")
    finally:
        await drop_throwaway_db(HARNESS_TEST_DB)


@pytest.mark.anyio
async def test_require_postgres_tests_fails_closed_when_unreachable(
    monkeypatch,
) -> None:
    """REQUIRE_POSTGRES_TESTS=1 raises RuntimeError instead of pytest.skip."""
    monkeypatch.setenv("REQUIRE_POSTGRES_TESTS", "1")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "59999")
    monkeypatch.setenv("DB_PASS", "")
    params = get_pg_admin_params()
    assert params["port"] == "59999"
    assert params["password"] == ""

    with pytest.raises(RuntimeError, match="REQUIRE_POSTGRES_TESTS=1"):
        await recreate_throwaway_db("creative_studio_unreachable_test")
