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
"""Tests for the step-checkpoint helpers of ``WorkflowRunRepository``."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.workflows.repository.workflow_run_repository import (
    RunStepContext,
    WorkflowRunRepository,
)

pytestmark = pytest.mark.anyio

RUN_ID = "run-1"
STEP_ID = "image_1"


def _repository(row=None) -> tuple[WorkflowRunRepository, AsyncMock]:
    db = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = row
    db.execute.return_value = result
    return WorkflowRunRepository(db), db


def _compiled(db: AsyncMock):
    statement = db.execute.await_args.args[0]
    return statement.compile(dialect=postgresql.dialect())


async def test_lock_step_context_locks_the_run_row():
    repository, db = _repository(
        SimpleNamespace(user_id=7, attempt_count=2, step_states={"a": {}})
    )

    context = await repository.lock_step_context(RUN_ID)

    assert context == RunStepContext(
        user_id=7, attempt_count=2, step_states={"a": {}}
    )
    compiled = _compiled(db)
    sql = str(compiled)
    assert "FROM workflow_runs" in sql
    assert "WHERE workflow_runs.id = " in sql
    assert sql.rstrip().endswith("FOR UPDATE")
    assert RUN_ID in compiled.params.values()
    # The caller owns the transaction.
    db.commit.assert_not_called()


async def test_lock_step_context_defaults_null_columns():
    repository, _ = _repository(
        SimpleNamespace(user_id=7, attempt_count=None, step_states=None)
    )

    context = await repository.lock_step_context(RUN_ID)

    assert context == RunStepContext(user_id=7, attempt_count=0, step_states={})


async def test_lock_step_context_returns_none_for_unknown_run():
    repository, _ = _repository(None)

    assert await repository.lock_step_context("missing") is None


async def test_set_step_state_writes_only_that_step_key():
    repository, db = _repository()
    state = {"status": "running", "job_id": 812}

    await repository.set_step_state(RUN_ID, STEP_ID, state)

    compiled = _compiled(db)
    sql = str(compiled)
    assert sql.startswith("UPDATE workflow_runs SET step_states=jsonb_set(")
    assert "coalesce(workflow_runs.step_states, " in sql
    assert "WHERE workflow_runs.id = " in sql
    params = list(compiled.params.values())
    assert [STEP_ID] in params
    assert state in params
    assert {} in params  # coalesce() fallback for NULL step_states
    assert RUN_ID in params
    db.commit.assert_not_called()


async def test_lock_run_locks_and_validates_run_model():
    repository, db = _repository()
    orm_row = {
        "id": RUN_ID,
        "workflow_id": "wf-1",
        "user_id": 7,
        "workspace_id": 1,
        "status": "running",
        "started_at": "2026-04-17T12:00:00Z",
        "workflow_snapshot": {},
    }
    db.execute.return_value.scalar_one_or_none.return_value = orm_row

    run = await repository.lock_run(RUN_ID)

    assert run is not None
    assert run.id == RUN_ID
    assert run.user_id == 7
    compiled = _compiled(db)
    sql = str(compiled)
    assert "FROM workflow_runs" in sql
    assert sql.rstrip().endswith("FOR UPDATE")
    db.commit.assert_not_called()


async def test_lock_run_returns_none_when_missing():
    repository, db = _repository()
    db.execute.return_value.scalar_one_or_none.return_value = None

    assert await repository.lock_run("missing") is None


async def test_get_by_id_populates_existing_identity_map_entry():
    repository, db = _repository()
    orm_row = {
        "id": RUN_ID,
        "workflow_id": "wf-1",
        "user_id": 7,
        "workspace_id": 1,
        "status": "running",
        "started_at": "2026-04-17T12:00:00Z",
        "workflow_snapshot": {},
    }
    db.execute.return_value.scalar_one_or_none.return_value = orm_row

    run = await repository.get_by_id(RUN_ID)

    assert run is not None
    assert run.id == RUN_ID
    assert run.status == "running"
    statement = db.execute.await_args.args[0]
    assert statement.get_execution_options().get("populate_existing") is True

    db.execute.return_value.scalar_one_or_none.return_value = None
    assert await repository.get_by_id("missing") is None


async def test_update_fields_updates_selected_columns_without_committing():
    repository, db = _repository()

    await repository.update_fields(
        RUN_ID, {"status": "COMPLETED", "queue_reason": None}
    )

    compiled = _compiled(db)
    sql = str(compiled)
    assert sql.startswith("UPDATE workflow_runs SET ")
    assert "status=" in sql
    assert "queue_reason=" in sql
    assert "WHERE workflow_runs.id = " in sql
    assert RUN_ID in compiled.params.values()
    db.commit.assert_not_called()


async def test_advisory_lock_and_count_helpers():
    import datetime

    repository, db = _repository()
    db.execute.return_value.scalar_one.return_value = True
    assert await repository.try_advisory_xact_lock(12345) is True

    db.execute.return_value.scalar_one.return_value = 3
    assert await repository.count_running() == 3
    assert await repository.count_active_by_workflow("wf-1") == 3

    db.execute.return_value.scalar_one_or_none.return_value = "run-1"
    now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
    assert (
        await repository.has_due_work(
            user_id=7, now=now, max_running_workflows=5
        )
        is True
    )
    compiled = _compiled(db)
    sql = str(compiled)
    assert "SELECT count(*) AS count_1" in sql
    assert "workflow_runs.dispatched_at IS NULL" in sql
    assert "workflow_runs.dispatched_at <=" in sql
    params = list(compiled.params.values())
    assert 5 in params
    assert (now - datetime.timedelta(seconds=60)) in params

    db.execute.return_value.scalar_one_or_none.return_value = None
    assert await repository.has_due_work(now=now) is False


async def test_unpark_session_waiting_and_append_execution_id():
    import datetime

    now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
    repository, db = _repository()
    waiting_row = {
        "id": RUN_ID,
        "workflow_id": "wf-1",
        "user_id": 7,
        "workspace_id": 1,
        "status": "queued",
        "started_at": now - datetime.timedelta(minutes=10),
        "queued_at": now - datetime.timedelta(minutes=10),
        "queue_reason": "WAITING_FOR_SESSION",
        "waiting_for_session_since": now - datetime.timedelta(minutes=2),
        "session_wait_seconds": 30,
        "workflow_snapshot": {},
    }
    db.execute.return_value.scalars.return_value.all.return_value = [
        waiting_row
    ]
    unparked = await repository.unpark_session_waiting_runs(7, now)
    assert unparked == 1

    await repository.append_execution_id(
        RUN_ID, {"execution_id": "exec-9", "state": "ACTIVE"}
    )
    compiled = _compiled(db)
    assert "UPDATE workflow_runs SET execution_ids=" in str(compiled)


async def test_list_by_workflow_and_compute_queue_positions():
    import datetime

    now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
    repository, db = _repository()
    row_dict = {
        "id": RUN_ID,
        "workflow_id": "wf-1",
        "user_id": 7,
        "workspace_id": 1,
        "status": "queued",
        "started_at": now,
        "queued_at": now,
        "workflow_snapshot": {},
    }
    count_res = MagicMock()
    count_res.scalar_one.return_value = 1
    items_res = MagicMock()
    items_res.scalars.return_value.all.return_value = [row_dict]
    db.execute.side_effect = [count_res, items_res]

    items, total = await repository.list_by_workflow(
        "wf-1", user_id=7, status="queued", limit=10, offset=0
    )
    assert total == 1
    assert len(items) == 1
    assert items[0].id == RUN_ID

    assert await repository.compute_queue_positions([]) == {}
    pos_res = MagicMock()
    pos_res.scalars.return_value.all.return_value = ["other", RUN_ID]
    db.execute.side_effect = [pos_res]
    positions = await repository.compute_queue_positions([RUN_ID])
    assert positions == {RUN_ID: 2}


def test_alembic_import_order_has_no_circular_import():
    """Importing workflow_run_model first in a fresh interpreter (as alembic/env.py does) succeeds."""
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.workflows.schema.workflow_run_model import"
                " WorkflowRun, WorkflowUserSession, QueueReasonEnum;"
                " from src.workflows.queue.workflow_dispatcher import"
                " WorkflowDispatcher"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
