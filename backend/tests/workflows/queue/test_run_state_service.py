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

"""Unit tests for RunStateService (spec §6, §7.3, §8.3, §8.4, §11.1)."""

import datetime
import random
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.workflows.dto.workflow_run_dto import (
    ExecutionCallbackStatusEnum,
    RunCheckpointResponseDto,
    RunFinishedCallbackDto,
    RunFinishedResponseDto,
    WorkflowRunDetailDto,
    WorkflowRunSummaryDto,
)
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.queue.run_state_service import (
    MissingResumeInputsError,
    RunStateService,
    fold_session_wait,
    get_dispatch_hook,
    set_dispatch_hook,
)
from src.workflows.workflow_yaml_builder import (
    compute_definition_hash,
    compute_step_hash,
)
from src.workflows.schema.workflow_model import (
    StepStatusEnum,
    WorkflowRunStatusEnum,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepErrorInfo,
    StepState,
    WorkflowRunExecution,
    WorkflowRunModel,
)
from src.workflows_executor.step_errors import StepError

BASE_TIME = datetime.datetime(2026, 4, 17, 12, 0, 0, tzinfo=datetime.UTC)


def _snapshot_with_two_steps(
    *, with_user_input: bool = False
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    if with_user_input:
        steps.append(
            {
                "step_id": "user_in",
                "type": "user_input",
                "inputs": {},
                "settings": {},
            }
        )
    steps.extend(
        [
            {
                "step_id": "step_a",
                "type": "generate_text",
                "inputs": {
                    "prompt": (
                        {"step": "user_in", "output": "topic"}
                        if with_user_input
                        else "Write a haiku"
                    )
                },
                "settings": {
                    "model": "gemini-2.5-flash",
                    "temperature": 0.7,
                },
            },
            {
                "step_id": "step_b",
                "type": "image",
                "inputs": {
                    "prompt": {"step": "step_a", "output": "generated_text"}
                },
                "settings": {"model": "gemini-3.1-flash-image"},
            },
        ]
    )
    return {"name": "Two Step Workflow", "steps": steps}


def _make_run(**overrides: Any) -> WorkflowRunModel:
    defaults: dict[str, Any] = {
        "id": "run-123",
        "workflow_id": "wf-1",
        "user_id": 7,
        "workspace_id": 42,
        "status": WorkflowRunStatusEnum.RUNNING,
        "started_at": BASE_TIME - datetime.timedelta(minutes=5),
        "queued_at": BASE_TIME - datetime.timedelta(minutes=5),
        "dispatched_at": BASE_TIME - datetime.timedelta(minutes=4),
        "attempt_count": 1,
        "session_wait_seconds": 0,
        "current_step_id": "step_a",
        "execution_ids": [
            WorkflowRunExecution(
                execution_id="exec-1",
                started_at=BASE_TIME - datetime.timedelta(minutes=4),
                state="ACTIVE",
            )
        ],
        "step_states": {
            "step_a": StepState(
                status=StepStatusEnum.RUNNING,
                attempts=0,
                first_started_at=BASE_TIME - datetime.timedelta(minutes=4),
                started_at=BASE_TIME - datetime.timedelta(minutes=4),
            )
        },
        "workflow_snapshot": _snapshot_with_two_steps(),
        "input_args": {"workspace_id": 42},
    }
    defaults.update(overrides)
    return WorkflowRunModel(**defaults)


@pytest.fixture(name="mock_repo")
def fixture_mock_repo():
    repo = MagicMock()
    repo.db = MagicMock()
    repo.db.commit = AsyncMock()
    repo.db.rollback = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.lock_run = AsyncMock()
    repo.update_fields = AsyncMock(return_value=True)
    repo.set_step_state = AsyncMock()
    return repo


@pytest.fixture(name="service")
def fixture_service(mock_repo):
    return RunStateService(
        repository=mock_repo,
        clock=lambda: BASE_TIME,
        rng=random.Random(0),
        max_step_attempts=4,
        max_step_duration_seconds=3600,
        max_run_executions=8,
        max_run_age_hours=24,
        max_session_wait_days=7,
        retry_base_seconds=10.0,
        retry_max_seconds=300.0,
        continuation_delay_seconds=5.0,
    )


class TestInitAndHelpers:
    """Tests for constructor options, fold_session_wait, and dispatch hooks."""

    def test_get_run_state_service_dependency_factory(self, mock_repo):
        from src.workflows.queue.run_state_service import get_run_state_service

        svc = get_run_state_service(repository=mock_repo)
        assert isinstance(svc, RunStateService)

    def test_fold_session_wait_accumulates_active_span(self):
        run_idle = _make_run(
            session_wait_seconds=120, waiting_for_session_since=None
        )
        assert fold_session_wait(run_idle, BASE_TIME) == 120

        run_waiting = _make_run(
            session_wait_seconds=120,
            waiting_for_session_since=BASE_TIME - datetime.timedelta(minutes=3),
        )
        assert fold_session_wait(run_waiting, BASE_TIME) == 300

    @pytest.mark.anyio
    async def test_dispatch_hook_registration_and_error_isolation(
        self, mock_repo
    ):
        run = _make_run()
        mock_repo.lock_run.return_value = run

        calls: list[tuple[str, int | None]] = []

        async def async_hook(trigger: str, user_id: int | None) -> None:
            calls.append((trigger, user_id))

        set_dispatch_hook(async_hook)
        assert get_dispatch_hook() is async_hook
        try:
            svc = RunStateService(repository=mock_repo, clock=lambda: BASE_TIME)
            await svc.on_finished(
                "run-123",
                execution_id="exec-1",
                status="SUCCEEDED",
                user_id=7,
            )
            assert calls == [("completion", 7)]
        finally:
            set_dispatch_hook(None)
            assert get_dispatch_hook() is None

        # Failing hook must not break state transition.
        def failing_hook(_trigger: str, _user_id: int | None) -> None:
            raise RuntimeError("dispatcher boom")

        svc_failing = RunStateService(
            repository=mock_repo,
            dispatch_hook=failing_hook,
            clock=lambda: BASE_TIME,
        )
        result = await svc_failing.on_finished(
            "run-123",
            {"execution_id": "exec-1", "status": "SUCCEEDED"},
            user_id=7,
        )
        assert result.status == WorkflowRunStatusEnum.COMPLETED

    def test_dto_models_serialize_cleanly(self):
        run = _make_run()
        summary = WorkflowRunSummaryDto.model_validate(run.model_dump())
        detail = WorkflowRunDetailDto.model_validate(run.model_dump())
        checkpoint = RunCheckpointResponseDto(
            run_id=run.id, prior_outputs={"step_a": {"generated_text": "hi"}}
        )
        finished = RunFinishedResponseDto(
            run_id=run.id, status=WorkflowRunStatusEnum.COMPLETED
        )
        assert summary.id == "run-123"
        assert detail.workflow_snapshot is not None
        assert checkpoint.prior_outputs["step_a"]["generated_text"] == "hi"
        assert finished.status == WorkflowRunStatusEnum.COMPLETED


class TestGetCheckpoint:
    """Tests for RunStateService.get_checkpoint."""

    @pytest.mark.anyio
    async def test_get_checkpoint_filters_outputs_via_snapshot(
        self, service, mock_repo
    ):
        run = _make_run(
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={
                        "generated_text": "hello",
                        "extra_unreferenced": "drop-me",
                    },
                ),
                "step_b": StepState(
                    status=StepStatusEnum.RUNNING,
                    outputs={"images": [1]},
                ),
            }
        )
        mock_repo.get_by_id.return_value = run

        prior = await service.get_checkpoint(
            "run-123", user_id=7, execution_id="exec-1"
        )
        assert prior == {"step_a": {"generated_text": "hello"}}

    @pytest.mark.anyio
    async def test_get_checkpoint_fallback_when_snapshot_absent_or_invalid(
        self, service, mock_repo
    ):
        run = _make_run(
            workflow_snapshot={"steps": [{"invalid": True}]},
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "hello"},
                ),
                "step_b": StepState(
                    status=StepStatusEnum.FAILED,
                    outputs={"images": [1]},
                ),
            },
        )
        mock_repo.get_by_id.return_value = run

        prior = await service.get_checkpoint("run-123", user_id=7)
        assert prior == {"step_a": {"generated_text": "hello"}}

    @pytest.mark.anyio
    async def test_get_checkpoint_404_and_403(self, service, mock_repo):
        mock_repo.get_by_id.return_value = None
        with pytest.raises(StepError) as exc_404:
            await service.get_checkpoint("missing", user_id=7)
        assert exc_404.value.status_code == 404

        mock_repo.get_by_id.return_value = _make_run(user_id=99)
        with pytest.raises(StepError) as exc_403:
            await service.get_checkpoint("run-123", user_id=7)
        assert exc_403.value.status_code == 403


