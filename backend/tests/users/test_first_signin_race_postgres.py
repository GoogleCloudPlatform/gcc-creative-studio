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
"""Checks that a user's very first sign-in works even when the browser sends
two requests at the same moment.

Both requests find no user row and both try to create one. The database lets
only one succeed; the other must pick up the row that now exists instead of
failing with a 500.

These tests need a real PostgreSQL, because the clash comes from its unique
constraints. Set TEST_POSTGRES_URL to run them, for example:
postgresql+asyncpg://postgres@127.0.0.1:55432/cstest
"""

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.config_service import config_service
from src.users.repository.user_repository import UserRepository
from src.users.user_model import User
from src.users.user_service import UserService

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="needs a real PostgreSQL; set TEST_POSTGRES_URL",
    ),
]

_OID = "11111111-2222-3333-4444-555555555555"
_EMAIL = "first.signin@example.com"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PausingUserRepository(UserRepository):
    """A real repository where both requests meet right before inserting, so
    both have already decided the user doesn't exist yet."""

    def __init__(self, db: AsyncSession, everyone_here: asyncio.Barrier):
        super().__init__(db=db)
        self._everyone_here = everyone_here

    async def create(self, schema):
        await self._everyone_here.wait()
        return await super().create(schema)


@pytest.fixture
async def session_factory(monkeypatch):
    # Keep Microsoft Graph out of this test: no role sync, no org filter.
    monkeypatch.setattr(config_service, "ENTRA_TENANT_ID", "", raising=False)
    monkeypatch.setattr(config_service, "ALLOWED_ORGS_STR", "", raising=False)

    engine = create_async_engine(POSTGRES_URL)
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.drop, checkfirst=True)
        await conn.run_sync(User.__table__.create)
    yield async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.drop, checkfirst=True)
    await engine.dispose()


async def _count_user_rows(factory) -> int:
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(User))
        return result.scalar_one()


async def test_two_first_signins_at_once_both_succeed(session_factory):
    # The fixture blanks the tenant, so role sync is off for this test.
    assert not config_service.ENTRA_ROLE_SYNC_ENABLED

    everyone_here = asyncio.Barrier(2)

    async def _sign_in():
        async with session_factory() as session:
            service = UserService(
                user_repo=_PausingUserRepository(session, everyone_here)
            )
            return await service.create_user_if_not_exists(
                email=_EMAIL, name="First Signin", picture="", entra_oid=_OID
            )

    results = await asyncio.gather(
        _sign_in(), _sign_in(), return_exceptions=True
    )

    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, f"a first sign-in failed: {errors!r}"
    assert results[0].id == results[1].id
    assert results[0].entra_oid == _OID
    assert await _count_user_rows(session_factory) == 1
