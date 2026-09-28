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

"""Postgres integration tests for WorkflowDispatcher concurrency (§8.2, §11.1, §11.2).

Uses a throwaway Postgres database (``creative_studio_dispatcher_concurrency_test``)
created for the module and dropped afterwards. The main application database
is never modified.
"""

import asyncio
from collections.abc import AsyncGenerator
import datetime
from typing import Any
from unittest.mock import MagicMock

import asyncpg
from cryptography.fernet import Fernet
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.config_service import config_service
from src.database import Base
from src.users.user_model import User  # noqa: F401
from src.workflows.queue.run_state_service import RunStateService
from src.workflows.queue.workflow_dispatcher import WorkflowDispatcher
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows.schema.workflow_model import (
    NodeTypes,
    StepStatusEnum,
    Workflow,
    WorkflowRunStatusEnum,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    WorkflowRun,
    WorkflowRunModel,
    WorkflowUserSession,  # noqa: F401
)
from src.workflows.session.token_store_service import (
    TokenStoreService,
    WorkflowUserSessionRepository,
)

THROWAWAY_DB = "creative_studio_dispatcher_concurrency_test"
MAINTENANCE_DB = "postgres"
CONNECT_TIMEOUT_SECONDS = 5
DROP_THROWAWAY_SQL = f'DROP DATABASE IF EXISTS "{THROWAWAY_DB}" WITH (FORCE)'

TEST_KEY = Fernet.generate_key().decode("ascii")
SampleJwt = (
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NSIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSJ9."
    "c2lnbmF0dXJl"
)
FIXED_NOW = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)


async def _connect_maintenance() -> asyncpg.Connection:
    return await asyncpg.connect(
        user=config_service.DB_USER,
        password=config_service.DB_PASS,
        host=config_service.DB_HOST,
        port=config_service.DB_PORT,
        database=MAINTENANCE_DB,
        timeout=CONNECT_TIMEOUT_SECONDS,
        ssl=False,
    )


def _throwaway_url() -> str:
    return (
        f"postgresql+asyncpg://{config_service.DB_USER}:"
        f"{config_service.DB_PASS}@"
        f"{config_service.DB_HOST}:{config_service.DB_PORT}"
        f"/{THROWAWAY_DB}"
    )


@pytest_asyncio.fixture(name="session_factory")
async def fixture_session_factory() -> (
    AsyncGenerator[async_sessionmaker[AsyncSession], None]
):
    """Creates a throwaway Postgres DB + tables for each test and drops it after."""
    try:
        conn = await _connect_maintenance()
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unavailable for concurrency test: {exc}")
        return

    try:
        await conn.execute(DROP_THROWAWAY_SQL)
        await conn.execute(f'CREATE DATABASE "{THROWAWAY_DB}"')
    finally:
        await conn.close()

    engine: AsyncEngine = create_async_engine(
        _throwaway_url(),
        pool_size=25,
        max_overflow=10,
    )
    try:
        async with engine.begin() as db_conn:
            await db_conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    User.__table__,
                    Workflow.__table__,
                    WorkflowRun.__table__,
                    WorkflowUserSession.__table__,
                ],
            )
        factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        yield factory
    finally:
        await engine.dispose()
        cleanup_conn = await _connect_maintenance()
        try:
            await cleanup_conn.execute(DROP_THROWAWAY_SQL)
        finally:
            await cleanup_conn.close()


def _snapshot() -> dict[str, Any]:
    return {
        "id": "wf-conc",
        "user_id": 1,
        "name": "Concurrency WF",
        "steps": [
            {
                "step_id": "step_a",
                "type": NodeTypes.GENERATE_TEXT.value,
                "status": StepStatusEnum.PENDING.value,
                "inputs": {"prompt": "Hello"},
                "settings": {"model": "gemini-2.5-flash", "temperature": 0.7},
            }
        ],
    }


async def _seed_users_and_runs(
    factory: async_sessionmaker[AsyncSession],
    *,
    user_run_counts: dict[int, int],
) -> None:
    """Seeds users, workflow, valid encrypted tokens, and queued runs."""
    async with factory() as session:
        for idx, uid in enumerate(user_run_counts.keys()):
            session.add(
                User(
                    id=uid,
                    email=f"user-{uid}@example.com",
                    roles=["user"],
                    name=f"User {uid}",
                    picture="",
                )
            )
            if idx == 0:
                session.add(
                    Workflow(
                        id="wf-conc",
                        user_id=uid,
                        name="Concurrency WF",
                        steps=_snapshot()["steps"],
                    )
                )
        await session.commit()

    async with factory() as session:
        session_repo = WorkflowUserSessionRepository(db=session)
        token_store = TokenStoreService(
            repository=session_repo,
            encryption_key=TEST_KEY,
            clock=lambda: FIXED_NOW,
        )
        seq = 0
        for uid, count in user_run_counts.items():
            await token_store.store_token(
                uid,
                SampleJwt,
                exp=FIXED_NOW + datetime.timedelta(minutes=45),
                commit=False,
            )
            for i in range(count):
                seq += 1
                queued_at = FIXED_NOW + datetime.timedelta(seconds=i)
                session.add(
                    WorkflowRun(
                        id=f"run-u{uid}-{i:02d}",
                        workflow_id="wf-conc",
                        user_id=uid,
                        workspace_id=1,
                        status=WorkflowRunStatusEnum.QUEUED.value,
                        started_at=queued_at,
                        queued_at=queued_at,
                        queue_reason=QueueReasonEnum.WAITING_FOR_SLOT.value,
                        workflow_snapshot=_snapshot(),
                        input_args={"workspace_id": 1},
                        execution_ids=[],
                        step_states={},
                    )
                )
        await session.commit()


