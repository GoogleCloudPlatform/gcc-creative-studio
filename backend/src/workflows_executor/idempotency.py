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

"""Step checkpoint and idempotency guard for executor calls.

Every step call that carries ``run_id`` / ``step_id`` goes through a
:class:`StepIdempotencyGuard`, keyed by ``(run_id, step_id)``:

1. A completed step returns its stored outputs (no new generation).
2. A step whose gen job (``job_id``) is in flight or finished keeps polling
   that job instead of creating a new one. When the per-request poll budget
   runs out, the call answers 504 ``STEP_IN_PROGRESS`` and the retried call
   resumes polling. Past ``WORKFLOW_MAX_STEP_DURATION_SECONDS`` (counted
   from ``first_started_at``) the step fails with ``CAP_EXCEEDED``.
3. A failed job is not regenerated until the dispatcher starts a new run
   attempt (``workflow_runs.attempt_count`` advanced).
4. Otherwise a new job is created and its id is recorded before polling.

Each read-modify-write of ``step_states`` runs in its own short transaction
under ``SELECT ... FOR UPDATE`` on the run row; the lock is never held while
a job is created or polled. Step ``attempts`` are not incremented here:
failures are counted when the run state service classifies them (Phase 2).
"""

import datetime
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from src.common.secret_redaction import install_secret_redaction
from src.config.config_service import config_service
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows.schema.workflow_model import StepStatusEnum
from src.workflows.schema.workflow_run_model import StepErrorInfo, StepState
from src.workflows_executor.dto.workflows_executor_dto import StepCallContext
from src.workflows_executor.step_errors import (
    StepError,
    invalid_input_error,
    status_for_category,
    step_in_progress_error,
)

logger = install_secret_redaction(logging.getLogger(__name__))

# A running claim without a job id older than this is abandoned: the
# executor's HTTP client timeout (280 s) plus a margin.
CLAIM_TTL = datetime.timedelta(seconds=300)

StepMutation = Callable[[StepState, int], Any]
CreateJob = Callable[[], Awaitable[int]]
# poll_job(job_id, single_check): single_check polls once, without waiting.
PollJob = Callable[[int, bool], Awaitable[Any]]


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _parse_category(value: Any) -> ErrorCategory:
    try:
        return ErrorCategory(value)
    except ValueError:
        return ErrorCategory.UNKNOWN


