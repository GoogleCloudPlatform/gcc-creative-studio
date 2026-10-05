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
"""Tests for the step checkpoint / idempotency guard."""

import copy
import datetime
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from httpx import Response

from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.repository.workflow_run_repository import RunStepContext
from src.workflows.schema.workflow_model import StepStatusEnum
from src.workflows.schema.workflow_run_model import StepState
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateTextRequest,
    ImageStepRequest,
)
from src.workflows_executor.idempotency import (
    CLAIM_TTL,
    StepIdempotencyGuard,
)
from src.workflows_executor.step_errors import (
    StepError,
    invalid_input_error,
    job_failed_error,
    step_in_progress_error,
)
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)

pytestmark = pytest.mark.anyio

RUN_ID = "run-1"
STEP_ID = "image_1"
EXECUTION_ID = "exec-1"
USER_ID = 7
AUTH = "Bearer header.payload.signature"
MAX_STEP_SECONDS = 1800
T0 = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)


def _iso(moment: datetime.datetime) -> str:
    return moment.isoformat()


class FakeClock:
    """Manually advanced clock injected into the guard."""

    def __init__(self, now: datetime.datetime = T0):
        self.now = now

    def __call__(self) -> datetime.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += datetime.timedelta(seconds=seconds)


class FakeRunRepository:
    """In-memory ``WorkflowRunRepository`` with transactional writes.

    ``set_step_state`` stages the write; ``db.commit`` applies it and
    ``db.rollback`` discards it, like the real row-locked transaction.
    """

    def __init__(
        self,
        *,
        user_id: int = USER_ID,
        attempt_count: int = 1,
        step_states: dict | None = None,
        exists: bool = True,
    ):
        self.user_id = user_id
        self.attempt_count = attempt_count
        self.step_states = copy.deepcopy(step_states or {})
        self.exists = exists
        self.locks = 0
        self.writes: list[tuple[str, dict]] = []
        self._staged: dict[str, dict] = {}
        self.db = MagicMock()
        self.db.commit = AsyncMock(side_effect=self._commit)
        self.db.rollback = AsyncMock(side_effect=self._rollback)

    def _commit(self) -> None:
        self.step_states.update(self._staged)
        self._staged = {}

    def _rollback(self) -> None:
        self._staged = {}

    async def lock_step_context(self, run_id: str) -> RunStepContext | None:
        assert run_id == RUN_ID
        self.locks += 1
        if not self.exists:
            return None
        return RunStepContext(
            user_id=self.user_id,
            attempt_count=self.attempt_count,
            step_states=copy.deepcopy(self.step_states),
        )

    async def set_step_state(
        self, run_id: str, step_id: str, state: dict
    ) -> None:
        assert run_id == RUN_ID
        self.writes.append((step_id, copy.deepcopy(state)))
        self._staged[step_id] = copy.deepcopy(state)

    def state(self, step_id: str = STEP_ID) -> StepState:
        return StepState.model_validate(self.step_states[step_id])


def make_guard(
    repo: FakeRunRepository,
    clock: FakeClock | None = None,
    *,
    user_id: int = USER_ID,
) -> StepIdempotencyGuard:
    return StepIdempotencyGuard(
        repo,
        run_id=RUN_ID,
        step_id=STEP_ID,
        user_id=user_id,
        execution_id=EXECUTION_ID,
        max_step_duration_seconds=MAX_STEP_SECONDS,
        clock=clock or FakeClock(),
    )


def running_job_state(**overrides) -> dict:
    state = {
        "status": "running",
        "job_id": 42,
        "run_attempt": 1,
        "claim_id": "previous-call",
        "started_at": _iso(T0 - datetime.timedelta(seconds=300)),
        "first_started_at": _iso(T0 - datetime.timedelta(seconds=300)),
    }
    state.update(overrides)
    return state


def failed_job_state(error: dict | None, **overrides) -> dict:
    state = running_job_state(status="failed", **overrides)
    if error is not None:
        state["error"] = error
    return state


def image_request(**context) -> ImageStepRequest:
    return ImageStepRequest(
        workspace_id=1,
        inputs={"prompt": "A cat"},
        config={"mode": "generate_image"},
        **context,
    )