class TestOnFinished:
    """Tests for RunStateService.on_finished."""

    @pytest.mark.anyio
    async def test_on_finished_succeeded_marks_completed_and_clears_errors(
        self, service, mock_repo
    ):
        run = _make_run(
            last_error_category=ErrorCategory.TRANSIENT,
            last_error_detail="Previous error",
            waiting_for_session_since=BASE_TIME
            - datetime.timedelta(seconds=30),
            session_wait_seconds=10,
        )
        mock_repo.lock_run.return_value = run

        dto = RunFinishedCallbackDto(
            execution_id="exec-1",
            status=ExecutionCallbackStatusEnum.SUCCEEDED,
        )
        updated = await service.on_finished("run-123", dto, user_id=7)

        assert updated.status == WorkflowRunStatusEnum.COMPLETED
        assert updated.completed_at == BASE_TIME
        assert updated.last_error_category is None
        assert updated.last_error_detail is None
        assert updated.session_wait_seconds == 40
        assert updated.execution_ids[-1].state == "SUCCEEDED"
        assert updated.execution_ids[-1].ended_at == BASE_TIME
        mock_repo.update_fields.assert_awaited_once()
        mock_repo.db.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_on_finished_cancelled_with_empty_execution_ids(
        self, service, mock_repo
    ):
        run = _make_run(execution_ids=[])
        mock_repo.lock_run.return_value = run

        updated = await service.on_finished(
            "run-123",
            execution_id="exec-new",
            status=ExecutionCallbackStatusEnum.CANCELLED,
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.CANCELED
        assert len(updated.execution_ids) == 1
        assert updated.execution_ids[0].execution_id == "exec-new"
        assert updated.execution_ids[0].state == "CANCELLED"

    @pytest.mark.anyio
    async def test_on_finished_stale_execution_is_ignored(
        self, service, mock_repo
    ):
        run = _make_run()
        mock_repo.lock_run.return_value = run

        # Mismatched execution_id -> stale callback ignored.
        result = await service.on_finished(
            "run-123",
            execution_id="exec-old",
            status="SUCCEEDED",
            user_id=7,
        )
        assert result.status == WorkflowRunStatusEnum.RUNNING
        mock_repo.update_fields.assert_not_awaited()
        mock_repo.db.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_on_finished_missing_args_raises_value_error(self, service):
        with pytest.raises(
            ValueError, match="execution_id and status are required"
        ):
            await service.on_finished("run-123")

    @pytest.mark.anyio
    async def test_on_finished_failed_delegates_to_on_step_failed(
        self, service, mock_repo
    ):
        run = _make_run()
        mock_repo.lock_run.return_value = run

        updated = await service.on_finished(
            "run-123",
            {
                "execution_id": "exec-1",
                "status": "FAILED",
                "step_id": "step_a",
                "error": {
                    "code": 429,
                    "body": '{"category": "QUOTA", "detail": "Resource exhausted"}',
                },
            },
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.QUEUED
        assert updated.queue_reason == QueueReasonEnum.RETRY_SCHEDULED
        assert updated.last_error_category == ErrorCategory.QUOTA
        assert updated.attempt_count == 2
        assert updated.step_states["step_a"].attempts == 1

    @pytest.mark.anyio
    async def test_on_finished_rolls_back_on_db_error(self, service, mock_repo):
        mock_repo.lock_run.return_value = _make_run()
        mock_repo.update_fields.side_effect = RuntimeError("db write failed")
        mock_repo.db.rollback.side_effect = RuntimeError("rollback failed too")

        with pytest.raises(RuntimeError, match="db write failed"):
            await service.on_finished(
                "run-123",
                execution_id="exec-1",
                status="SUCCEEDED",
                user_id=7,
            )
        mock_repo.db.rollback.assert_awaited_once()


class TestOnStepFailedCategoriesAndTransitions:
    """Tests for failure categories, continuations, session wait, and caps."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("error_payload", "expected_category"),
        [
            (
                {"code": 503, "message": "Service Unavailable"},
                ErrorCategory.TRANSIENT,
            ),
            (
                {"code": 429, "message": "Quota exceeded"},
                ErrorCategory.QUOTA,
            ),
            (
                {"tags": ["TimeoutError"], "message": "Deadline exceeded"},
                ErrorCategory.TIMEOUT,
            ),
            (
                {"code": 500, "body": '{"detail": "Internal Server Error"}'},
                ErrorCategory.INTERNAL,
            ),
        ],
    )
    async def test_retryable_categories_advance_attempts_and_requeue(
        self, service, mock_repo, error_payload, expected_category
    ):
        run = _make_run(attempt_count=1)
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error=error_payload,
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        # Verify short-lived STEP_FAILED was persisted first, then final state.
        assert mock_repo.update_fields.await_count == 2
        first_call_fields = mock_repo.update_fields.await_args_list[0].args[1]
        assert (
            first_call_fields["status"]
            == WorkflowRunStatusEnum.STEP_FAILED.value
        )

        assert updated.status == WorkflowRunStatusEnum.QUEUED
        assert updated.queue_reason == QueueReasonEnum.RETRY_SCHEDULED
        assert updated.last_error_category == expected_category
        assert updated.attempt_count == 2
        assert updated.next_retry_at is not None
        assert updated.next_retry_at > BASE_TIME
        assert updated.step_states["step_a"].attempts == 1
        assert updated.step_states["step_a"].status == StepStatusEnum.FAILED
        assert updated.execution_ids[-1].state == "FAILED"

    @pytest.mark.anyio
    async def test_unknown_category_retries_once_then_parks_on_second_attempt(
        self, service, mock_repo
    ):
        # Attempt 1: UNKNOWN is retried once.
        run_attempt_1 = _make_run()
        mock_repo.lock_run.return_value = run_attempt_1

        updated_1 = await service.on_step_failed(
            "run-123",
            error="Mysterious failure with Bearer ya29.secret_token_value",
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )
        assert updated_1.status == WorkflowRunStatusEnum.QUEUED
        assert updated_1.last_error_category == ErrorCategory.UNKNOWN
        assert updated_1.step_states["step_a"].attempts == 1
        # Verify secret token was redacted from error detail.
        assert "ya29." not in (updated_1.last_error_detail or "")
        assert "[REDACTED]" in (updated_1.last_error_detail or "")

        # Attempt 2: UNKNOWN parks in NEEDS_ATTENTION.
        run_attempt_2 = _make_run(
            attempt_count=2,
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.RUNNING,
                    attempts=1,
                    first_started_at=BASE_TIME - datetime.timedelta(minutes=2),
                )
            },
        )
        mock_repo.lock_run.return_value = run_attempt_2

        updated_2 = await service.on_step_failed(
            "run-123",
            error="Mysterious failure again",
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )
        assert updated_2.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated_2.queue_reason is None
        assert updated_2.last_error_category == ErrorCategory.UNKNOWN
        assert updated_2.step_states["step_a"].attempts == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("error_payload", "expected_category"),
        [
            (
                {
                    "code": 422,
                    "body": {
                        "category": "SAFETY_BLOCK",
                        "detail": "Blocked by safety filter",
                    },
                },
                ErrorCategory.SAFETY_BLOCK,
            ),
            (
                {"code": 400, "body": {"error": {"message": "Bad prompt"}}},
                ErrorCategory.INVALID_INPUT,
            ),
            (
                {"code": 403, "body": "Permission denied on bucket"},
                ErrorCategory.FORBIDDEN,
            ),
            (
                {"code": 404, "message": "Source asset not found"},
                ErrorCategory.MISSING_RESOURCE,
            ),
        ],
    )
    async def test_terminal_categories_park_in_needs_attention_immediately(
        self, service, mock_repo, error_payload, expected_category
    ):
        run = _make_run(attempt_count=1)
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error=error_payload,
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated.queue_reason is None
        assert updated.next_retry_at is None
        assert updated.attempt_count == 1
        assert updated.last_error_category == expected_category
        assert updated.step_states["step_a"].attempts == 1
        assert updated.step_states["step_a"].status == StepStatusEnum.FAILED

    @pytest.mark.anyio
    async def test_step_in_progress_schedules_continuation_without_burning_attempts(
        self, service, mock_repo
    ):
        run = _make_run(
            attempt_count=1,
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.RUNNING,
                    job_id=555,
                    claim_id="claim-xyz",
                    attempts=0,
                    in_progress_continuations=0,
                    first_started_at=BASE_TIME - datetime.timedelta(minutes=5),
                )
            },
        )
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error={
                "code": 504,
                "body": {
                    "category": "STEP_IN_PROGRESS",
                    "detail": "Video job 555 still running",
                },
            },
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.QUEUED
        assert updated.queue_reason == QueueReasonEnum.STEP_IN_PROGRESS
        assert updated.next_retry_at == BASE_TIME + datetime.timedelta(
            seconds=5
        )
        # Neither step attempts nor run attempt_count are incremented.
        assert updated.attempt_count == 1
        step_state = updated.step_states["step_a"]
        assert step_state.attempts == 0
        assert step_state.in_progress_continuations == 1
        assert step_state.status == StepStatusEnum.RUNNING
        assert step_state.job_id == 555
        assert step_state.claim_id is None

    @pytest.mark.anyio
    async def test_auth_expired_parks_in_waiting_for_session_without_burning_attempts(
        self, service, mock_repo
    ):
        run = _make_run(
            attempt_count=1,
            current_step_id=None,
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.RUNNING,
                    attempts=1,
                    error=StepErrorInfo(
                        category=ErrorCategory.AUTH_EXPIRED,
                        http_status=401,
                        detail="Token expired",
                    ),
                )
            },
        )
        mock_repo.lock_run.return_value = run

        # Omit step_id and error so _resolve_step_id and _combine_error_signals
        # read from run.step_states["step_a"].
        updated = await service.on_step_failed(
            "run-123",
            error=None,
            step_id=None,
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.QUEUED
        assert updated.queue_reason == QueueReasonEnum.WAITING_FOR_SESSION
        assert updated.waiting_for_session_since == BASE_TIME
        assert updated.next_retry_at is None
        assert updated.attempt_count == 1
        assert updated.step_states["step_a"].attempts == 1
        assert updated.step_states["step_a"].status == StepStatusEnum.FAILED


class TestCapsAndInputValidation:
    """Tests for all 5 hard caps (spec §6) and missing required inputs."""

    @pytest.mark.anyio
    async def test_cap_max_step_attempts_exceeded(self, service, mock_repo):
        # max_step_attempts is 4; prior attempts=3 -> this failure is attempt 4.
        run = _make_run(
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.RUNNING,
                    attempts=3,
                    first_started_at=BASE_TIME - datetime.timedelta(minutes=5),
                )
            }
        )
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error={"code": 503, "message": "Transient error"},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_STEP_ATTEMPTS (4/4)" in (
            updated.last_error_detail or ""
        )

    @pytest.mark.anyio
    async def test_cap_max_step_duration_seconds_exceeded_on_continuation(
        self, service, mock_repo
    ):
        # max_step_duration_seconds is 3600 (1h); step started 61 minutes ago.
        run = _make_run(
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.RUNNING,
                    job_id=777,
                    attempts=0,
                    first_started_at=BASE_TIME - datetime.timedelta(minutes=61),
                )
            }
        )
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error={"code": 504, "body": {"category": "STEP_IN_PROGRESS"}},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_STEP_DURATION_SECONDS" in (
            updated.last_error_detail or ""
        )

    @pytest.mark.anyio
    async def test_cap_exceeded_from_executor_names_step_duration_cap(
        self, service, mock_repo
    ):
        run = _make_run()
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error={
                "code": 504,
                "body": {
                    "category": "CAP_EXCEEDED",
                    "detail": "Step polling exceeded duration",
                },
            },
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )
        assert updated.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_STEP_DURATION_SECONDS" in (
            updated.last_error_detail or ""
        )

    @pytest.mark.anyio
    async def test_cap_max_run_executions_exceeded(self, service, mock_repo):
        # max_run_executions is 8; run is already at attempt_count=8.
        run = _make_run(attempt_count=8)
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error={"code": 503, "message": "Backend unavailable"},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_RUN_EXECUTIONS (8/8)" in (
            updated.last_error_detail or ""
        )

    @pytest.mark.anyio
    async def test_cap_max_run_age_hours_excludes_session_wait_seconds(
        self, service, mock_repo
    ):
        # Run started 30h ago, but spent 10h in session wait -> effective age 20h (< 24h cap).
        run_within_cap = _make_run(
            queued_at=BASE_TIME - datetime.timedelta(hours=30),
            session_wait_seconds=10 * 3600,
        )
        mock_repo.lock_run.return_value = run_within_cap

        requeued = await service.on_step_failed(
            "run-123",
            error={"code": 503, "message": "Transient error"},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )
        assert requeued.status == WorkflowRunStatusEnum.QUEUED

        # Run started 30h ago with 0 session wait -> effective age 30h (>= 24h cap).
        run_over_cap = _make_run(
            queued_at=BASE_TIME - datetime.timedelta(hours=30),
            session_wait_seconds=0,
        )
        mock_repo.lock_run.return_value = run_over_cap

        parked = await service.on_step_failed(
            "run-123",
            error={"code": 503, "message": "Transient error"},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )
        assert parked.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert parked.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_RUN_AGE_HOURS (24h)" in (
            parked.last_error_detail or ""
        )

    @pytest.mark.anyio
    async def test_cap_max_session_wait_days_in_on_step_failed_and_expire_session_wait(
        self, service, mock_repo
    ):
        # 1. In on_step_failed when session_wait_seconds >= 7d.
        run_over_wait = _make_run(session_wait_seconds=7 * 86400)
        mock_repo.lock_run.return_value = run_over_wait

        parked = await service.on_step_failed(
            "run-123",
            error={"code": 401, "message": "Unauthorized"},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )
        assert parked.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert parked.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_SESSION_WAIT_DAYS (7d)" in (
            parked.last_error_detail or ""
        )

        # 2. In expire_session_wait when not yet expired -> returns unchanged.
        run_waiting_fresh = _make_run(
            status=WorkflowRunStatusEnum.QUEUED,
            queue_reason=QueueReasonEnum.WAITING_FOR_SESSION,
            waiting_for_session_since=BASE_TIME - datetime.timedelta(days=2),
            session_wait_seconds=0,
        )
        mock_repo.lock_run.return_value = run_waiting_fresh
        unchanged = await service.expire_session_wait("run-123", user_id=7)
        assert unchanged.status == WorkflowRunStatusEnum.QUEUED

        # 3. In expire_session_wait when >= 7d -> parks in NEEDS_ATTENTION.
        run_waiting_expired = _make_run(
            status=WorkflowRunStatusEnum.QUEUED,
            queue_reason=QueueReasonEnum.WAITING_FOR_SESSION,
            waiting_for_session_since=BASE_TIME - datetime.timedelta(days=8),
            session_wait_seconds=0,
        )
        mock_repo.lock_run.return_value = run_waiting_expired
        expired = await service.expire_session_wait("run-123", user_id=7)
        assert expired.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert expired.last_error_category == ErrorCategory.CAP_EXCEEDED
        assert "WORKFLOW_MAX_SESSION_WAIT_DAYS (7d)" in (
            expired.last_error_detail or ""
        )

    @pytest.mark.anyio
    async def test_missing_required_user_inputs_parks_as_invalid_input(
        self, service, mock_repo
    ):
        # Snapshot requires user_in.topic, but input_args only has workspace_id.
        run = _make_run(
            workflow_snapshot=_snapshot_with_two_steps(with_user_input=True),
            input_args={"workspace_id": 42},
        )
        mock_repo.lock_run.return_value = run

        updated = await service.on_step_failed(
            "run-123",
            error={"code": 503, "message": "Transient error"},
            step_id="step_a",
            execution_id="exec-1",
            user_id=7,
        )

        assert updated.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
        assert updated.last_error_category == ErrorCategory.INVALID_INPUT
        assert "Missing required workflow inputs" in (
            updated.last_error_detail or ""
        )
        assert "topic" in (updated.last_error_detail or "")


class TestResume:
    """Tests for RunStateService.resume (spec §9.1, §11.1 #4, E16, E17)."""

    @pytest.mark.anyio
    async def test_resume_reconciles_step_hashes_and_preserves_unchanged_completed(
        self, service, mock_repo
    ):
        old_snap = _snapshot_with_two_steps(with_user_input=True)
        # Add a third step_c in old snapshot that will be deleted in new_snap.
        old_snap["steps"].append(
            {
                "step_id": "step_c",
                "type": "generate_text",
                "inputs": {"prompt": "old c"},
                "settings": {"model": "gemini-2.5-flash", "temperature": 0.7},
            }
        )
        old_def_hash = compute_definition_hash(old_snap["steps"])
        run = _make_run(
            status=WorkflowRunStatusEnum.NEEDS_ATTENTION,
            definition_hash=old_def_hash,
            workflow_snapshot=old_snap,
            input_args={"workspace_id": 42, "topic": "cats"},
            last_error_category=ErrorCategory.INVALID_INPUT,
            last_error_detail="Model error",
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "haiku about cats"},
                    attempts=1,
                ),
                "step_b": StepState(
                    status=StepStatusEnum.FAILED,
                    job_id=888,
                    attempts=2,
                    error=StepErrorInfo(
                        category=ErrorCategory.INVALID_INPUT, detail="boom"
                    ),
                ),
                "step_c": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "c out"},
                ),
            },
        )
        mock_repo.lock_run.return_value = run

        # New snapshot keeps step_a identical, modifies step_b settings, drops step_c, adds step_d.
        new_snap = _snapshot_with_two_steps(with_user_input=True)
        new_snap["steps"][2]["settings"] = {"model": "gemini-3.1-pro-image"}
        new_snap["steps"].append(
            {
                "step_id": "step_d",
                "type": "generate_text",
                "inputs": {"prompt": "after b"},
                "settings": {"model": "gemini-2.5-flash", "temperature": 0.5},
            }
        )

        resumed = await service.resume(
            "run-123",
            user_id=7,
            current_workflow_snapshot=new_snap,
        )

        assert resumed.status == WorkflowRunStatusEnum.QUEUED
        assert resumed.queue_reason == QueueReasonEnum.RESUME_REQUESTED
        assert resumed.attempt_count == 0
        assert resumed.last_error_category is None
        assert resumed.last_error_detail is None
        assert resumed.definition_hash == compute_definition_hash(
            new_snap["steps"]
        )
        # step_a was COMPLETED and its hash didn't change -> kept COMPLETED + outputs.
        assert resumed.step_states["step_a"].status == StepStatusEnum.COMPLETED
        assert resumed.step_states["step_a"].outputs == {
            "generated_text": "haiku about cats"
        }
        # step_b was modified (and FAILED with PERMANENT) -> reset to PENDING, job_id cleared.
        assert resumed.step_states["step_b"].status == StepStatusEnum.PENDING
        assert resumed.step_states["step_b"].job_id is None
        assert resumed.step_states["step_b"].attempts == 0
        # step_c was deleted -> dropped from step_states.
        assert "step_c" not in resumed.step_states
        # step_d is new -> PENDING.
        assert resumed.step_states["step_d"].status == StepStatusEnum.PENDING

    @pytest.mark.anyio
    async def test_resume_args_override_invalidates_direct_and_transitive_steps(
        self, service, mock_repo
    ):
        snap = _snapshot_with_two_steps(with_user_input=True)
        # Add an independent step_indep that does NOT depend on user_in.topic.
        snap["steps"].append(
            {
                "step_id": "step_indep",
                "type": "generate_text",
                "inputs": {"prompt": "Static prompt"},
                "settings": {"model": "gemini-2.5-flash", "temperature": 0.7},
            }
        )
        def_hash = compute_definition_hash(snap["steps"])
        run = _make_run(
            status=WorkflowRunStatusEnum.NEEDS_ATTENTION,
            definition_hash=def_hash,
            workflow_snapshot=snap,
            input_args={"workspace_id": 42, "topic": "dogs"},
            last_error_category=ErrorCategory.INVALID_INPUT,
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "dogs haiku"},
                    attempts=1,
                ),
                "step_b": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"images": ["dog.png"]},
                    attempts=1,
                ),
                "step_indep": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "independent result"},
                    attempts=1,
                ),
            },
        )
        mock_repo.lock_run.return_value = run

        resumed = await service.resume(
            "run-123",
            user_id=7,
            args_override={"topic": "otters"},
            current_workflow_snapshot=snap,
        )

        assert resumed.input_args["topic"] == "otters"
        # step_a references user_in.topic directly -> reset to PENDING.
        assert resumed.step_states["step_a"].status == StepStatusEnum.PENDING
        assert resumed.step_states["step_a"].outputs is None
        # step_b depends on step_a transitively -> reset to PENDING.
        assert resumed.step_states["step_b"].status == StepStatusEnum.PENDING
        assert resumed.step_states["step_b"].outputs is None
        # step_indep does not depend on topic -> stays COMPLETED.
        assert (
            resumed.step_states["step_indep"].status == StepStatusEnum.COMPLETED
        )
        assert resumed.step_states["step_indep"].outputs == {
            "generated_text": "independent result"
        }

    @pytest.mark.anyio
    async def test_resume_preserves_job_id_only_on_cap_exceeded(
        self, service, mock_repo
    ):
        snap = _snapshot_with_two_steps()
        def_hash = compute_definition_hash(snap["steps"])
        run_cap = _make_run(
            status=WorkflowRunStatusEnum.NEEDS_ATTENTION,
            definition_hash=def_hash,
            workflow_snapshot=snap,
            last_error_category=ErrorCategory.CAP_EXCEEDED,
            step_states={
                "step_a": StepState(
                    status=StepStatusEnum.RUNNING,
                    job_id=555,
                    attempts=4,
                    first_started_at=BASE_TIME - datetime.timedelta(hours=2),
                ),
                "step_b": StepState(status=StepStatusEnum.PENDING),
            },
        )
        mock_repo.lock_run.return_value = run_cap

        resumed = await service.resume(
            "run-123",
            user_id=7,
            current_workflow_snapshot=snap,
        )
        assert resumed.step_states["step_a"].status == StepStatusEnum.PENDING
        assert resumed.step_states["step_a"].job_id == 555
        assert resumed.step_states["step_a"].attempts == 0
        assert resumed.step_states["step_a"].first_started_at is None

    @pytest.mark.anyio
    async def test_resume_pre_migration_null_step_states_or_null_hash_and_missing_inputs(
        self, service, mock_repo
    ):
        snap = _snapshot_with_two_steps(with_user_input=True)
        run_migrated = _make_run(
            status=WorkflowRunStatusEnum.NEEDS_ATTENTION,
            definition_hash=None,
            workflow_snapshot=snap,
            input_args=None,
            step_states=None,
        )
        mock_repo.lock_run.return_value = run_migrated

        # Without args_override supplying 'topic' -> raises MissingResumeInputsError (422).
        with pytest.raises(MissingResumeInputsError) as exc_info:
            await service.resume(
                "run-123",
                user_id=7,
                current_workflow_snapshot=snap,
            )
        assert exc_info.value.missing_inputs == ["topic"]

        # With args_override supplying 'topic' -> resets all steps to PENDING and computes hash.
        resumed = await service.resume(
            "run-123",
            user_id=7,
            args_override={"topic": "stars"},
            current_workflow_snapshot=snap,
        )
        assert resumed.status == WorkflowRunStatusEnum.QUEUED
        assert resumed.definition_hash == compute_definition_hash(snap["steps"])
        assert resumed.step_states["step_a"].status == StepStatusEnum.PENDING
        assert resumed.step_states["step_b"].status == StepStatusEnum.PENDING

    @pytest.mark.anyio
    async def test_resume_404_and_409_guards(self, service, mock_repo):
        mock_repo.lock_run.return_value = None
        with pytest.raises(StepError) as exc_404:
            await service.resume("run-123", user_id=7)
        assert exc_404.value.status_code == 404

        mock_repo.lock_run.return_value = _make_run(user_id=99)
        with pytest.raises(StepError) as exc_non_owner:
            await service.resume("run-123", user_id=7)
        assert exc_non_owner.value.status_code == 404

        mock_repo.lock_run.return_value = _make_run(
            status=WorkflowRunStatusEnum.RUNNING
        )
        with pytest.raises(StepError) as exc_409:
            await service.resume("run-123", user_id=7)
        assert exc_409.value.status_code == 409