class StepIdempotencyGuard:
    """Checkpoint and idempotency of one step call of one workflow run."""

    def __init__(
        self,
        repository: WorkflowRunRepository,
        *,
        run_id: str,
        step_id: str,
        user_id: int,
        execution_id: str | None = None,
        max_step_duration_seconds: int | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        if max_step_duration_seconds is None:
            max_step_duration_seconds = (
                config_service.WORKFLOW_MAX_STEP_DURATION_SECONDS
            )
        self.run_id = run_id
        self.step_id = step_id
        self._repository = repository
        self._user_id = user_id
        self._execution_id = execution_id
        self._max_step_duration = datetime.timedelta(
            seconds=max_step_duration_seconds
        )
        self._clock = clock or _utcnow
        # Identifies this call while it creates the job (concurrent calls).
        self._claim_id = uuid.uuid4().hex
        self._reuse_job_id: int | None = None
        self._job_id: int | None = None
        self._first_started_at: datetime.datetime | None = None
        self._recheck_before_regenerate: bool = False
        self._abandoned_prior_job: bool = False

    @classmethod
    def from_request(
        cls,
        request: StepCallContext,
        user_id: int,
        repository: WorkflowRunRepository,
    ) -> "StepIdempotencyGuard | None":
        """Guard for a step request; ``None`` when it has no ``run_id``.

        Calls without ``run_id`` (executions started before this feature
        or outside the queue) run without checkpoint and idempotency.
        """
        if not request.run_id:
            return None
        if not request.step_id:
            raise invalid_input_error("step_id is required with run_id.")
        return cls(
            repository,
            run_id=request.run_id,
            step_id=request.step_id,
            user_id=user_id,
            execution_id=request.execution_id or None,
        )

    # --- Public API -------------------------------------------------------

    async def begin(self, *, job_step: bool = True) -> dict[str, Any] | None:
        """Claims the step; returns stored outputs if it already completed.

        Args:
            job_step: Whether the step creates a gen job. Steps without a
                job (text generation) only reuse completed outputs (Q12).

        Raises:
            StepError: 404 / 403 for a missing or foreign run, the recorded
                error of a failed job in the same run attempt, or 504
                ``STEP_IN_PROGRESS`` while another call creates the job.
        """

        def mutate(state: StepState, run_attempt: int) -> Any:
            now = self._clock()
            if (
                state.status == StepStatusEnum.COMPLETED
                and state.outputs is not None
            ):
                return dict(state.outputs)
            if job_step:
                blocked = self._blocking_error(state, run_attempt, now)
                if blocked is not None:
                    return blocked
                self._plan_job(state, run_attempt, now)
            state.status = StepStatusEnum.RUNNING
            state.started_at = now
            state.execution_id = self._execution_id or state.execution_id
            state.claim_id = self._claim_id
            state.error = None
            return None

        return await self._transact(mutate)

    async def run_job(self, create_job: CreateJob, poll_job: PollJob) -> int:
        """Reuses the step's job or creates one, then polls it.

        A new job id is recorded before polling starts. A reused job past
        the step duration cap is checked once; if it is still running the
        step fails with 409 ``CAP_EXCEEDED``. A resumed ``CAP_EXCEEDED``
        job is checked once and regenerated if it did not complete.

        Returns:
            The gen job (gallery item) id.
        """
        job_id = self._reuse_job_id
        if job_id is not None and self._recheck_before_regenerate:
            try:
                await poll_job(job_id, True)
            except StepError as error:
                if error.job_terminal or error.error_category in (
                    ErrorCategory.STEP_IN_PROGRESS,
                    ErrorCategory.MISSING_RESOURCE,
                ):
                    logger.info(
                        "Prior job %s for step %s of run %s did not complete "
                        "(%s); regenerating.",
                        job_id,
                        self.step_id,
                        self.run_id,
                        error.error_category.value,
                    )
                    self._abandoned_prior_job = True
                    job_id = None
                else:
                    raise
            else:
                self._job_id = job_id
                return job_id

        if job_id is None:
            job_id = await create_job()
            await self._record_job(job_id)
            single_check = False
        else:
            single_check = self._over_duration_cap()
        self._job_id = job_id
        try:
            await poll_job(job_id, single_check)
        except StepError as error:
            if (
                error.error_category is ErrorCategory.STEP_IN_PROGRESS
                and self._over_duration_cap()
            ):
                raise self._cap_exceeded_error(job_id) from error
            raise
        return job_id

    async def complete(self, outputs: dict[str, Any]) -> None:
        """Checkpoints the step as completed with its (JSON-safe) outputs."""
        now = self._clock()

        def mutate(state: StepState, unused_run_attempt: int) -> None:
            state.status = StepStatusEnum.COMPLETED
            state.outputs = outputs
            state.completed_at = now
            state.error = None
            state.claim_id = None
            if self._job_id is not None:
                state.job_id = self._job_id

        await self._transact(mutate)

    async def record_failure(self, error: StepError) -> None:
        """Records a failed call in ``step_states``; never raises.

        ``STEP_IN_PROGRESS`` counts a continuation. Errors that leave a gen
        job alive keep the step ``running`` so the next call reuses the
        job; every other error marks the step ``failed``.
        """
        info = StepErrorInfo(
            category=error.error_category,
            http_status=error.status_code,
            detail=error.detail,
        )

        def mutate(state: StepState, unused_run_attempt: int) -> None:
            if self._abandoned_prior_job:
                state.job_id = None
                state.first_started_at = None
                state.run_attempt = None
                state.status = StepStatusEnum.FAILED
                state.error = info
                return
            if error.error_category is ErrorCategory.STEP_IN_PROGRESS:
                state.in_progress_continuations += 1
                state.status = StepStatusEnum.RUNNING
                return
            if state.job_id is not None and not error.job_terminal:
                state.status = (
                    StepStatusEnum.PENDING
                    if self._recheck_before_regenerate
                    else StepStatusEnum.RUNNING
                )
            else:
                state.status = StepStatusEnum.FAILED
            state.error = info

        try:
            await self._transact(mutate)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Could not record the failure of step %s of run %s.",
                self.step_id,
                self.run_id,
            )

    # --- Internals --------------------------------------------------------

    def _blocking_error(
        self, state: StepState, run_attempt: int, now: datetime.datetime
    ) -> StepError | None:
        """Error that ends the call before any job is created or polled."""
        if (
            state.status == StepStatusEnum.FAILED
            and state.job_id is not None
            and state.run_attempt == run_attempt
        ):
            # Rule 3: a failed job is only regenerated in a new attempt.
            return self._recorded_error(state)
        if (
            state.status == StepStatusEnum.RUNNING
            and state.job_id is None
            and state.claim_id not in (None, self._claim_id)
            and state.started_at is not None
            and now - state.started_at < CLAIM_TTL
        ):
            # Another call is creating the job right now.
            state.in_progress_continuations += 1
            return step_in_progress_error(
                "Another call is starting the generation job of this step."
            )
        return None

    def _plan_job(
        self, state: StepState, run_attempt: int, now: datetime.datetime
    ) -> None:
        """Decides whether this call reuses the recorded job."""
        error_category = state.error.category if state.error else None
        if state.job_id is not None and state.status == StepStatusEnum.RUNNING:
            # In flight: keep polling it (no new generation).
            self._reuse_job_id = state.job_id
            self._recheck_before_regenerate = False
            self._first_started_at = state.first_started_at or now
            state.first_started_at = self._first_started_at
        elif state.job_id is not None and (
            state.status == StepStatusEnum.PENDING
            or error_category == ErrorCategory.CAP_EXCEEDED
        ):
            # Resumed or new attempt after the duration cap: re-check the
            # same job once before generating again, with a fresh duration
            # budget.
            self._reuse_job_id = state.job_id
            self._recheck_before_regenerate = True
            self._first_started_at = now
            state.first_started_at = now
            state.run_attempt = run_attempt
        else:
            self._reuse_job_id = None
            self._recheck_before_regenerate = False
            state.job_id = None
            state.first_started_at = None
            state.run_attempt = None

    async def _record_job(self, job_id: int) -> None:
        now = self._clock()
        self._first_started_at = now
        self._recheck_before_regenerate = False
        self._abandoned_prior_job = False

        def mutate(state: StepState, run_attempt: int) -> None:
            state.status = StepStatusEnum.RUNNING
            state.job_id = job_id
            state.first_started_at = now
            state.run_attempt = run_attempt

        await self._transact(mutate)

    def _over_duration_cap(self) -> bool:
        return (
            self._first_started_at is not None
            and self._clock() - self._first_started_at > self._max_step_duration
        )

    def _cap_exceeded_error(self, job_id: int) -> StepError:
        seconds = int(self._max_step_duration.total_seconds())
        return StepError(
            409,
            ErrorCategory.CAP_EXCEEDED,
            f"Generation job {job_id} is still running after the maximum "
            f"step duration of {seconds}s "
            "(WORKFLOW_MAX_STEP_DURATION_SECONDS).",
            job_terminal=True,
        )

    @staticmethod
    def _recorded_error(state: StepState) -> StepError:
        info = state.error or StepErrorInfo()
        category = _parse_category(info.category)
        return StepError(
            info.http_status or status_for_category(category),
            category,
            info.detail or "The generation job of this step failed.",
            job_terminal=True,
        )

    def _load_state(self, raw: Any) -> StepState:
        if raw is None:
            return StepState()
        try:
            return StepState.model_validate(raw)
        except ValidationError:
            logger.warning(
                "Ignoring unreadable state of step %s in run %s.",
                self.step_id,
                self.run_id,
            )
            return StepState()

    async def _transact(self, mutate: StepMutation) -> Any:
        """Runs ``mutate`` on the locked step state in one transaction.

        Writes the step state only when it changed, always ends the
        transaction (releasing the row lock) and raises the ``StepError``
        returned by ``mutate`` after committing.
        """
        db = self._repository.db
        try:
            context = await self._repository.lock_step_context(self.run_id)
            if context is None:
                raise StepError(
                    404,
                    ErrorCategory.MISSING_RESOURCE,
                    "Workflow run not found.",
                )
            if context.user_id != self._user_id:
                raise StepError(
                    403,
                    ErrorCategory.FORBIDDEN,
                    "The workflow run belongs to another user.",
                )
            state = self._load_state(context.step_states.get(self.step_id))
            before = state.to_json()
            outcome = mutate(state, context.attempt_count)
            after = state.to_json()
            if after != before:
                await self._repository.set_step_state(
                    self.run_id, self.step_id, after
                )
            await db.commit()
        except Exception:
            await self._rollback()
            raise
        if isinstance(outcome, StepError):
            raise outcome
        return outcome

    async def _rollback(self) -> None:
        try:
            await self._repository.db.rollback()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Rollback failed for run %s.", self.run_id, exc_info=True
            )