def _make_create_execution_fn(counter: list[int]):
    async def _create_exec(run: WorkflowRunModel, args: dict[str, Any]) -> str:
        _ = (run, args)
        counter.append(1)
        return f"exec-conc-{len(counter)}"

    return _create_exec


@pytest.mark.asyncio
async def test_two_concurrent_dispatchers_with_one_slot_claim_at_most_one_run(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Two concurrent dispatch() calls with 1 slot claim at most 1 run (§11.1 #6)."""
    await _seed_users_and_runs(session_factory, user_run_counts={1: 4})
    created_counter: list[int] = []
    create_exec_fn = _make_create_execution_fn(created_counter)

    async def _run_one_dispatcher() -> list[WorkflowRunModel]:
        async with session_factory() as session:
            run_repo = WorkflowRunRepository(db=session)
            session_repo = WorkflowUserSessionRepository(db=session)
            token_store = TokenStoreService(
                repository=session_repo,
                encryption_key=TEST_KEY,
                clock=lambda: FIXED_NOW,
            )
            state_svc = RunStateService(
                repository=run_repo,
                dispatch_hook=None,
                clock=lambda: FIXED_NOW,
            )
            dispatcher = WorkflowDispatcher(
                run_repository=run_repo,
                token_store=token_store,
                run_state_service=state_svc,
                create_execution_fn=create_exec_fn,
                clock=lambda: FIXED_NOW,
                max_running_workflows=1,
            )
            return await dispatcher.dispatch(trigger="concurrent-2")

    results = await asyncio.gather(
        _run_one_dispatcher(),
        _run_one_dispatcher(),
    )
    all_claimed = [r.id for batch in results for r in batch]
    assert len(all_claimed) == 1
    assert all_claimed == ["run-u1-00"]
    assert len(created_counter) == 1

    async with session_factory() as verify_session:
        repo = WorkflowRunRepository(db=verify_session)
        assert await repo.count_running() == 1


@pytest.mark.asyncio
async def test_twenty_parallel_dispatchers_never_double_claim_and_respect_cap(
    session_factory: async_sessionmaker[AsyncSession],
):
    """20 parallel dispatchers competing for 10 queued runs with cap=4 (§11.2 #7)."""
    await _seed_users_and_runs(session_factory, user_run_counts={1: 5, 2: 5})
    created_counter: list[int] = []
    create_exec_fn = _make_create_execution_fn(created_counter)

    async def _worker(idx: int) -> list[WorkflowRunModel]:
        async with session_factory() as session:
            run_repo = WorkflowRunRepository(db=session)
            session_repo = WorkflowUserSessionRepository(db=session)
            token_store = TokenStoreService(
                repository=session_repo,
                encryption_key=TEST_KEY,
                clock=lambda: FIXED_NOW,
            )
            state_svc = RunStateService(
                repository=run_repo,
                dispatch_hook=None,
                clock=lambda: FIXED_NOW,
            )
            dispatcher = WorkflowDispatcher(
                run_repository=run_repo,
                token_store=token_store,
                run_state_service=state_svc,
                create_execution_fn=create_exec_fn,
                clock=lambda: FIXED_NOW,
                max_running_workflows=4,
            )
            return await dispatcher.dispatch(trigger=f"parallel-{idx}")

    batches = await asyncio.gather(*[_worker(i) for i in range(20)])
    claimed_ids = [r.id for batch in batches for r in batch]

    # Cap is 4: at most 4 runs claimed total, zero duplicates, round-robin fairness.
    assert len(claimed_ids) == 4
    assert len(set(claimed_ids)) == 4
    assert set(claimed_ids) == {
        "run-u1-00",
        "run-u2-00",
        "run-u1-01",
        "run-u2-01",
    }
    assert len(created_counter) == 4

    async with session_factory() as verify_session:
        repo = WorkflowRunRepository(db=verify_session)
        assert await repo.count_running() == 4
        for rid in claimed_ids:
            run = await repo.get_by_id(rid)
            assert run is not None
            assert run.status == WorkflowRunStatusEnum.RUNNING
            assert len(run.execution_ids or []) == 1


@pytest.mark.asyncio
async def test_for_update_skip_locked_skips_rows_locked_by_concurrent_tx(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Direct verification of SELECT ... FOR UPDATE SKIP LOCKED across two sessions."""
    await _seed_users_and_runs(session_factory, user_run_counts={1: 3})

    async with session_factory() as session_a, session_factory() as session_b:
        repo_a = WorkflowRunRepository(db=session_a)
        repo_b = WorkflowRunRepository(db=session_b)

        # Session A locks all 3 queued rows and holds the transaction open.
        locked_a = await repo_a.lock_due_queued_runs(FIXED_NOW, limit=10)
        assert [r.id for (r, _) in locked_a] == [
            "run-u1-00",
            "run-u1-01",
            "run-u1-02",
        ]

        # Session B queries concurrently with SKIP LOCKED -> sees 0 rows without blocking.
        locked_b = await repo_b.lock_due_queued_runs(FIXED_NOW, limit=10)
        assert locked_b == []

        await session_a.rollback()
        await session_b.rollback()
