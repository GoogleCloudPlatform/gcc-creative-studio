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

"""Unit tests for WorkflowDispatcher and global-cap round-robin scheduling (§8.1, §11.1)."""

import datetime
import random
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.queue.workflow_dispatcher import (
    WorkflowDispatcher,
    build_execution_args,
    pick_runs_round_robin,
)
from src.workflows.schema.workflow_model import (
    NodeTypes,
    StepStatusEnum,
    WorkflowModel,
    WorkflowRunStatusEnum,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepState,
    WorkflowRunExecution,
    WorkflowRunModel,
)
from src.workflows.workflow_yaml_builder import YAML_VERSION

pytestmark = pytest.mark.anyio

FIXED_NOW = datetime.datetime(2026, 9, 28, 12, 0, 0, tzinfo=datetime.UTC)


def _snapshot_two_steps() -> dict[str, Any]:
    return {
        "id": "wf-1",
        "user_id": 1,
        "name": "Two Step WF",
        "steps": [
            {
                "step_id": "user_input",
                "type": NodeTypes.USER_INPUT.value,
                "status": StepStatusEnum.PENDING.value,
                "inputs": {},
                "settings": {},
            },
            {
                "step_id": "step_a",
                "type": NodeTypes.GENERATE_TEXT.value,
                "status": StepStatusEnum.PENDING.value,
                "inputs": {"prompt": {"step": "user_input", "output": "topic"}},
                "settings": {"model": "gemini-2.5-flash", "temperature": 0.7},
            },
            {
                "step_id": "step_b",
                "type": NodeTypes.IMAGE.value,
                "status": StepStatusEnum.PENDING.value,
                "inputs": {
                    "prompt": {
                        "step": "step_a",
                        "output": "generated_text",
                    }
                },
                "settings": {"model": "gemini-3.1-flash-image"},
            },
        ],
    }


def _make_run(
    run_id: str,
    user_id: int = 1,
    *,
    queued_offset_seconds: int = 0,
    queue_reason: QueueReasonEnum | None = QueueReasonEnum.WAITING_FOR_SLOT,
    attempt_count: int = 0,
    next_retry_at: datetime.datetime | None = None,
    step_states: dict[str, StepState] | None = None,
    last_error_category: ErrorCategory | None = None,
    input_args: dict[str, Any] | None = None,
) -> WorkflowRunModel:
    ts = FIXED_NOW + datetime.timedelta(seconds=queued_offset_seconds)
    return WorkflowRunModel(
        id=run_id,
        workflow_id="wf-1",
        user_id=user_id,
        workspace_id=10,
        status=WorkflowRunStatusEnum.QUEUED,
        queue_reason=queue_reason,
        started_at=ts,
        queued_at=ts,
        next_retry_at=next_retry_at,
        attempt_count=attempt_count,
        last_error_category=last_error_category,
        workflow_snapshot=_snapshot_two_steps(),
        input_args=input_args or {"topic": "space", "workspace_id": 10},
        step_states=step_states or {},
    )


