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

"""State transitions, cap enforcement and checkpoint reads for workflow runs.

Handles the callbacks emitted by the generated GCP Workflows YAML:

* ``on_finished`` marks a ``RUNNING`` run ``COMPLETED`` (or ``CANCELED``) or
  delegates ``FAILED`` outcomes to ``on_step_failed``;
* ``on_step_failed`` persists ``STEP_FAILED``, classifies the failure, owns
  step ``attempts`` when ``counts_as_attempt(category)`` is true, enforces
  step and run caps, and transitions the run to ``QUEUED`` (continuation,
  session wait, or backoff retry with ``attempt_count`` advanced) or
  ``NEEDS_ATTENTION``;
* ``get_checkpoint`` serves ``prior_outputs`` to ``GET /runs/{run_id}/checkpoint``
  when the checkpoint is too large for execution arguments (Q7).
"""

import datetime
import inspect
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends
from pydantic import ValidationError

from src.common.secret_redaction import (
    install_secret_redaction,
    sanitize_error_detail,
)
from src.config.config_service import config_service
from src.workflows.dto.workflow_run_dto import (
    ExecutionCallbackStatusEnum,
    RunFinishedCallbackDto,
)
from src.workflows.queue.backoff import compute_next_retry_at
from src.workflows.queue.failure_classifier import (
    Classification,
    ErrorCategory,
    classify,
)
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows.schema.workflow_model import (
    StepStatusEnum,
    WorkflowBase,
    WorkflowRunStatusEnum,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepErrorInfo,
    StepState,
    WorkflowRunExecution,
    WorkflowRunModel,
)
from src.workflows.workflow_yaml_builder import (
    RESERVED_ARGS,
    build_prior_outputs,
    compute_definition_hash,
    missing_required_args,
    reconcile_step_states_for_resume,
)
from src.workflows_executor.step_errors import StepError

logger = install_secret_redaction(logging.getLogger(__name__))

# Short fixed delay before dispatching an L3 STEP_IN_PROGRESS continuation.
CONTINUATION_DELAY_SECONDS = 5
# Stale RUNNING claim threshold when execution_ids is empty (spec §8.4, E5).
STALE_CLAIM_SECONDS = 120
SECONDS_PER_DAY = 86400


class MissingResumeInputsError(StepError):
    """Raised (HTTP 422) when a resumed run is missing required user inputs."""

    def __init__(self, missing_inputs: list[str]) -> None:
        self.missing_inputs = list(missing_inputs)
        joined = ", ".join(self.missing_inputs)
        super().__init__(
            422,
            ErrorCategory.INVALID_INPUT,
            f"Missing required workflow inputs for resume: {joined}",
            retry_safe=False,
        )


DispatchHook = Callable[[str, int | None], Awaitable[Any] | Any]
_default_dispatch_hook: DispatchHook | None = None


def set_dispatch_hook(hook: DispatchHook | None) -> None:
    """Registers the process-wide dispatcher trigger hook (used by Phase 3)."""
    global _default_dispatch_hook  # pylint: disable=global-statement
    _default_dispatch_hook = hook


def get_dispatch_hook() -> DispatchHook | None:
    """Returns the currently registered dispatcher trigger hook, if any."""
    return _default_dispatch_hook


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def fold_session_wait(run: WorkflowRunModel, now: datetime.datetime) -> int:
    """Total ``session_wait_seconds`` including any active session-wait span."""
    accumulated = max(0, run.session_wait_seconds or 0)
    if run.waiting_for_session_since is None:
        return accumulated
    elapsed = (now - run.waiting_for_session_since).total_seconds()
    return accumulated + max(0, int(elapsed))


def _active_execution_statuses() -> frozenset[WorkflowRunStatusEnum]:
    return frozenset(
        {
            WorkflowRunStatusEnum.RUNNING,
            WorkflowRunStatusEnum.STEP_FAILED,
        }
    )


def _is_active_execution(
    run: WorkflowRunModel, execution_id: str | None
) -> bool:
    """True when ``run`` is running and ``execution_id`` is its latest one."""
    if WorkflowRunStatusEnum(run.status) not in _active_execution_statuses():
        return False
    if run.execution_ids and execution_id:
        return run.execution_ids[-1].execution_id == execution_id
    return True


def _update_execution_history(
    run: WorkflowRunModel,
    execution_id: str | None,
    state: str,
    now: datetime.datetime,
) -> list[WorkflowRunExecution]:
    """Marks the latest execution entry ended (or appends one if empty)."""
    entries = [item.model_copy(deep=True) for item in run.execution_ids]
    if entries:
        entries[-1].ended_at = now
        entries[-1].state = state
    elif execution_id:
        entries.append(
            WorkflowRunExecution(
                execution_id=execution_id,
                started_at=run.dispatched_at or run.started_at,
                ended_at=now,
                state=state,
            )
        )
    return entries