def text_request(**context) -> GenerateTextRequest:
    return GenerateTextRequest(
        inputs={"prompt": "Write a haiku"},
        config={"model": "gemini-3-flash-preview", "temperature": 0.2},
        **context,
    )


# --- from_request ---------------------------------------------------------


@pytest.mark.parametrize("run_id", [None, ""])
def test_from_request_without_run_id_has_no_guard(run_id):
    repo = FakeRunRepository()
    request = image_request(run_id=run_id, step_id=STEP_ID)
    assert StepIdempotencyGuard.from_request(request, USER_ID, repo) is None
    assert repo.locks == 0


async def test_from_request_builds_a_guard_for_the_step():
    repo = FakeRunRepository()
    request = image_request(
        run_id=RUN_ID, step_id=STEP_ID, execution_id=EXECUTION_ID
    )
    guard = StepIdempotencyGuard.from_request(request, USER_ID, repo)
    assert guard is not None
    assert (guard.run_id, guard.step_id) == (RUN_ID, STEP_ID)

    assert await guard.begin() is None
    assert repo.state().execution_id == EXECUTION_ID


def test_from_request_requires_a_step_id_with_run_id():
    # model_construct skips the DTO validator that already rejects this.
    request = ImageStepRequest.model_construct(run_id=RUN_ID, step_id=None)
    with pytest.raises(StepError) as exc:
        StepIdempotencyGuard.from_request(request, USER_ID, FakeRunRepository())
    assert exc.value.status_code == 400
    assert exc.value.error_category is ErrorCategory.INVALID_INPUT


# --- begin ----------------------------------------------------------------


async def test_begin_claims_a_new_step():
    repo = FakeRunRepository()
    guard = make_guard(repo)

    assert await guard.begin() is None

    state = repo.state()
    assert state.status == StepStatusEnum.RUNNING
    assert state.started_at == T0
    assert state.execution_id == EXECUTION_ID
    assert state.claim_id
    assert state.job_id is None
    assert state.attempts == 0
    repo.db.commit.assert_awaited_once()


async def test_completed_step_returns_stored_outputs_without_writing():
    repo = FakeRunRepository(
        step_states={
            STEP_ID: {"status": "completed", "outputs": {"generated_image": 5}}
        }
    )
    guard = make_guard(repo)

    assert await guard.begin() == {"generated_image": 5}
    assert not repo.writes
    # The transaction still ends, releasing the row lock.
    repo.db.commit.assert_awaited_once()


async def test_missing_run_is_404_and_rolls_back():
    repo = FakeRunRepository(exists=False)
    with pytest.raises(StepError) as exc:
        await make_guard(repo).begin()
    assert exc.value.status_code == 404
    assert exc.value.error_category is ErrorCategory.MISSING_RESOURCE
    repo.db.rollback.assert_awaited_once()


async def test_run_of_another_user_is_403():
    repo = FakeRunRepository(
        user_id=99,
        step_states={
            STEP_ID: {"status": "completed", "outputs": {"generated_image": 5}}
        },
    )
    with pytest.raises(StepError) as exc:
        await make_guard(repo).begin()
    assert exc.value.status_code == 403
    assert exc.value.error_category is ErrorCategory.FORBIDDEN
    assert not repo.writes
    repo.db.rollback.assert_awaited_once()


async def test_unreadable_step_state_is_replaced(caplog):
    repo = FakeRunRepository(step_states={STEP_ID: {"status": "bogus"}})
    with caplog.at_level(logging.WARNING):
        assert await make_guard(repo).begin() is None
    assert "Ignoring unreadable state" in caplog.text
    assert repo.state().status == StepStatusEnum.RUNNING


async def test_concurrent_job_creation_answers_step_in_progress():
    repo = FakeRunRepository(
        step_states={
            STEP_ID: {
                "status": "running",
                "claim_id": "other-call",
                "started_at": _iso(T0 - datetime.timedelta(seconds=10)),
            }
        }
    )
    with pytest.raises(StepError) as exc:
        await make_guard(repo).begin()

    assert exc.value.status_code == 504
    assert exc.value.error_category is ErrorCategory.STEP_IN_PROGRESS
    state = repo.state()
    assert state.in_progress_continuations == 1
    assert state.claim_id == "other-call"
    assert state.attempts == 0


