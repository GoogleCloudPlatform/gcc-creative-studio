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
"""Checks that the app always keeps at least one admin, even when two admins
act at the same moment.

These tests need a real PostgreSQL, because SQLite ignores row locks and would
pass whether or not the locking works. Set TEST_POSTGRES_URL to run them, for
example: postgresql+asyncpg://postgres@127.0.0.1:55432/cstest
"""

import asyncio
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.users.dto.user_create_dto import UserUpdateRoleDto
from src.users.repository.user_repository import UserRepository
from src.users.user_model import User, UserRoleEnum
from src.users.user_service import UserService

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="needs a real PostgreSQL; set TEST_POSTGRES_URL",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _Rendezvous:
    """Lets two requests meet right before they save their change.

    Without locking, both requests have already passed the "is this the last
    admin?" check when they get here, so both save and the bug shows up. With
    locking, the second request is still waiting on the database, so the first
    one stops waiting after a short timeout and finishes on its own.
    """

    def __init__(self, parties: int, timeout: float = 0.5):
        self._parties = parties
        self._timeout = timeout
        self._arrived = 0
        self._everyone_here = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._everyone_here.set()
        try:
            await asyncio.wait_for(self._everyone_here.wait(), self._timeout)
        except TimeoutError:
            # The other request is blocked on the admin row lock, so it will
            # never arrive. Carry on alone; that is the point of the lock.
            pass


class _PausingUserRepository(UserRepository):
    """A real repository that pauses at the rendezvous before each write."""

    def __init__(self, db: AsyncSession, rendezvous: _Rendezvous):
        super().__init__(db=db)
        self._rendezvous = rendezvous

    async def update(self, item_id, update_data):
        await self._rendezvous.wait()
        return await super().update(item_id, update_data)

    async def soft_delete(self, item_id, deleted_by=None):
        await self._rendezvous.wait()
        return await super().soft_delete(item_id, deleted_by=deleted_by)


@pytest.fixture
async def session_factory():
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


async def _seed(factory, *users: tuple[str, list[str]]) -> list[int]:
    async with factory() as session:
        rows = [
            User(email=email, name=email.split("@")[0], roles=roles)
            for email, roles in users
        ]
        session.add_all(rows)
        await session.commit()
        return [row.id for row in rows]


async def _active_admin_count(factory) -> int:
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.roles.contains([UserRoleEnum.ADMIN.value]))
        )
        return result.scalar_one()


async def _run_concurrently(factory, actions):
    """Runs each action in its own database session at the same time."""
    rendezvous = _Rendezvous(parties=len(actions))

    async def _one(action):
        async with factory() as session:
            service = UserService(
                user_repo=_PausingUserRepository(session, rendezvous)
            )
            return await action(service)

    return await asyncio.gather(
        *(_one(a) for a in actions), return_exceptions=True
    )


def _is_last_admin_refusal(result) -> bool:
    return (
        isinstance(result, HTTPException)
        and result.status_code == 400
        and "at least 1 admin" in result.detail
    )


def _unexpected_errors(results) -> list[BaseException]:
    return [
        r
        for r in results
        if isinstance(r, BaseException) and not _is_last_admin_refusal(r)
    ]


def _outcomes(results) -> tuple[int, int]:
    """Returns (succeeded, refused as last admin) counts."""
    blocked = sum(_is_last_admin_refusal(r) for r in results)
    return len(results) - blocked, blocked


async def test_two_admins_demoting_each_other_leaves_one_admin(session_factory):
    alice, bob = await _seed(
        session_factory,
        ("alice@example.com", ["user", "admin"]),
        ("bob@example.com", ["user", "admin"]),
    )
    demote = UserUpdateRoleDto(roles=[UserRoleEnum.USER])

    results = await _run_concurrently(
        session_factory,
        [
            lambda s: s.update_user_role(bob, demote),
            lambda s: s.update_user_role(alice, demote),
        ],
    )

    assert _unexpected_errors(results) == []
    assert _outcomes(results) == (1, 1)
    assert await _active_admin_count(session_factory) == 1


async def test_two_admins_deleting_each_other_leaves_one_admin(session_factory):
    alice, bob = await _seed(
        session_factory,
        ("alice@example.com", ["user", "admin"]),
        ("bob@example.com", ["user", "admin"]),
    )

    results = await _run_concurrently(
        session_factory,
        [
            lambda s: s.delete_user(bob, deleted_by=alice),
            lambda s: s.delete_user(alice, deleted_by=bob),
        ],
    )

    assert _unexpected_errors(results) == []
    assert _outcomes(results) == (1, 1)
    assert await _active_admin_count(session_factory) == 1


async def test_last_admin_cannot_be_deleted(session_factory):
    alice, carol = await _seed(
        session_factory,
        ("alice@example.com", ["user", "admin"]),
        ("carol@example.com", ["user"]),
    )

    async with session_factory() as session:
        service = UserService(user_repo=UserRepository(db=session))
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_user(alice, deleted_by=carol)
        assert _is_last_admin_refusal(exc_info.value)

    assert await _active_admin_count(session_factory) == 1


async def test_deleting_a_non_admin_still_works(session_factory):
    alice, carol = await _seed(
        session_factory,
        ("alice@example.com", ["user", "admin"]),
        ("carol@example.com", ["user"]),
    )

    async with session_factory() as session:
        service = UserService(user_repo=UserRepository(db=session))
        assert await service.delete_user(carol, deleted_by=alice) is True