def _resolve_step_id(run: WorkflowRunModel, step_id: str | None) -> str | None:
    """Finds the step that failed from the callback or the run state."""
    cleaned = (step_id or "").strip()
    if cleaned:
        return cleaned
    if run.current_step_id:
        return run.current_step_id
    for candidate_id, state in run.step_states.items():
        if state.status in (StepStatusEnum.RUNNING, StepStatusEnum.FAILED):
            return candidate_id
    return None


def _snapshot_steps(snapshot: Mapping[str, Any] | None) -> list[Any]:
    """Validates and returns the workflow steps stored in ``snapshot``."""
    if not isinstance(snapshot, Mapping) or not snapshot.get("steps"):
        return []
    try:
        workflow = WorkflowBase.model_validate(
            {
                "name": snapshot.get("name") or "Workflow",
                "description": snapshot.get("description"),
                "steps": snapshot.get("steps", []),
            }
        )
        return list(workflow.steps)
    except ValidationError:
        logger.warning("Could not parse workflow_snapshot steps.")
        return []


def _parse_json_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return None
            if isinstance(parsed, Mapping):
                return parsed
    return None


def _detail_from_mapping(data: Mapping[str, Any]) -> str | None:
    """Extracts the most informative message from a GCP or executor payload."""
    detail_keys = ("detail", "error_message", "errorMessage", "message")
    body = data.get("body")
    body_map = _parse_json_mapping(body)
    if body_map is not None:
        for key in detail_keys:
            val = body_map.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        nested = _parse_json_mapping(body_map.get("error"))
        if nested is not None:
            msg = nested.get("message") or nested.get("detail")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
    elif isinstance(body, str) and body.strip():
        return body.strip()

    for key in (*detail_keys, "context"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_error_detail(
    error: Any,
    step_state: StepState | None,
    classification: Classification,
) -> str:
    """Builds a sanitised, bounded error detail string (never contains tokens)."""
    raw: str | None = None
    mapping = _parse_json_mapping(error)
    if mapping is not None:
        raw = _detail_from_mapping(mapping)
    elif isinstance(error, str) and error.strip():
        raw = error.strip()
    elif isinstance(error, BaseException):
        detail_attr = getattr(error, "detail", None)
        raw = str(detail_attr) if detail_attr else str(error)

    if not raw and step_state is not None and step_state.error is not None:
        if step_state.error.detail:
            raw = step_state.error.detail
    if not raw:
        raw = classification.reason
    return sanitize_error_detail(raw)


def _extract_http_status(
    error: Any, step_state: StepState | None
) -> int | None:
    mapping = _parse_json_mapping(error)
    if mapping is not None:
        for key in ("http_status", "httpStatus", "status_code", "code"):
            value = mapping.get(key)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 100 <= value <= 599
            ):
                return value
    if step_state is not None and step_state.error is not None:
        return step_state.error.http_status
    return None