async def test_abandoned_claim_is_taken_over():
    stale = T0 - CLAIM_TTL - datetime.timedelta(seconds=1)
    repo = FakeRunRepository(
        step_states={
            STEP_ID: {
                "status": "running",
                "claim_id": "crashed-call",
                "started_at": _iso(stale),
            }
        }
    )
    assert await make_guard(repo).begin() is None
    state = repo.state()
    assert state.claim_id not in (None, "crashed-call")
    assert state.started_at == T0


async def test_failed_job_is_not_regenerated_in_the_same_attempt():
    repo = FakeRunRepository(
        attempt_count=1,
        step_states={
            STEP_ID: failed_job_state(
                {
                    "category": "SAFETY_BLOCK",
                    "http_status": 422,
                    "detail": "blocked by safety filters",
                }
            )
        },
    )
    with pytest.raises(StepError) as exc:
        await make_guard(repo).begin()

    assert exc.value.status_code == 422
    assert exc.value.error_category is ErrorCategory.SAFETY_BLOCK
    assert exc.value.detail == "blocked by safety filters"
    assert exc.value.job_terminal is True
    assert not repo.writes


async def test_failed_job_without_error_info_uses_generic_error():
    repo = FakeRunRepository(step_states={STEP_ID: failed_job_state(None)})
    with pytest.raises(StepError) as exc:
        await make_guard(repo).begin()
    assert exc.value.status_code == 500
    assert exc.value.error_category is ErrorCategory.UNKNOWN
    assert exc.value.detail == "The generation job of this step failed."


async def test_text_step_only_reuses_completed_outputs():
    # Q12: without a job id a failed text step simply runs again.
    repo = FakeRunRepository(
        step_states={STEP_ID: failed_job_state({"category": "INTERNAL"})}
    )
    guard = make_guard(repo)

    assert await guard.begin(job_step=False) is None
    assert repo.state().status == StepStatusEnum.RUNNING

    await guard.complete({"generated_text": "hi"})
    assert await make_guard(repo).begin(job_step=False) == {
        "generated_text": "hi"
    }


# --- run_job --------------------------------------------------------------


async def test_new_job_is_recorded_before_polling():
    repo = FakeRunRepository()
    guard = make_guard(repo)
    await guard.begin()
    recorded = {}

    async def poll_job(job_id, single_check):
        recorded["state"] = repo.state()
        recorded["args"] = (job_id, single_check)

    job_id = await guard.run_job(AsyncMock(return_value=42), poll_job)

    assert job_id == 42
    assert recorded["args"] == (42, False)
    assert recorded["state"].job_id == 42
    assert recorded["state"].first_started_at == T0
    assert recorded["state"].run_attempt == 1

    await guard.complete({"generated_image": 42})
    state = repo.state()
    assert state.status == StepStatusEnum.COMPLETED
    assert state.outputs == {"generated_image": 42}
    assert state.completed_at == T0
    assert state.claim_id is None
    assert state.job_id == 42


async def test_in_flight_job_is_reused_without_a_new_generation():
    repo = FakeRunRepository(step_states={STEP_ID: running_job_state()})
    guard = make_guard(repo)
    create_job = AsyncMock(return_value=43)
    poll_job = AsyncMock()

    assert await guard.begin() is None
    assert await guard.run_job(create_job, poll_job) == 42

    create_job.assert_not_awaited()
    poll_job.assert_awaited_once_with(42, False)


async def test_continuation_does_not_consume_an_attempt_and_resumes():
    repo = FakeRunRepository()
    first = make_guard(repo)
    await first.begin()
    poll_job = AsyncMock(side_effect=step_in_progress_error("still running"))

    with pytest.raises(StepError) as exc:
        await first.run_job(AsyncMock(return_value=42), poll_job)
    assert exc.value.error_category is ErrorCategory.STEP_IN_PROGRESS
    await first.record_failure(exc.value)

    state = repo.state()
    assert state.status == StepStatusEnum.RUNNING
    assert state.in_progress_continuations == 1
    assert state.attempts == 0
    assert state.error is None
    assert state.job_id == 42

    second = make_guard(repo)
    create_job = AsyncMock(return_value=43)
    assert await second.begin() is None
    assert await second.run_job(create_job, AsyncMock()) == 42
    create_job.assert_not_awaited()
    await second.complete({"generated_image": 42})
    assert repo.state().status == StepStatusEnum.COMPLETED