class TestCancel:
    """Tests for RunStateService.cancel (spec §9.2, §11.1 #4)."""

    @pytest.mark.anyio
    async def test_cancel_queued_and_needs_attention_do_not_call_gcp_cancel(
        self, service, mock_repo
    ):
        cancel_fn = MagicMock()
        for initial_status in (
            WorkflowRunStatusEnum.QUEUED,
            WorkflowRunStatusEnum.NEEDS_ATTENTION,
        ):
            run = _make_run(status=initial_status)
            mock_repo.lock_run.return_value = run
            canceled = await service.cancel(
                "run-123", user_id=7, cancel_execution_fn=cancel_fn
            )
            assert canceled.status == WorkflowRunStatusEnum.CANCELED
            assert canceled.canceled_by_user is True
            assert canceled.completed_at == BASE_TIME
            cancel_fn.assert_not_called()

    @pytest.mark.anyio
    async def test_cancel_running_invokes_cancel_execution_fn_and_tolerates_error(
        self, service, mock_repo
    ):
        cancelled_execs: list[str] = []
        run = _make_run(status=WorkflowRunStatusEnum.RUNNING)
        mock_repo.lock_run.return_value = run

        canceled = await service.cancel(
            "run-123",
            user_id=7,
            cancel_execution_fn=cancelled_execs.append,
        )
        assert canceled.status == WorkflowRunStatusEnum.CANCELED
        assert canceled.canceled_by_user is True
        assert cancelled_execs == ["exec-1"]
        assert canceled.execution_ids[-1].state == "CANCELLED"

        # If GCP cancel raises (e.g. execution already ended), cancel still succeeds.
        run_err = _make_run(status=WorkflowRunStatusEnum.RUNNING)
        mock_repo.lock_run.return_value = run_err

        def _failing_cancel(_exec_id: str) -> None:
            raise RuntimeError("Execution already finished in GCP")

        canceled_2 = await service.cancel(
            "run-123",
            user_id=7,
            cancel_execution_fn=_failing_cancel,
        )
        assert canceled_2.status == WorkflowRunStatusEnum.CANCELED

    @pytest.mark.anyio
    async def test_cancel_terminal_returns_409_and_non_owner_returns_404(
        self, service, mock_repo
    ):
        for term in (
            WorkflowRunStatusEnum.COMPLETED,
            WorkflowRunStatusEnum.CANCELED,
        ):
            mock_repo.lock_run.return_value = _make_run(status=term)
            with pytest.raises(StepError) as exc_409:
                await service.cancel("run-123", user_id=7)
            assert exc_409.value.status_code == 409

        mock_repo.lock_run.return_value = _make_run(user_id=999)
        with pytest.raises(StepError) as exc_404:
            await service.cancel("run-123", user_id=7)
        assert exc_404.value.status_code == 404