class _InMemoryQueueHarness:
    """In-memory harness backing WorkflowRunRepository + TokenStoreService for
    multi-tick round-robin simulation.
    """

    def __init__(self, *, try_lock: bool = True) -> None:
        self.runs: dict[str, WorkflowRunModel] = {}
        self.last_dispatched_at: dict[int, datetime.datetime | None] = {}
        self.tokens: dict[int, str | None] = {}
        self.try_lock = try_lock
        self.created_executions: list[tuple[str, dict[str, Any]]] = []

        self.run_repo = MagicMock()
        self.run_repo.db = AsyncMock()
        self.run_repo.try_advisory_xact_lock = AsyncMock(
            side_effect=lambda _key: self.try_lock
        )
        self.run_repo.count_running = AsyncMock(side_effect=self._count_running)
        self.run_repo.lock_due_queued_runs = AsyncMock(
            side_effect=self._lock_due_queued_runs
        )
        self.run_repo.update_fields = AsyncMock(side_effect=self._update_fields)
        self.run_repo.append_execution_id = AsyncMock(
            side_effect=self._append_execution_id
        )
        self.run_repo.find_active_for_reconciliation = AsyncMock(
            return_value=[]
        )

        self.token_store = MagicMock()
        self.token_store.get_valid_token = AsyncMock(
            side_effect=lambda uid: self.tokens.get(uid)
        )
        self.token_store.touch_last_dispatched_at = AsyncMock(
            side_effect=self._touch_last_dispatched_at
        )

    async def _count_running(self) -> int:
        return sum(
            1
            for r in self.runs.values()
            if WorkflowRunStatusEnum(r.status) is WorkflowRunStatusEnum.RUNNING
        )

    async def _lock_due_queued_runs(
        self, now: datetime.datetime, *, limit: int = 200
    ) -> list[tuple[WorkflowRunModel, datetime.datetime | None]]:
        items: list[tuple[WorkflowRunModel, datetime.datetime | None]] = []
        for r in self.runs.values():
            if (
                WorkflowRunStatusEnum(r.status)
                is not WorkflowRunStatusEnum.QUEUED
            ):
                continue
            if r.next_retry_at is not None and r.next_retry_at > now:
                continue
            items.append((r, self.last_dispatched_at.get(r.user_id)))
        items.sort(
            key=lambda pair: (
                pair[1] is not None,
                pair[1] or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                pair[0].queued_at or pair[0].started_at,
                pair[0].id,
            )
        )
        return items[:limit]

    async def _update_fields(self, run_id: str, values: dict[str, Any]) -> None:
        run = self.runs[run_id]
        patched = dict(values)
        if "status" in patched and patched["status"] is not None:
            patched["status"] = WorkflowRunStatusEnum(patched["status"])
        if "queue_reason" in patched and patched["queue_reason"] is not None:
            patched["queue_reason"] = QueueReasonEnum(patched["queue_reason"])
        if (
            "last_error_category" in patched
            and patched["last_error_category"] is not None
        ):
            patched["last_error_category"] = ErrorCategory(
                patched["last_error_category"]
            )
        self.runs[run_id] = run.model_copy(update=patched)

    async def _append_execution_id(
        self, run_id: str, entry: dict[str, Any]
    ) -> None:
        run = self.runs[run_id]
        exec_item = WorkflowRunExecution.model_validate(entry)
        self.runs[run_id] = run.model_copy(
            update={"execution_ids": [*run.execution_ids, exec_item]}
        )

    async def _touch_last_dispatched_at(
        self, user_id: int, *, now: datetime.datetime | None = None
    ) -> None:
        self.last_dispatched_at[user_id] = now or FIXED_NOW

    async def create_execution(
        self, run: WorkflowRunModel, args: dict[str, Any]
    ) -> str:
        self.created_executions.append((run.id, args))
        return f"exec-{run.id}"

    def complete_one_running(self) -> str:
        for run_id, r in self.runs.items():
            if WorkflowRunStatusEnum(r.status) is WorkflowRunStatusEnum.RUNNING:
                self.runs[run_id] = r.model_copy(
                    update={"status": WorkflowRunStatusEnum.COMPLETED}
                )
                return run_id
        raise AssertionError("No RUNNING run to complete")


async def test_global_cap_round_robin_u1_50_runs_then_u2_5_runs_alternates():
    """H2 & H3: U1 alone with 50 runs fills all 20 slots; U2 submits 5; as slots
    free one by one the dispatch order alternates U2, U1, U2, U1...
    """
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = "jwt.u1.token"
    harness.tokens[2] = "jwt.u2.token"

    for idx in range(50):
        run = _make_run(f"u1-{idx:02d}", user_id=1, queued_offset_seconds=idx)
        harness.runs[run.id] = run

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=harness.create_execution,
        clock=lambda: FIXED_NOW,
        max_running_workflows=20,
    )

    # First dispatch: U1 is alone and fills all 20 global slots; 30 stay QUEUED.
    claimed_batch_1 = await dispatcher.dispatch("submit", run_reconciler=False)
    assert len(claimed_batch_1) == 20
    assert await harness._count_running() == 20
    queued_u1 = [
        r
        for r in harness.runs.values()
        if r.status == WorkflowRunStatusEnum.QUEUED
    ]
    assert len(queued_u1) == 30
    assert all(
        r.queue_reason == QueueReasonEnum.WAITING_FOR_SLOT for r in queued_u1
    )

    # Now U2 submits 5 runs while all 20 slots are occupied.
    for idx in range(5):
        run = _make_run(
            f"u2-{idx:02d}", user_id=2, queued_offset_seconds=100 + idx
        )
        harness.runs[run.id] = run

    # Dispatch while slots are full -> 0 claimed (global cap never exceeded).
    assert await dispatcher.dispatch("submit", run_reconciler=False) == []
    assert await harness._count_running() == 20

    # Free slots one by one: dispatch order must alternate U2, U1, U2, U1, U2, U1!
    dispatched_users: list[int] = []
    for _ in range(6):
        harness.complete_one_running()
        newly_dispatched = await dispatcher.dispatch(
            "completion", run_reconciler=False
        )
        assert len(newly_dispatched) == 1
        assert await harness._count_running() == 20
        dispatched_users.append(newly_dispatched[0].user_id)

    assert dispatched_users == [2, 1, 2, 1, 2, 1]