async def test_reused_job_past_the_duration_cap_is_checked_once():
    started = T0 - datetime.timedelta(seconds=MAX_STEP_SECONDS + 1)
    repo = FakeRunRepository(
        step_states={STEP_ID: running_job_state(first_started_at=_iso(started))}
    )
    guard = make_guard(repo)
    poll_job = AsyncMock()

    await guard.begin()
    assert await guard.run_job(AsyncMock(), poll_job) == 42
    poll_job.assert_awaited_once_with(42, True)


async def test_job_running_past_the_duration_cap_fails_with_cap_exceeded():
    started = T0 - datetime.timedelta(seconds=MAX_STEP_SECONDS + 1)
    repo = FakeRunRepository(
        step_states={STEP_ID: running_job_state(first_started_at=_iso(started))}
    )
    guard = make_guard(repo)
    await guard.begin()

    with pytest.raises(StepError) as exc:
        await guard.run_job(
            AsyncMock(),
            AsyncMock(side_effect=step_in_progress_error("still running")),
        )

    assert exc.value.status_code == 409
    assert exc.value.error_category is ErrorCategory.CAP_EXCEEDED
    assert exc.value.job_terminal is True
    assert "WORKFLOW_MAX_STEP_DURATION_SECONDS" in exc.value.detail

    await guard.record_failure(exc.value)
    state = repo.state()
    assert state.status == StepStatusEnum.FAILED
    assert state.error.category == ErrorCategory.CAP_EXCEEDED.value
    assert state.error.http_status == 409


async def test_new_job_exceeding_the_cap_while_polling():
    clock = FakeClock()
    repo = FakeRunRepository()
    guard = make_guard(repo, clock)
    await guard.begin()

    async def slow_poll(unused_job_id, unused_single_check):
        clock.advance(MAX_STEP_SECONDS + 1)
        raise step_in_progress_error("still running")

    with pytest.raises(StepError) as exc:
        await guard.run_job(AsyncMock(return_value=42), slow_poll)
    assert exc.value.error_category is ErrorCategory.CAP_EXCEEDED


async def test_other_poll_errors_are_reraised():
    repo = FakeRunRepository()
    guard = make_guard(repo)
    await guard.begin()
    error = job_failed_error("Image blocked by Responsible AI filters")

    with pytest.raises(StepError) as exc:
        await guard.run_job(
            AsyncMock(return_value=42), AsyncMock(side_effect=error)
        )
    assert exc.value is error


async def test_default_duration_cap_comes_from_the_config():
    started = T0 - datetime.timedelta(seconds=11)
    repo = FakeRunRepository(
        step_states={STEP_ID: running_job_state(first_started_at=_iso(started))}
    )
    config = MagicMock(WORKFLOW_MAX_STEP_DURATION_SECONDS=10)
    with patch("src.workflows_executor.idempotency.config_service", config):
        guard = StepIdempotencyGuard(
            repo,
            run_id=RUN_ID,
            step_id=STEP_ID,
            user_id=USER_ID,
            clock=FakeClock(),
        )
    poll_job = AsyncMock()

    await guard.begin()
    await guard.run_job(AsyncMock(), poll_job)
    poll_job.assert_awaited_once_with(42, True)


async def test_cap_exceeded_job_is_rechecked_in_a_new_attempt():
    repo = FakeRunRepository(
        attempt_count=2,
        step_states={
            STEP_ID: failed_job_state(
                {"category": "CAP_EXCEEDED", "http_status": 409}
            )
        },
    )
    guard = make_guard(repo)
    create_job = AsyncMock(return_value=43)
    poll_job = AsyncMock()

    assert await guard.begin() is None
    state = repo.state()
    assert state.first_started_at == T0
    assert state.run_attempt == 2

    assert await guard.run_job(create_job, poll_job) == 42
    create_job.assert_not_awaited()
    poll_job.assert_awaited_once_with(42, True)