class TestReconcileRun:
    """Tests for RunStateService.reconcile_run (spec §8.6, §11.1 #4, E21)."""

    @pytest.mark.anyio
    async def test_reconcile_stale_empty_execution_ids_resets_to_queued(
        self, service, mock_repo
    ):
        # Claimed 3 minutes ago (> 2 min STALE_CLAIM_SECONDS) with empty execution_ids.
        run = _make_run(
            status=WorkflowRunStatusEnum.RUNNING,
            execution_ids=[],
            dispatched_at=BASE_TIME - datetime.timedelta(minutes=3),
            attempt_count=0,
        )
        mock_repo.lock_run.return_value = run

        reconciled = await service.reconcile_run(run)
        assert reconciled is not None
        assert reconciled.status == WorkflowRunStatusEnum.QUEUED
        assert reconciled.queue_reason == QueueReasonEnum.WAITING_FOR_SLOT
        assert reconciled.next_retry_at == BASE_TIME
        assert reconciled.attempt_count == 0

    @pytest.mark.anyio
    async def test_reconcile_fresh_empty_execution_ids_is_untouched(
        self, service, mock_repo
    ):
        run = _make_run(
            status=WorkflowRunStatusEnum.RUNNING,
            execution_ids=[],
            dispatched_at=BASE_TIME - datetime.timedelta(seconds=30),
        )
        reconciled = await service.reconcile_run(run)
        assert reconciled is run
        mock_repo.lock_run.assert_not_awaited()

    @pytest.mark.anyio
    async def test_reconcile_migrated_row_e21_with_null_dispatched_at_calls_gcp(
        self, service, mock_repo
    ):
        """E21: Migrated legacy row has status=RUNNING, execution_ids backfilled from id,
        and dispatched_at=None. Reconciler must query GCP get_execution instead of resetting!
        """
        migrated_run = _make_run(
            id="legacy-exec-id",
            status=WorkflowRunStatusEnum.RUNNING,
            dispatched_at=None,
            execution_ids=[
                WorkflowRunExecution(
                    execution_id="legacy-exec-id",
                    started_at=BASE_TIME - datetime.timedelta(hours=1),
                )
            ],
        )
        mock_repo.lock_run.return_value = migrated_run

        queried_ids: list[str] = []

        def _get_execution(exec_id: str) -> dict[str, Any]:
            queried_ids.append(exec_id)
            return {"state": "SUCCEEDED"}

        reconciled = await service.reconcile_run(
            migrated_run,
            get_execution_fn=_get_execution,
        )
        assert queried_ids == ["legacy-exec-id"]
        assert reconciled is not None
        assert reconciled.status == WorkflowRunStatusEnum.COMPLETED

    @pytest.mark.anyio
    async def test_reconcile_missed_failed_and_cancelled_callbacks(
        self, service, mock_repo
    ):
        # 1. Missed FAILED callback in GCP -> transitions via on_step_failed.
        run_failed = _make_run()
        mock_repo.lock_run.return_value = run_failed

        reconciled_fail = await service.reconcile_run(
            run_failed,
            get_execution_fn=lambda _eid: {
                "state": "FAILED",
                "error": {"code": 503, "message": "Service unavailable"},
            },
        )
        assert reconciled_fail is not None
        assert reconciled_fail.status == WorkflowRunStatusEnum.QUEUED
        assert reconciled_fail.queue_reason == QueueReasonEnum.RETRY_SCHEDULED

        # 2. Missed CANCELLED callback in GCP -> transitions to CANCELED.
        run_cancelled = _make_run()
        mock_repo.lock_run.return_value = run_cancelled

        reconciled_cancel = await service.reconcile_run(
            run_cancelled,
            get_execution_fn=lambda _eid: {"state": "CANCELLED"},
        )
        assert reconciled_cancel is not None
        assert reconciled_cancel.status == WorkflowRunStatusEnum.CANCELED