def test_pick_runs_round_robin_u3_with_null_last_dispatched_goes_first():
    u1_run = _make_run("r-u1", user_id=1, queued_offset_seconds=1)
    u2_run = _make_run("r-u2", user_id=2, queued_offset_seconds=2)
    u3_run = _make_run("r-u3", user_id=3, queued_offset_seconds=10)

    candidates = [
        (u1_run, FIXED_NOW - datetime.timedelta(minutes=5)),
        (u2_run, FIXED_NOW - datetime.timedelta(minutes=1)),
        (u3_run, None),  # U3 has NULL last_dispatched_at -> goes first!
    ]
    picked, unpicked = pick_runs_round_robin(candidates, slots=2)
    assert [r.user_id for r in picked] == [3, 1]
    assert [r.user_id for r in unpicked] == [2]


async def test_expired_token_user_skipped_and_marked_waiting_for_session():
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = None  # Expired / missing token for user 1
    harness.tokens[2] = "jwt.u2.token"

    r1 = _make_run("r-expired-u1", user_id=1, queued_offset_seconds=1)
    r2 = _make_run("r-valid-u2", user_id=2, queued_offset_seconds=2)
    harness.runs[r1.id] = r1
    harness.runs[r2.id] = r2

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=harness.create_execution,
        clock=lambda: FIXED_NOW,
        max_running_workflows=20,
    )
    dispatched = await dispatcher.dispatch("tick", run_reconciler=False)

    assert [r.id for r in dispatched] == ["r-valid-u2"]
    updated_r1 = harness.runs["r-expired-u1"]
    assert updated_r1.status == WorkflowRunStatusEnum.QUEUED
    assert updated_r1.queue_reason == QueueReasonEnum.WAITING_FOR_SESSION
    assert updated_r1.waiting_for_session_since == FIXED_NOW


async def test_next_retry_at_in_future_is_skipped():
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = "jwt.u1.token"

    future_run = _make_run(
        "r-future",
        user_id=1,
        queue_reason=QueueReasonEnum.RETRY_SCHEDULED,
        next_retry_at=FIXED_NOW + datetime.timedelta(minutes=5),
    )
    due_run = _make_run(
        "r-due",
        user_id=1,
        queue_reason=QueueReasonEnum.RETRY_SCHEDULED,
        next_retry_at=FIXED_NOW - datetime.timedelta(seconds=1),
    )
    harness.runs[future_run.id] = future_run
    harness.runs[due_run.id] = due_run

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=harness.create_execution,
        clock=lambda: FIXED_NOW,
    )
    dispatched = await dispatcher.dispatch("tick", run_reconciler=False)
    assert [r.id for r in dispatched] == ["r-due"]
    assert harness.runs["r-future"].status == WorkflowRunStatusEnum.QUEUED


async def test_create_execution_failure_requeues_without_counting_as_step_attempt():
    """E16: create_execution fails -> back to QUEUED with backoff; not a step attempt."""
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = "jwt.u1.token"
    run = _make_run("r-fail-exec", user_id=1, attempt_count=0)
    harness.runs[run.id] = run

    async def failing_create_execution(
        _run: WorkflowRunModel, _args: dict[str, Any]
    ) -> str:
        raise RuntimeError("503 Service Unavailable from GCP Workflows")

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=failing_create_execution,
        clock=lambda: FIXED_NOW,
        rng=random.Random(42),
    )
    results = await dispatcher.dispatch("submit", run_reconciler=False)
    assert len(results) == 1

    updated = harness.runs["r-fail-exec"]
    assert updated.status == WorkflowRunStatusEnum.QUEUED
    assert updated.queue_reason == QueueReasonEnum.RETRY_SCHEDULED
    assert updated.attempt_count == 0
    assert updated.last_error_category == ErrorCategory.TRANSIENT
    assert (
        updated.next_retry_at is not None and updated.next_retry_at > FIXED_NOW
    )