@pytest.mark.parametrize(
    "initial_state",
    [
        failed_job_state({"category": "CAP_EXCEEDED", "http_status": 409}),
        {
            "status": "pending",
            "job_id": 42,
            "attempts": 0,
            "in_progress_continuations": 0,
        },
    ],
)
async def test_cap_exceeded_job_still_running_regenerates_a_new_job(
    initial_state,
):
    repo = FakeRunRepository(
        attempt_count=2,
        step_states={STEP_ID: initial_state},
    )
    guard = make_guard(repo)
    create_job = AsyncMock(return_value=43)
    poll_job = AsyncMock(
        side_effect=[step_in_progress_error("still running"), None]
    )

    assert await guard.begin() is None
    assert await guard.run_job(create_job, poll_job) == 43

    create_job.assert_awaited_once()
    assert poll_job.await_args_list == [call(42, True), call(43, False)]
    state = repo.state()
    assert state.job_id == 43
    assert state.run_attempt == 2


async def test_cap_exceeded_job_failed_in_meantime_regenerates_a_new_job():
    repo = FakeRunRepository(
        attempt_count=2,
        step_states={
            STEP_ID: {
                "status": "pending",
                "job_id": 42,
                "attempts": 0,
                "in_progress_continuations": 0,
            }
        },
    )
    guard = make_guard(repo)
    create_job = AsyncMock(return_value=43)
    poll_job = AsyncMock(
        side_effect=[job_failed_error("upstream failure"), None]
    )

    assert await guard.begin() is None
    assert await guard.run_job(create_job, poll_job) == 43

    create_job.assert_awaited_once()
    assert poll_job.await_args_list == [call(42, True), call(43, False)]
    assert repo.state().job_id == 43


async def test_cap_exceeded_abandoned_job_clears_job_id_if_create_job_fails():
    repo = FakeRunRepository(
        attempt_count=2,
        step_states={
            STEP_ID: {
                "status": "pending",
                "job_id": 42,
                "attempts": 0,
                "in_progress_continuations": 0,
            }
        },
    )
    guard = make_guard(repo)
    create_error = StepError(503, ErrorCategory.TRANSIENT, "create failed")
    create_job = AsyncMock(side_effect=create_error)
    poll_job = AsyncMock(side_effect=step_in_progress_error("still running"))

    assert await guard.begin() is None
    with pytest.raises(StepError) as exc:
        await guard.run_job(create_job, poll_job)
    assert exc.value is create_error

    await guard.record_failure(exc.value)
    state = repo.state()
    assert state.job_id is None
    assert state.first_started_at is None
    assert state.run_attempt is None
    assert state.status == StepStatusEnum.FAILED
    assert state.error.category == ErrorCategory.TRANSIENT.value


async def test_cap_exceeded_recheck_transient_error_keeps_prior_job():
    repo = FakeRunRepository(
        attempt_count=2,
        step_states={
            STEP_ID: {
                "status": "pending",
                "job_id": 42,
                "attempts": 0,
                "in_progress_continuations": 0,
            }
        },
    )
    guard = make_guard(repo)
    poll_error = StepError(503, ErrorCategory.TRANSIENT, "poll failed")
    create_job = AsyncMock(return_value=43)
    poll_job = AsyncMock(side_effect=poll_error)

    assert await guard.begin() is None
    with pytest.raises(StepError) as exc:
        await guard.run_job(create_job, poll_job)
    assert exc.value is poll_error

    create_job.assert_not_awaited()
    await guard.record_failure(exc.value)
    state = repo.state()
    assert state.job_id == 42
    assert state.status == StepStatusEnum.PENDING

    retry_guard = make_guard(repo)
    retry_poll = AsyncMock(
        side_effect=[step_in_progress_error("still running"), None]
    )
    assert await retry_guard.begin() is None
    assert await retry_guard.run_job(create_job, retry_poll) == 43
    create_job.assert_awaited_once()
    assert retry_poll.await_args_list == [call(42, True), call(43, False)]