class RunStateService:
    """Manages workflow run state transitions and cap enforcement."""

    def __init__(
        self,
        repository: WorkflowRunRepository = Depends(),
        *,
        dispatch_hook: DispatchHook | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        rng: random.Random | None = None,
        max_step_attempts: int | None = None,
        max_step_duration_seconds: int | None = None,
        max_run_executions: int | None = None,
        max_run_age_hours: int | None = None,
        max_session_wait_days: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        continuation_delay_seconds: float = CONTINUATION_DELAY_SECONDS,
    ) -> None:
        self._repository = repository
        self._dispatch_hook = dispatch_hook
        self._clock = clock or _utcnow
        self._rng = rng
        self._max_step_attempts = (
            config_service.WORKFLOW_MAX_STEP_ATTEMPTS
            if max_step_attempts is None
            else int(max_step_attempts)
        )
        self._max_step_duration_seconds = (
            config_service.WORKFLOW_MAX_STEP_DURATION_SECONDS
            if max_step_duration_seconds is None
            else int(max_step_duration_seconds)
        )
        self._max_run_executions = (
            config_service.WORKFLOW_MAX_RUN_EXECUTIONS
            if max_run_executions is None
            else int(max_run_executions)
        )
        self._max_run_age_hours = (
            config_service.WORKFLOW_MAX_RUN_AGE_HOURS
            if max_run_age_hours is None
            else int(max_run_age_hours)
        )
        self._max_session_wait_days = (
            config_service.WORKFLOW_MAX_SESSION_WAIT_DAYS
            if max_session_wait_days is None
            else int(max_session_wait_days)
        )
        self._retry_base_seconds = float(
            config_service.WORKFLOW_RETRY_BASE_SECONDS
            if retry_base_seconds is None
            else retry_base_seconds
        )
        self._retry_max_seconds = float(
            config_service.WORKFLOW_RETRY_MAX_SECONDS
            if retry_max_seconds is None
            else retry_max_seconds
        )
        self._continuation_delay_seconds = float(continuation_delay_seconds)

    async def get_checkpoint(
        self,
        run_id: str,
        *,
        user_id: int | None = None,
        execution_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Returns ``prior_outputs`` for ``GET /runs/{run_id}/checkpoint`` (Q7).

        Only outputs referenced by downstream steps are returned, with ``{}``
        for completed steps that have no downstream consumers so their gates
        still skip them.
        """
        del execution_id  # Reserved for audit logging / future tracing.
        run = await self._repository.get_by_id(run_id)
        if run is None:
            raise StepError(
                404,
                ErrorCategory.MISSING_RESOURCE,
                "Workflow run not found.",
            )
        if user_id is not None and run.user_id != user_id:
            raise StepError(
                403,
                ErrorCategory.FORBIDDEN,
                "The workflow run belongs to another user.",
            )
        steps = _snapshot_steps(run.workflow_snapshot)
        if steps:
            return build_prior_outputs(steps, run.step_states)
        return {
            step_id: dict(state.outputs or {})
            for step_id, state in run.step_states.items()
            if state.status == StepStatusEnum.COMPLETED
            and state.outputs is not None
        }

    async def on_finished(
        self,
        run_id: str,
        payload: RunFinishedCallbackDto | Mapping[str, Any] | None = None,
        *,
        user_id: int | None = None,
        execution_id: str | None = None,
        status: ExecutionCallbackStatusEnum | str | None = None,
        step_id: str | None = None,
        error: Any = None,
    ) -> WorkflowRunModel:
        """Handles the completion callback of a GCP workflow execution."""
        if isinstance(payload, Mapping):
            dto = RunFinishedCallbackDto.model_validate(payload)
        elif isinstance(payload, RunFinishedCallbackDto):
            dto = payload
        else:
            if not execution_id or status is None:
                raise ValueError("execution_id and status are required")
            dto = RunFinishedCallbackDto(
                execution_id=execution_id,
                status=ExecutionCallbackStatusEnum(status),
                step_id=step_id,
                error=error,
            )

        outcome_status = ExecutionCallbackStatusEnum(dto.status)
        if outcome_status is ExecutionCallbackStatusEnum.FAILED:
            return await self.on_step_failed(
                run_id,
                error=dto.error,
                step_id=dto.step_id,
                execution_id=dto.execution_id,
                user_id=user_id,
            )

        now = self._clock()
        db = self._repository.db
        try:
            run = await self._lock_and_authorize(run_id, user_id)
            if not _is_active_execution(run, dto.execution_id):
                await db.commit()
                return run

            target_status = (
                WorkflowRunStatusEnum.COMPLETED
                if outcome_status is ExecutionCallbackStatusEnum.SUCCEEDED
                else WorkflowRunStatusEnum.CANCELED
            )
            gcp_state = (
                "SUCCEEDED"
                if target_status is WorkflowRunStatusEnum.COMPLETED
                else "CANCELLED"
            )
            executions = _update_execution_history(
                run, dto.execution_id, gcp_state, now
            )
            folded_wait = fold_session_wait(run, now)
            updates: dict[str, Any] = {
                "status": target_status.value,
                "completed_at": now,
                "queue_reason": None,
                "next_retry_at": None,
                "current_step_id": None,
                "waiting_for_session_since": None,
                "session_wait_seconds": folded_wait,
                "execution_ids": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in executions
                ],
            }
            if target_status is WorkflowRunStatusEnum.COMPLETED:
                updates["last_error_category"] = None
                updates["last_error_detail"] = None
            await self._repository.update_fields(run_id, updates)
            await db.commit()
        except Exception:
            await self._rollback()
            raise

        updated_run = run.model_copy(
            update={
                **updates,
                "status": target_status,
                "execution_ids": executions,
            }
        )
        await self._trigger_dispatch("completion", run.user_id)
        return updated_run

    async def on_step_failed(
        self,
        run_id: str,
        *,
        error: Any = None,
        step_id: str | None = None,
        execution_id: str | None = None,
        user_id: int | None = None,
    ) -> WorkflowRunModel:
        """Classifies a step failure and transitions the run."""
        now = self._clock()
        db = self._repository.db
        try:
            run = await self._lock_and_authorize(run_id, user_id)
            if not _is_active_execution(run, execution_id):
                await db.commit()
                return run

            effective_step_id = _resolve_step_id(run, step_id)
            # Short-lived STEP_FAILED state persisted in the same transaction
            # so a crash during classification is visible.
            await self._repository.update_fields(
                run_id,
                {
                    "status": WorkflowRunStatusEnum.STEP_FAILED.value,
                    "current_step_id": effective_step_id,
                },
            )

            step_state = (
                (
                    run.step_states.get(effective_step_id) or StepState()
                ).model_copy(deep=True)
                if effective_step_id is not None
                else None
            )
            has_inflight_job = bool(
                step_state is not None
                and step_state.job_id is not None
                and step_state.status != StepStatusEnum.FAILED
            )
            signals = self._combine_error_signals(error, step_state)
            prior_attempts = (
                step_state.attempts
                if step_state is not None
                else max(run.attempt_count, 0)
            )
            classification = classify(
                signals,
                has_inflight_job=has_inflight_job,
                attempt=prior_attempts + 1,
                max_attempts=None,
            )

            if step_state is not None:
                if classification.counts_as_attempt:
                    step_state.attempts += 1
                elif (
                    classification.category is ErrorCategory.STEP_IN_PROGRESS
                    and step_state.in_progress_continuations == 0
                ):
                    step_state.in_progress_continuations = 1
            step_attempts = (
                step_state.attempts
                if step_state is not None
                else prior_attempts
                + (1 if classification.counts_as_attempt else 0)
            )

            folded_wait = fold_session_wait(run, now)
            base_detail = _extract_error_detail(
                error, step_state, classification
            )
            http_status = _extract_http_status(error, step_state)

            final_category, retryable, detail = self._evaluate_caps_and_inputs(
                run=run,
                step_state=step_state,
                classification=classification,
                step_attempts=step_attempts,
                session_wait_seconds=folded_wait,
                base_detail=base_detail,
                now=now,
            )

            if step_state is not None and effective_step_id is not None:
                self._apply_step_failure_state(
                    step_state,
                    category=final_category,
                    retryable=retryable,
                    has_inflight_job=has_inflight_job,
                    http_status=http_status,
                    detail=detail,
                )
                await self._repository.set_step_state(
                    run_id, effective_step_id, step_state.to_json()
                )

            executions = _update_execution_history(
                run, execution_id, "FAILED", now
            )
            updates = self._build_failure_run_updates(
                run=run,
                category=final_category,
                retryable=retryable,
                detail=detail,
                effective_step_id=effective_step_id,
                step_attempts=step_attempts,
                session_wait_seconds=folded_wait,
                executions=executions,
                now=now,
            )
            await self._repository.update_fields(run_id, updates)
            await db.commit()
        except Exception:
            await self._rollback()
            raise

        new_step_states = dict(run.step_states)
        if step_state is not None and effective_step_id is not None:
            new_step_states[effective_step_id] = step_state
        updated_run = run.model_copy(
            update={
                **updates,
                "status": WorkflowRunStatusEnum(updates["status"]),
                "queue_reason": (
                    QueueReasonEnum(updates["queue_reason"])
                    if updates["queue_reason"] is not None
                    else None
                ),
                "last_error_category": final_category,
                "execution_ids": executions,
                "step_states": new_step_states,
            }
        )
        await self._trigger_dispatch("step_failed", run.user_id)
        return updated_run

    async def expire_session_wait(
        self,
        run_id: str,
        *,
        user_id: int | None = None,
    ) -> WorkflowRunModel:
        """Parks a ``WAITING_FOR_SESSION`` run in ``NEEDS_ATTENTION`` if expired.

        Enforces ``WORKFLOW_MAX_SESSION_WAIT_DAYS`` (7 days by default).
        """
        now = self._clock()
        db = self._repository.db
        try:
            run = await self._lock_and_authorize(run_id, user_id)
            folded_wait = fold_session_wait(run, now)
            max_wait_seconds = self._max_session_wait_days * SECONDS_PER_DAY
            if (
                WorkflowRunStatusEnum(run.status)
                is not WorkflowRunStatusEnum.QUEUED
                or run.queue_reason != QueueReasonEnum.WAITING_FOR_SESSION
                or folded_wait < max_wait_seconds
            ):
                await db.commit()
                return run

            detail = sanitize_error_detail(
                "Exceeded WORKFLOW_MAX_SESSION_WAIT_DAYS "
                f"({self._max_session_wait_days}d) while waiting for a fresh "
                "user session."
            )
            updates: dict[str, Any] = {
                "status": WorkflowRunStatusEnum.NEEDS_ATTENTION.value,
                "queue_reason": None,
                "next_retry_at": None,
                "waiting_for_session_since": None,
                "session_wait_seconds": folded_wait,
                "last_error_category": ErrorCategory.CAP_EXCEEDED.value,
                "last_error_detail": detail,
            }
            await self._repository.update_fields(run_id, updates)
            await db.commit()
        except Exception:
            await self._rollback()
            raise

        return run.model_copy(
            update={
                **updates,
                "status": WorkflowRunStatusEnum.NEEDS_ATTENTION,
                "queue_reason": None,
                "last_error_category": ErrorCategory.CAP_EXCEEDED,
            }
        )

    async def resume(
        self,
        run_id: str,
        *,
        args_override: Mapping[str, Any] | None = None,
        current_workflow: Any = None,
        current_workflow_snapshot: Any = None,
        user_id: int | None = None,
        workflow_id: str | None = None,
    ) -> WorkflowRunModel:
        """Resumes a ``NEEDS_ATTENTION`` or ``WAITING_FOR_SESSION`` run.

        Reconciles step definition hashes against ``current_workflow`` (if
        supplied) or the stored ``workflow_snapshot``, invalidates steps whose
        definition or upstream inputs changed, validates required user
        inputs (raising :class:`MissingResumeInputsError` on 422), resets the
        failed step's attempt counter, and transitions to ``QUEUED`` with
        ``queue_reason = RESUME_REQUESTED``.
        """
        now = self._clock()
        db = self._repository.db
        try:
            run = await self._lock_and_authorize_owner(
                run_id, user_id=user_id, workflow_id=workflow_id
            )
            current_status = WorkflowRunStatusEnum(run.status)
            is_session_wait = (
                current_status is WorkflowRunStatusEnum.QUEUED
                and run.queue_reason == QueueReasonEnum.WAITING_FOR_SESSION
            )
            if (
                current_status is not WorkflowRunStatusEnum.NEEDS_ATTENTION
                and not is_session_wait
            ):
                raise StepError(
                    409,
                    ErrorCategory.INVALID_INPUT,
                    f"Cannot resume workflow run in status '{current_status.value}'.",
                )

            effective_workflow = (
                current_workflow
                if current_workflow is not None
                else current_workflow_snapshot
            )
            previous_steps = _snapshot_steps(run.workflow_snapshot)
            snapshot = self._resolve_resume_snapshot(run, effective_workflow)
            steps = _snapshot_steps(snapshot)
            new_def_hash = compute_definition_hash(steps) if steps else None

            old_args = {
                k: v
                for k, v in (run.input_args or {}).items()
                if k not in RESERVED_ARGS
            }
            cleaned_override = {
                k: v
                for k, v in (args_override or {}).items()
                if k not in RESERVED_ARGS
            }
            effective_args = {**old_args, **cleaned_override}
            if (
                run.workspace_id is not None
                and effective_args.get("workspace_id") is None
            ):
                effective_args["workspace_id"] = run.workspace_id

            missing = missing_required_args(steps, effective_args)
            if missing:
                raise MissingResumeInputsError(missing)

            changed_inputs = [
                key
                for key, val in cleaned_override.items()
                if old_args.get(key) != val
            ]
            reconciled_states, first_incomplete = (
                reconcile_step_states_for_resume(
                    steps,
                    run.step_states,
                    run_definition_hash=run.definition_hash,
                    changed_input_names=changed_inputs,
                    previous_steps=previous_steps,
                    run_last_error_category=run.last_error_category,
                )
            )
            validated_states = {
                step_id: StepState.model_validate(state_dict)
                for step_id, state_dict in reconciled_states.items()
            }
            folded_wait = fold_session_wait(run, now)

            updates: dict[str, Any] = {
                "status": WorkflowRunStatusEnum.QUEUED.value,
                "queue_reason": QueueReasonEnum.RESUME_REQUESTED.value,
                "next_retry_at": now,
                "waiting_for_session_since": None,
                "session_wait_seconds": folded_wait,
                "current_step_id": first_incomplete,
                "attempt_count": 0,
                "input_args": effective_args,
                "workflow_snapshot": snapshot,
                "definition_hash": new_def_hash,
                "step_states": {
                    step_id: state.to_json()
                    for step_id, state in validated_states.items()
                },
                "last_error_category": None,
                "last_error_detail": None,
            }
            await self._repository.update_fields(run_id, updates)
            await db.commit()
        except Exception:
            await self._rollback()
            raise

        updated_run = run.model_copy(
            update={
                **updates,
                "status": WorkflowRunStatusEnum.QUEUED,
                "queue_reason": QueueReasonEnum.RESUME_REQUESTED,
                "step_states": validated_states,
                "last_error_category": None,
            }
        )
        await self._trigger_dispatch("resume", run.user_id)
        return updated_run

    async def cancel(
        self,
        run_id: str,
        *,
        user_id: int | None = None,
        workflow_id: str | None = None,
        cancel_execution_cb: (
            Callable[[WorkflowRunModel, str], Awaitable[Any] | Any] | None
        ) = None,
        cancel_execution_fn: (
            Callable[[str], Awaitable[Any] | Any] | None
        ) = None,
    ) -> WorkflowRunModel:
        """Cancels a non-terminal run and best-effort cancels its GCP execution."""
        now = self._clock()
        db = self._repository.db
        try:
            run = await self._lock_and_authorize_owner(
                run_id, user_id=user_id, workflow_id=workflow_id
            )
            current_status = WorkflowRunStatusEnum(run.status)
            if current_status in (
                WorkflowRunStatusEnum.COMPLETED,
                WorkflowRunStatusEnum.CANCELED,
            ):
                raise StepError(
                    409,
                    ErrorCategory.INVALID_INPUT,
                    "Cannot cancel workflow run in terminal status "
                    f"'{current_status.value}'.",
                )

            was_running = current_status in _active_execution_statuses()
            active_exec_id = (
                run.execution_ids[-1].execution_id
                if was_running and run.execution_ids
                else None
            )
            executions = (
                _update_execution_history(run, active_exec_id, "CANCELLED", now)
                if was_running
                else [item.model_copy(deep=True) for item in run.execution_ids]
            )
            folded_wait = fold_session_wait(run, now)
            updates: dict[str, Any] = {
                "status": WorkflowRunStatusEnum.CANCELED.value,
                "completed_at": now,
                "canceled_by_user": True,
                "queue_reason": None,
                "next_retry_at": None,
                "waiting_for_session_since": None,
                "session_wait_seconds": folded_wait,
                "current_step_id": None,
                "execution_ids": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in executions
                ],
            }
            await self._repository.update_fields(run_id, updates)
            await db.commit()
        except Exception:
            await self._rollback()
            raise

        updated_run = run.model_copy(
            update={
                **updates,
                "status": WorkflowRunStatusEnum.CANCELED,
                "queue_reason": None,
                "execution_ids": executions,
            }
        )
        if active_exec_id and (
            cancel_execution_cb is not None or cancel_execution_fn is not None
        ):
            try:
                if cancel_execution_cb is not None:
                    cb_res = cancel_execution_cb(updated_run, active_exec_id)
                else:
                    assert cancel_execution_fn is not None
                    cb_res = cancel_execution_fn(active_exec_id)
                if inspect.isawaitable(cb_res):
                    await cb_res
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Best-effort GCP execution cancel failed for run %s "
                    "(execution %s).",
                    run_id,
                    active_exec_id,
                    exc_info=True,
                )
        if was_running:
            await self._trigger_dispatch("cancel", run.user_id)
        return updated_run

    async def reconcile_run(
        self,
        run: WorkflowRunModel,
        *,
        gcp_state: str | None = None,
        gcp_error: Any = None,
        get_execution_fn: Callable[[str], Any] | None = None,
        stale_claim_seconds: int = STALE_CLAIM_SECONDS,
    ) -> WorkflowRunModel:
        """Reconciles a single active or session-waiting run.

        * ``QUEUED`` with ``WAITING_FOR_SESSION`` -> checks 7-day expiry.
        * ``RUNNING`` with empty ``execution_ids`` and ``dispatched_at`` older
          than ``stale_claim_seconds`` (2 min) -> re-queues as ``WAITING_FOR_SLOT``
          (crash between claim commit and ``create_execution``). Backfilled
          migration rows have non-empty ``execution_ids`` and never match.
        * ``RUNNING`` / ``STEP_FAILED`` with non-empty ``execution_ids`` and a
          terminal ``gcp_state`` (``SUCCEEDED``, ``CANCELLED``, ``FAILED``) ->
          delegates to ``on_finished`` / ``on_step_failed``.
        """
        current_status = WorkflowRunStatusEnum(run.status)
        if (
            current_status is WorkflowRunStatusEnum.QUEUED
            and run.queue_reason == QueueReasonEnum.WAITING_FOR_SESSION
        ):
            return await self.expire_session_wait(run.id)

        if current_status not in _active_execution_statuses():
            return run

        now = self._clock()
        if not run.execution_ids:
            dispatched_at = run.dispatched_at
            if dispatched_at is None:
                return run
            if dispatched_at.tzinfo is None:
                dispatched_at = dispatched_at.replace(tzinfo=datetime.UTC)
            elapsed = (now - dispatched_at).total_seconds()
            if elapsed < stale_claim_seconds:
                return run

            db = self._repository.db
            try:
                locked = await self._repository.lock_run(run.id)
                if (
                    locked is None
                    or WorkflowRunStatusEnum(locked.status)
                    is not WorkflowRunStatusEnum.RUNNING
                    or locked.execution_ids
                ):
                    await db.commit()
                    return locked or run
                updates: dict[str, Any] = {
                    "status": WorkflowRunStatusEnum.QUEUED.value,
                    "queue_reason": QueueReasonEnum.WAITING_FOR_SLOT.value,
                    "next_retry_at": now,
                }
                await self._repository.update_fields(run.id, updates)
                await db.commit()
                return locked.model_copy(
                    update={
                        **updates,
                        "status": WorkflowRunStatusEnum.QUEUED,
                        "queue_reason": QueueReasonEnum.WAITING_FOR_SLOT,
                    }
                )
            except Exception:
                await self._rollback()
                raise

        latest_exec_id = run.execution_ids[-1].execution_id
        if gcp_state is None and get_execution_fn is not None:
            raw_exec = get_execution_fn(latest_exec_id)
            if inspect.isawaitable(raw_exec):
                raw_exec = await raw_exec
            if isinstance(raw_exec, Mapping):
                gcp_state = str(raw_exec.get("state") or "")
                gcp_error = raw_exec.get("error")
            elif raw_exec is not None:
                state_attr = getattr(raw_exec, "state", None)
                gcp_state = (
                    state_attr.name
                    if hasattr(state_attr, "name")
                    else str(state_attr or "")
                )
                gcp_error = getattr(raw_exec, "error", None)

        normalized_state = (gcp_state or "").strip().upper()
        if normalized_state == "SUCCEEDED":
            return await self.on_finished(
                run.id,
                execution_id=latest_exec_id,
                status=ExecutionCallbackStatusEnum.SUCCEEDED,
            )
        if normalized_state in ("CANCELLED", "CANCELED"):
            return await self.on_finished(
                run.id,
                execution_id=latest_exec_id,
                status=ExecutionCallbackStatusEnum.CANCELLED,
            )
        if normalized_state == "FAILED":
            return await self.on_step_failed(
                run.id,
                execution_id=latest_exec_id,
                error=gcp_error
                or "GCP workflow execution ended in FAILED state.",
            )
        return run

    # --- Internals --------------------------------------------------------

    async def _lock_and_authorize_owner(
        self,
        run_id: str,
        *,
        user_id: int | None,
        workflow_id: str | None,
    ) -> WorkflowRunModel:
        """Locks ``run_id`` and enforces owner/workflow match (404 on mismatch)."""
        run = await self._repository.lock_run(run_id)
        if (
            run is None
            or (workflow_id is not None and run.workflow_id != workflow_id)
            or (user_id is not None and run.user_id != user_id)
        ):
            raise StepError(
                404,
                ErrorCategory.MISSING_RESOURCE,
                "Workflow run not found.",
            )
        return run

    @staticmethod
    def _resolve_resume_snapshot(
        run: WorkflowRunModel,
        current_workflow: Any,
    ) -> dict[str, Any]:
        if current_workflow is None:
            return dict(run.workflow_snapshot or {})
        if hasattr(current_workflow, "model_dump"):
            return current_workflow.model_dump(mode="json")
        if isinstance(current_workflow, Mapping):
            return dict(current_workflow)
        return dict(run.workflow_snapshot or {})

    async def _lock_and_authorize(
        self, run_id: str, user_id: int | None
    ) -> WorkflowRunModel:
        run = await self._repository.lock_run(run_id)
        if run is None:
            raise StepError(
                404,
                ErrorCategory.MISSING_RESOURCE,
                "Workflow run not found.",
            )
        if user_id is not None and run.user_id != user_id:
            raise StepError(
                403,
                ErrorCategory.FORBIDDEN,
                "The workflow run belongs to another user.",
            )
        return run

    @staticmethod
    def _combine_error_signals(error: Any, step_state: StepState | None) -> Any:
        if step_state is None or step_state.error is None:
            return error
        recorded = step_state.error.model_dump(exclude_none=True)
        if error is None:
            return recorded
        return [error, recorded]

    def _evaluate_caps_and_inputs(
        self,
        *,
        run: WorkflowRunModel,
        step_state: StepState | None,
        classification: Classification,
        step_attempts: int,
        session_wait_seconds: int,
        base_detail: str,
        now: datetime.datetime,
    ) -> tuple[ErrorCategory, bool, str]:
        """Applies step/run caps and input completeness checks."""
        category = classification.category
        if category is ErrorCategory.CAP_EXCEEDED:
            detail = base_detail
            if "WORKFLOW_MAX_" not in detail:
                detail = sanitize_error_detail(
                    "Exceeded WORKFLOW_MAX_STEP_DURATION_SECONDS "
                    f"({self._max_step_duration_seconds}s): {base_detail}"
                )
            return ErrorCategory.CAP_EXCEEDED, False, detail

        # 1. Step wall-clock duration cap across continuations.
        if (
            step_state is not None
            and step_state.first_started_at is not None
            and (
                classification.retryable
                or category is ErrorCategory.STEP_IN_PROGRESS
            )
        ):
            step_elapsed = (now - step_state.first_started_at).total_seconds()
            if step_elapsed >= self._max_step_duration_seconds:
                detail = sanitize_error_detail(
                    "Exceeded WORKFLOW_MAX_STEP_DURATION_SECONDS "
                    f"({int(step_elapsed)}s/{self._max_step_duration_seconds}s)"
                    f": {base_detail}"
                )
                return ErrorCategory.CAP_EXCEEDED, False, detail

        # 2. Hard 7-day session-wait expiry (Q6).
        if (
            session_wait_seconds
            >= self._max_session_wait_days * SECONDS_PER_DAY
        ):
            detail = sanitize_error_detail(
                "Exceeded WORKFLOW_MAX_SESSION_WAIT_DAYS "
                f"({self._max_session_wait_days}d): {base_detail}"
            )
            return ErrorCategory.CAP_EXCEEDED, False, detail

        # 3. Step failure attempts cap (continuations and 401 excluded).
        if (
            classification.counts_as_attempt
            and (classification.retryable or category is ErrorCategory.UNKNOWN)
            and step_attempts >= self._max_step_attempts
        ):
            detail = sanitize_error_detail(
                "Exceeded WORKFLOW_MAX_STEP_ATTEMPTS "
                f"({step_attempts}/{self._max_step_attempts}): {base_detail}"
            )
            return ErrorCategory.CAP_EXCEEDED, False, detail

        if not classification.retryable:
            return category, False, base_detail

        # 4. Failure-driven GCP executions per run cap.
        executions_run = max(run.attempt_count, 1)
        if (
            classification.counts_as_attempt
            and executions_run >= self._max_run_executions
        ):
            detail = sanitize_error_detail(
                "Exceeded WORKFLOW_MAX_RUN_EXECUTIONS "
                f"({executions_run}/{self._max_run_executions}): {base_detail}"
            )
            return ErrorCategory.CAP_EXCEEDED, False, detail

        # 5. Total run age cap excluding session wait (coalesce(queued_at, started_at)).
        anchor = run.queued_at or run.started_at
        effective_age_seconds = max(
            0.0, (now - anchor).total_seconds() - session_wait_seconds
        )
        if effective_age_seconds >= self._max_run_age_hours * 3600:
            detail = sanitize_error_detail(
                "Exceeded WORKFLOW_MAX_RUN_AGE_HOURS "
                f"({self._max_run_age_hours}h): {base_detail}"
            )
            return ErrorCategory.CAP_EXCEEDED, False, detail

        # 6. Auto re-queue requires complete required user inputs.
        missing = missing_required_args(
            _snapshot_steps(run.workflow_snapshot), run.input_args
        )
        if missing:
            detail = sanitize_error_detail(
                "Missing required workflow inputs for automatic retry "
                f"({', '.join(missing)}): {base_detail}"
            )
            return ErrorCategory.INVALID_INPUT, False, detail

        return category, True, base_detail

    @staticmethod
    def _apply_step_failure_state(
        step_state: StepState,
        *,
        category: ErrorCategory,
        retryable: bool,
        has_inflight_job: bool,
        http_status: int | None,
        detail: str,
    ) -> None:
        step_state.claim_id = None
        if retryable and category is ErrorCategory.STEP_IN_PROGRESS:
            # Keep job_id and RUNNING status so the next execution re-polls.
            step_state.status = StepStatusEnum.RUNNING
            return
        if retryable and category is ErrorCategory.AUTH_EXPIRED:
            if not has_inflight_job:
                step_state.status = StepStatusEnum.FAILED
            step_state.error = StepErrorInfo(
                category=category,
                http_status=http_status or 401,
                detail=detail,
            )
            return
        step_state.status = StepStatusEnum.FAILED
        step_state.error = StepErrorInfo(
            category=category,
            http_status=http_status,
            detail=detail,
        )

    def _build_failure_run_updates(
        self,
        *,
        run: WorkflowRunModel,
        category: ErrorCategory,
        retryable: bool,
        detail: str,
        effective_step_id: str | None,
        step_attempts: int,
        session_wait_seconds: int,
        executions: list[WorkflowRunExecution],
        now: datetime.datetime,
    ) -> dict[str, Any]:
        serialized_executions = [
            item.model_dump(mode="json", exclude_none=True)
            for item in executions
        ]
        if not retryable:
            return {
                "status": WorkflowRunStatusEnum.NEEDS_ATTENTION.value,
                "queue_reason": None,
                "next_retry_at": None,
                "waiting_for_session_since": None,
                "session_wait_seconds": session_wait_seconds,
                "current_step_id": effective_step_id,
                "attempt_count": run.attempt_count,
                "last_error_category": category.value,
                "last_error_detail": detail,
                "execution_ids": serialized_executions,
            }

        if category is ErrorCategory.STEP_IN_PROGRESS:
            next_retry_at = now + datetime.timedelta(
                seconds=self._continuation_delay_seconds
            )
            return {
                "status": WorkflowRunStatusEnum.QUEUED.value,
                "queue_reason": QueueReasonEnum.STEP_IN_PROGRESS.value,
                "next_retry_at": next_retry_at,
                "waiting_for_session_since": None,
                "session_wait_seconds": session_wait_seconds,
                "current_step_id": effective_step_id,
                "attempt_count": run.attempt_count,
                "last_error_category": category.value,
                "last_error_detail": detail,
                "execution_ids": serialized_executions,
            }

        if category is ErrorCategory.AUTH_EXPIRED:
            return {
                "status": WorkflowRunStatusEnum.QUEUED.value,
                "queue_reason": QueueReasonEnum.WAITING_FOR_SESSION.value,
                "next_retry_at": None,
                "waiting_for_session_since": now,
                "session_wait_seconds": session_wait_seconds,
                "current_step_id": effective_step_id,
                "attempt_count": run.attempt_count,
                "last_error_category": category.value,
                "last_error_detail": detail,
                "execution_ids": serialized_executions,
            }

        next_retry_at = compute_next_retry_at(
            max(step_attempts, 1),
            now,
            self._rng,
            base_seconds=self._retry_base_seconds,
            max_seconds=self._retry_max_seconds,
        )
        return {
            "status": WorkflowRunStatusEnum.QUEUED.value,
            "queue_reason": QueueReasonEnum.RETRY_SCHEDULED.value,
            "next_retry_at": next_retry_at,
            "waiting_for_session_since": None,
            "session_wait_seconds": session_wait_seconds,
            "current_step_id": effective_step_id,
            # Advance attempt_count on failure-driven re-queues so the Phase 1
            # StepIdempotencyGuard run_attempt contract holds on the next run.
            "attempt_count": (run.attempt_count or 0) + 1,
            "last_error_category": category.value,
            "last_error_detail": detail,
            "execution_ids": serialized_executions,
        }

    async def _trigger_dispatch(
        self, trigger: str, user_id: int | None
    ) -> None:
        hook = self._dispatch_hook or _default_dispatch_hook
        if hook is None:
            return
        try:
            result = hook(trigger, user_id)
            if inspect.isawaitable(result):
                await result
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Dispatch hook failed after %s transition.", trigger
            )

    async def _rollback(self) -> None:
        try:
            await self._repository.db.rollback()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("Rollback failed in RunStateService.", exc_info=True)


def get_run_state_service(
    repository: WorkflowRunRepository = Depends(),
) -> RunStateService:
    """FastAPI dependency provider for :class:`RunStateService`."""
    return RunStateService(repository=repository)