async def test_continuation_and_session_resume_do_not_increment_attempt_count():
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = "jwt.u1.token"

    r_cont = _make_run(
        "r-cont",
        user_id=1,
        queue_reason=QueueReasonEnum.STEP_IN_PROGRESS,
        attempt_count=2,
    )
    r_sess = _make_run(
        "r-sess",
        user_id=1,
        queue_reason=QueueReasonEnum.WAITING_FOR_SLOT,
        last_error_category=ErrorCategory.AUTH_EXPIRED,
        attempt_count=3,
    )
    r_initial = _make_run(
        "r-init",
        user_id=1,
        queue_reason=QueueReasonEnum.WAITING_FOR_SLOT,
        attempt_count=0,
    )
    harness.runs[r_cont.id] = r_cont
    harness.runs[r_sess.id] = r_sess
    harness.runs[r_initial.id] = r_initial

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=harness.create_execution,
        clock=lambda: FIXED_NOW,
    )
    await dispatcher.dispatch("tick", run_reconciler=False)

    assert harness.runs["r-cont"].attempt_count == 2
    assert harness.runs["r-sess"].attempt_count == 3
    assert harness.runs["r-init"].attempt_count == 1


async def test_outdated_yaml_version_triggers_redeploy_before_create_execution():
    """E14 & Q13: outdated yaml_version -> redeploy called before create_execution."""
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = "jwt.u1.token"
    run = _make_run("r-redeploy", user_id=1)
    harness.runs[run.id] = run

    call_order: list[str] = []

    async def ensure_yaml(r: WorkflowRunModel) -> None:
        call_order.append(f"ensure_yaml:{r.workflow_id}:{YAML_VERSION}")

    async def create_exec(r: WorkflowRunModel, args: dict[str, Any]) -> str:
        call_order.append(f"create_execution:{r.id}")
        return await harness.create_execution(r, args)

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        ensure_yaml_current_fn=ensure_yaml,
        create_execution_fn=create_exec,
        clock=lambda: FIXED_NOW,
    )
    await dispatcher.dispatch("submit", run_reconciler=False)

    assert call_order == [
        f"ensure_yaml:wf-1:{YAML_VERSION}",
        "create_execution:r-redeploy",
    ]


async def test_token_injected_into_execution_args_not_persisted_and_prior_outputs_filtered():
    """Token injected into args but not persisted in input_args; prior_outputs
    contains only referenced completed outputs (Q7).
    """
    harness = _InMemoryQueueHarness()
    harness.tokens[1] = "secret.jwt.token"

    step_states = {
        "step_a": StepState(
            status=StepStatusEnum.COMPLETED,
            outputs={
                "generated_text": "hello world",
                "unused_meta": "should-not-be-sent",
            },
        ),
        "step_b": StepState(status=StepStatusEnum.FAILED, attempts=1),
    }
    run = _make_run(
        "r-args",
        user_id=1,
        step_states=step_states,
        input_args={"topic": "mars", "workspace_id": 10},
    )
    harness.runs[run.id] = run

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=harness.create_execution,
        clock=lambda: FIXED_NOW,
    )
    await dispatcher.dispatch("submit", run_reconciler=False)

    assert len(harness.created_executions) == 1
    _, sent_args = harness.created_executions[0]
    assert sent_args["run_id"] == "r-args"
    assert sent_args["user_auth_header"] == "Bearer secret.jwt.token"
    assert sent_args["prior_outputs"] == {
        "step_a": {"generated_text": "hello world"}
    }
    # Token is never persisted in the run's input_args!
    assert "user_auth_header" not in harness.runs["r-args"].input_args


def test_build_execution_args_switches_to_fetch_checkpoint_when_large():
    huge_text = "x" * (40 * 1024)
    step_states = {
        "step_a": StepState(
            status=StepStatusEnum.COMPLETED,
            outputs={"generated_text": huge_text},
        )
    }
    run = _make_run("r-large", step_states=step_states)
    args = build_execution_args(run, "jwt.tok.val")
    assert "prior_outputs" not in args
    assert args["fetch_checkpoint"] is True


async def test_try_lock_held_returns_immediately():
    """E4: Second concurrent dispatcher sees try-lock held -> returns immediately."""
    harness = _InMemoryQueueHarness(try_lock=False)
    harness.tokens[1] = "jwt.u1.token"
    harness.runs["r-1"] = _make_run("r-1", user_id=1)

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        create_execution_fn=harness.create_execution,
        clock=lambda: FIXED_NOW,
    )
    claimed = await dispatcher.dispatch("tick", run_reconciler=False)
    assert claimed == []
    assert harness.created_executions == []
    harness.run_repo.count_running.assert_not_called()