async def test_failed_job_is_regenerated_in_a_new_attempt():
    repo = FakeRunRepository(
        attempt_count=2,
        step_states={
            STEP_ID: failed_job_state(
                {"category": "TRANSIENT", "http_status": 503}
            )
        },
    )
    guard = make_guard(repo)

    assert await guard.begin() is None
    state = repo.state()
    assert state.job_id is None
    assert state.error is None

    assert await guard.run_job(AsyncMock(return_value=43), AsyncMock()) == 43
    state = repo.state()
    assert state.job_id == 43
    assert state.run_attempt == 2


# --- record_failure -------------------------------------------------------


async def test_failure_with_a_live_job_keeps_the_step_running():
    repo = FakeRunRepository(step_states={STEP_ID: running_job_state()})
    guard = make_guard(repo)
    await guard.begin()

    await guard.record_failure(
        StepError(503, ErrorCategory.TRANSIENT, "poll failed")
    )

    state = repo.state()
    assert state.status == StepStatusEnum.RUNNING
    assert state.job_id == 42
    assert state.error.category == ErrorCategory.TRANSIENT.value
    assert state.error.http_status == 503
    assert state.error.detail == "poll failed"


async def test_failure_of_the_job_marks_the_step_failed():
    repo = FakeRunRepository(step_states={STEP_ID: running_job_state()})
    guard = make_guard(repo)
    await guard.begin()

    await guard.record_failure(job_failed_error("blocked by safety filters"))

    state = repo.state()
    assert state.status == StepStatusEnum.FAILED
    assert state.error.category == ErrorCategory.SAFETY_BLOCK.value
    assert state.error.http_status == 422


async def test_failure_before_any_job_marks_the_step_failed():
    repo = FakeRunRepository()
    guard = make_guard(repo)
    await guard.begin()

    await guard.record_failure(invalid_input_error("Prompt is required"))

    state = repo.state()
    assert state.status == StepStatusEnum.FAILED
    assert state.error.category == ErrorCategory.INVALID_INPUT.value


async def test_record_failure_never_raises(caplog):
    repo = FakeRunRepository()
    repo.lock_step_context = AsyncMock(side_effect=RuntimeError("db down"))

    with caplog.at_level(logging.ERROR):
        await make_guard(repo).record_failure(
            invalid_input_error("Prompt is required")
        )

    assert "Could not record the failure" in caplog.text
    repo.db.rollback.assert_awaited_once()


# --- transactions ---------------------------------------------------------


async def test_failed_commit_rolls_back_the_write():
    repo = FakeRunRepository()
    repo.db.commit.side_effect = RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        await make_guard(repo).begin()

    repo.db.rollback.assert_awaited_once()
    assert STEP_ID not in repo.step_states


async def test_failed_rollback_is_logged_and_the_error_kept(caplog):
    repo = FakeRunRepository()
    repo.db.commit.side_effect = RuntimeError("commit failed")
    repo.db.rollback.side_effect = RuntimeError("rollback failed")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="commit failed"):
            await make_guard(repo).begin()

    assert "Rollback failed" in caplog.text


# --- Executor service with a guard ----------------------------------------


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch(
            "src.workflows_executor.workflows_executor_service.RestClient"
        ) as rest_client_class,
        patch(
            "src.workflows_executor.workflows_executor_service"
            ".GenAIModelSetup.init"
        ) as genai_init,
    ):
        rest_client_class.return_value = AsyncMock()
        genai_init.return_value = MagicMock()
        yield WorkflowsExecutorService()


def _context() -> dict:
    return {
        "run_id": RUN_ID,
        "step_id": STEP_ID,
        "execution_id": EXECUTION_ID,
    }


async def test_service_completed_step_skips_the_generation(service):
    repo = FakeRunRepository(
        step_states={
            STEP_ID: {"status": "completed", "outputs": {"generated_image": 5}}
        }
    )
    request = image_request(**_context())
    guard = StepIdempotencyGuard.from_request(request, USER_ID, repo)

    with patch.object(service, "_poll_job_status", AsyncMock()) as poll:
        result = await service.execute_image(request, AUTH, guard=guard)

    assert result == {"generated_image": 5}
    service.rest_client.post.assert_not_awaited()
    poll.assert_not_awaited()