async def test_reconcile_pass_fetches_gcp_state_and_handles_stale_claims():
    """Reconcile synchronizes active RUNNING runs with GCP and handles QUEUED/STEP_FAILED."""
    from src.workflows.schema.workflow_run_model import WorkflowRunExecution

    harness = _InMemoryQueueHarness()
    running_with_exec = _make_run(
        "r-active",
        user_id=1,
    ).model_copy(
        update={
            "status": WorkflowRunStatusEnum.RUNNING,
            "dispatched_at": FIXED_NOW - datetime.timedelta(minutes=5),
            "execution_ids": [
                WorkflowRunExecution(
                    execution_id="exec-1",
                    started_at=FIXED_NOW - datetime.timedelta(minutes=5),
                    state="ACTIVE",
                )
            ],
        }
    )
    stale_claimed = _make_run(
        "r-stale",
        user_id=1,
    ).model_copy(
        update={
            "status": WorkflowRunStatusEnum.RUNNING,
            "dispatched_at": FIXED_NOW - datetime.timedelta(minutes=5),
            "execution_ids": [],
        }
    )
    harness.run_repo.find_active_for_reconciliation = AsyncMock(
        return_value=[running_with_exec, stale_claimed]
    )

    state_svc = MagicMock()
    state_svc.reconcile_run = AsyncMock(
        side_effect=lambda r, **kw: r.model_copy(
            update={"status": WorkflowRunStatusEnum.COMPLETED}
        )
    )

    async def fetch_gcp(
        r: WorkflowRunModel, exec_id: str
    ) -> tuple[str | None, Any]:
        return ("SUCCEEDED", None)

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        run_state_service=state_svc,
        fetch_gcp_execution_fn=fetch_gcp,
        clock=lambda: FIXED_NOW,
    )
    reconciled = await dispatcher.reconcile()
    assert len(reconciled) == 2
    assert state_svc.reconcile_run.await_count == 2


async def test_default_gcp_clients_and_ensure_yaml_via_workflow_repo():
    """Tests default _ensure_yaml_current, _create_execution, and _fetch_gcp_execution paths."""
    from contextlib import asynccontextmanager
    from unittest.mock import patch
    from src.workflows.queue.workflow_dispatcher import run_default_dispatch

    harness = _InMemoryQueueHarness()
    run = _make_run("r-gcp", user_id=1)

    wf_repo = MagicMock()
    wf_repo.db = MagicMock()
    wf_repo.db.commit = AsyncMock()
    outdated_wf = MagicMock()
    outdated_wf.yaml_version = 1
    wf_repo.get_by_id = AsyncMock(return_value=outdated_wf)

    dispatcher = WorkflowDispatcher(
        run_repository=harness.run_repo,
        token_store=harness.token_store,
        workflow_repository=wf_repo,
        clock=lambda: FIXED_NOW,
    )

    with patch(
        "src.workflows.workflow_service.WorkflowService.ensure_yaml_current",
        new_callable=AsyncMock,
    ) as mock_ensure:
        await dispatcher._ensure_yaml_current(run)
        mock_ensure.assert_awaited_once_with(outdated_wf)
        wf_repo.db.commit.assert_awaited_once()

    with patch(
        "src.workflows.queue.workflow_dispatcher.executions_v1.ExecutionsAsyncClient"
    ) as mock_exec_cls:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.name = (
            "projects/p/locations/l/workflows/wf-1/executions/exec-gcp-99"
        )
        mock_client.create_execution = AsyncMock(return_value=mock_resp)

        mock_get_resp = MagicMock()
        mock_get_resp.state.name = "FAILED"
        mock_get_resp.error.payload = '{"code": 503}'
        mock_get_resp.error.context = "ctx"
        mock_client.get_execution = AsyncMock(return_value=mock_get_resp)
        mock_exec_cls.return_value = mock_client

        exec_id = await dispatcher._create_execution(run, {"run_id": "r-gcp"})
        assert exec_id == "exec-gcp-99"

        state_name, err_payload = await dispatcher._fetch_gcp_execution(
            run, "exec-gcp-99"
        )
        assert state_name == "FAILED"
        assert err_payload["payload"] == '{"code": 503}'

        mock_client.get_execution.side_effect = RuntimeError("rpc failed")
        state_err, payload_err = await dispatcher._fetch_gcp_execution(
            run, "exec-gcp-99"
        )
        assert state_err is None
        assert payload_err is None

    @asynccontextmanager
    async def fake_session_local():
        yield MagicMock()

    with (
        patch(
            "src.workflows.queue.workflow_dispatcher.async_session_local",
            fake_session_local,
        ),
        patch.object(
            WorkflowDispatcher,
            "dispatch",
            new_callable=AsyncMock,
            return_value=[run],
        ) as mock_disp,
    ):
        dispatched = await run_default_dispatch("hook", 1)
        assert dispatched == [run]
        mock_disp.assert_awaited_once_with(trigger="hook", user_id=1)