async def test_service_continuation_reuses_the_job_until_it_completes(
    service,
):
    repo = FakeRunRepository()
    request = image_request(**_context())
    service.rest_client.post.return_value = Response(200, json={"id": 42})
    poll = AsyncMock(side_effect=[step_in_progress_error("running"), True])

    with patch.object(service, "_poll_job_status", poll):
        # 1st call: the poll budget runs out while the job is running.
        with pytest.raises(StepError) as exc:
            await service.execute_image(
                request,
                AUTH,
                guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
            )
        assert exc.value.status_code == 504
        assert exc.value.error_category is ErrorCategory.STEP_IN_PROGRESS
        state = repo.state()
        assert state.in_progress_continuations == 1
        assert state.attempts == 0
        assert state.job_id == 42

        # 2nd call (L2 retry): same job, no second POST, completes.
        result = await service.execute_image(
            request,
            AUTH,
            guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
        )
        assert result == {"generated_image": 42}

        # 3rd call: stored outputs, nothing polled or generated.
        result = await service.execute_image(
            request,
            AUTH,
            guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
        )
        assert result == {"generated_image": 42}

    service.rest_client.post.assert_awaited_once()
    assert poll.await_args_list == [call(42, AUTH), call(42, AUTH)]
    state = repo.state()
    assert state.status == StepStatusEnum.COMPLETED
    assert state.outputs == {"generated_image": 42}


async def test_service_without_run_id_skips_the_checkpoint(service):
    repo = FakeRunRepository()
    request = image_request()
    service.rest_client.post.return_value = Response(200, json={"id": 11})
    guard = StepIdempotencyGuard.from_request(request, USER_ID, repo)

    with patch.object(service, "_poll_job_status", AsyncMock()):
        result = await service.execute_image(request, AUTH, guard=guard)

    assert guard is None
    assert result == {"generated_image": 11}
    assert repo.locks == 0
    assert not repo.writes


async def test_service_records_structured_failures(service):
    repo = FakeRunRepository()
    request = image_request(**_context())
    service.rest_client.post.return_value = Response(
        400, text="Request blocked by safety filters"
    )

    with pytest.raises(StepError) as exc:
        await service.execute_image(
            request,
            AUTH,
            guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
        )

    assert exc.value.status_code == 422
    assert exc.value.error_category is ErrorCategory.SAFETY_BLOCK
    state = repo.state()
    assert state.status == StepStatusEnum.FAILED
    assert state.error.category == ErrorCategory.SAFETY_BLOCK.value


async def test_service_converts_unexpected_errors_and_keeps_the_job(service):
    repo = FakeRunRepository()
    request = image_request(**_context())
    service.rest_client.post.return_value = Response(200, json={"id": 42})
    poll = AsyncMock(side_effect=ValueError("boom"))

    with patch.object(service, "_poll_job_status", poll):
        with pytest.raises(StepError) as exc:
            await service.execute_image(
                request,
                AUTH,
                guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
            )

    assert exc.value.status_code == 500
    assert exc.value.error_category is ErrorCategory.INTERNAL
    assert isinstance(exc.value.__cause__, ValueError)
    state = repo.state()
    # The job may still finish: the next call keeps polling it.
    assert state.status == StepStatusEnum.RUNNING
    assert state.job_id == 42
    assert state.error.category == ErrorCategory.INTERNAL.value


async def test_service_rejects_runs_of_other_users(service):
    repo = FakeRunRepository(user_id=99)
    request = image_request(**_context())

    with pytest.raises(StepError) as exc:
        await service.execute_image(
            request,
            AUTH,
            guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
        )

    assert exc.value.status_code == 403
    service.rest_client.post.assert_not_awaited()


async def test_service_text_step_checkpoints_its_outputs(service):
    repo = FakeRunRepository()
    request = text_request(**_context())
    chunk = MagicMock(text="An old pond", prompt_feedback=None, candidates=[])
    stream = service.genai_client.models.generate_content_stream
    stream.return_value = [chunk]

    first = await service.generate_text(
        request,
        AUTH,
        guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
    )
    second = await service.generate_text(
        request,
        AUTH,
        guard=StepIdempotencyGuard.from_request(request, USER_ID, repo),
    )

    assert first == second == {"generated_text": "An old pond"}
    stream.assert_called_once()
    assert repo.state().status == StepStatusEnum.COMPLETED
