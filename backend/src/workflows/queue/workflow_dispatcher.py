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

"""PostgreSQL-backed workflow queue dispatcher and reconciler (spec §8).

Implements:
* Advisory try-lock (``pg_try_advisory_xact_lock``) so concurrent dispatchers
  across Cloud Run instances skip immediately without double-claiming or
  exceeding ``MAX_RUNNING_WORKFLOWS`` (§8.1, E4);
* Reconciler pass (§8.4) for missed terminal callbacks (E6, E21), crash between
  claim commit and ``create_execution`` (E5), and 7-day ``WAITING_FOR_SESSION``
  expiry (Q6);
* Global-cap round-robin scheduling ordered by
  ``workflow_user_sessions.last_dispatched_at ASC NULLS FIRST`` with no
  per-user cap (Q16, H2, H3);
* Token validity check before claim -> transitions runs of users without a
  valid token to ``QUEUED / WAITING_FOR_SESSION`` (E1, E19);
* Execution creation with ``run_id``, decrypted ``user_auth_header`` (never
  persisted in ``input_args``), and ``prior_outputs`` / ``fetch_checkpoint``
  (Q7, E12), falling back to ``QUEUED / RETRY_SCHEDULED`` with ``TRANSIENT``
  backoff if ``create_execution`` fails (E16).
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
import dataclasses
import datetime
import inspect
import json
import logging
import random
import time
from typing import Any

from fastapi import Depends
from google.cloud.workflows import executions_v1
from google.cloud.workflows.executions_v1.types import Execution

from src.common.secret_redaction import (
    install_secret_redaction,
    sanitize_error_detail,
)
from src.config.config_service import config_service
from src.database import async_session_local
from src.users.user_model import UserModel
from src.workflows.queue.backoff import compute_next_retry_at
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.queue.run_state_service import (
    RunStateService,
    STALE_CLAIM_SECONDS,
    _snapshot_steps,
    fold_session_wait,
)
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows.schema.workflow_model import WorkflowRunStatusEnum
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    WorkflowRunExecution,
    WorkflowRunModel,
)
from src.workflows.session.token_store_service import (
    TokenStoreService,
    WorkflowUserSessionRepository,
)
from src.workflows.workflow_yaml_builder import (
    RESERVED_ARGS,
    prior_outputs_args,
)

logger = install_secret_redaction(logging.getLogger(__name__))

# Fixed 64-bit PostgreSQL advisory lock key for the workflow dispatcher.
WORKFLOW_DISPATCH_LOCK_ID = 0x4353_5746_4453_5031  # "CSWFDSP1"
DEFAULT_SCAN_LIMIT = 200
DEFAULT_RECONCILE_LIMIT = 50


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _normalize_dt(value: datetime.datetime | None) -> datetime.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


@dataclasses.dataclass(frozen=True)
class ClaimedRun:
    """A run claimed inside the dispatch transaction for GCP execution start."""

    run: WorkflowRunModel
    previous_attempt_count: int
    previous_queue_reason: QueueReasonEnum | None
    token: str


def should_increment_attempt_count(run: WorkflowRunModel) -> bool:
    """True when claiming ``run`` starts a new execution attempt (§8.1).

    * ``STEP_IN_PROGRESS`` continuations and ``WAITING_FOR_SESSION`` resumes do
      not increment ``attempt_count``.
    * Unparked session-wait runs (``queue_reason == WAITING_FOR_SLOT`` with
      ``last_error_category == AUTH_EXPIRED`` and ``attempt_count >= 1``) also
      do not increment ``attempt_count``.
    * ``RETRY_SCHEDULED`` runs whose ``attempt_count`` was already advanced by
      ``RunStateService.on_step_failed`` (``attempt_count > len(execution_ids)``)
      keep that pre-incremented value; if a ``RETRY_SCHEDULED`` row has
      ``attempt_count <= len(execution_ids)``, the dispatcher advances it.
    """
    reason = (
        QueueReasonEnum(run.queue_reason)
        if run.queue_reason is not None
        else None
    )
    if reason in (
        QueueReasonEnum.STEP_IN_PROGRESS,
        QueueReasonEnum.WAITING_FOR_SESSION,
    ):
        return False
    if (
        reason is QueueReasonEnum.WAITING_FOR_SLOT
        and run.last_error_category == ErrorCategory.AUTH_EXPIRED
        and (run.attempt_count or 0) > 0
    ):
        return False
    if reason is QueueReasonEnum.RETRY_SCHEDULED and (
        run.attempt_count or 0
    ) > len(run.execution_ids or []):
        return False
    return True


def build_execution_args(
    run: WorkflowRunModel,
    token: str,
) -> dict[str, Any]:
    """Builds the GCP Workflows execution arguments for ``run`` (§8.1, Q7).

    Injects ``run_id``, ``user_auth_header``, and ``prior_outputs`` (or
    ``fetch_checkpoint: True``) into a fresh dict without mutating
    ``run.input_args``.
    """
    args = {
        key: value
        for key, value in (run.input_args or {}).items()
        if key not in RESERVED_ARGS
    }
    if run.workspace_id is not None and args.get("workspace_id") is None:
        args["workspace_id"] = run.workspace_id

    cleaned_token = (token or "").strip()
    auth_header = (
        cleaned_token
        if cleaned_token.lower().startswith("bearer ")
        else f"Bearer {cleaned_token}"
    )
    args["run_id"] = run.id
    args["user_auth_header"] = auth_header

    steps = _snapshot_steps(run.workflow_snapshot)
    if steps:
        args.update(prior_outputs_args(steps, run.step_states))
    return args


def pick_runs_round_robin(
    candidates: Sequence[tuple[WorkflowRunModel, datetime.datetime | None]],
    slots: int,
) -> tuple[list[WorkflowRunModel], list[WorkflowRunModel]]:
    """Selects up to ``slots`` runs round-robin across users (§8.1, Q16).

    Users are ordered by ``last_dispatched_at ASC NULLS FIRST`` (ties broken by
    their oldest candidate's ``coalesce(queued_at, started_at)`` and
    ``user_id``). Each round pops one oldest run from the user at the front of
    the queue and rotates that user to the back if they have more runs.

    Returns ``(picked_runs, unpicked_runs)``.
    """
    if slots <= 0 or not candidates:
        return [], [run for run, _ in candidates]

    user_runs: dict[int, list[WorkflowRunModel]] = {}
    user_last_dispatched: dict[int, datetime.datetime | None] = {}

    for run, last_dispatched in candidates:
        uid = run.user_id
        norm_last = _normalize_dt(last_dispatched)
        if uid not in user_runs:
            user_runs[uid] = []
            user_last_dispatched[uid] = norm_last
        elif norm_last is not None and (
            user_last_dispatched[uid] is None
            or norm_last > user_last_dispatched[uid]  # type: ignore[operator]
        ):
            user_last_dispatched[uid] = norm_last
        user_runs[uid].append(run)

    for uid, runs in user_runs.items():
        runs.sort(
            key=lambda r: (
                _normalize_dt(r.queued_at or r.started_at)
                or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                _normalize_dt(r.started_at)
                or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                r.id,
            )
        )

    def _user_sort_key(
        uid: int,
    ) -> tuple[bool, datetime.datetime, datetime.datetime, int]:
        last_dt = user_last_dispatched[uid]
        oldest_run = user_runs[uid][0]
        oldest_queued = _normalize_dt(
            oldest_run.queued_at or oldest_run.started_at
        ) or datetime.datetime.min.replace(tzinfo=datetime.UTC)
        return (
            last_dt is not None,
            last_dt or datetime.datetime.min.replace(tzinfo=datetime.UTC),
            oldest_queued,
            uid,
        )

    ordered_users = deque(sorted(user_runs.keys(), key=_user_sort_key))
    user_deques = {uid: deque(runs) for uid, runs in user_runs.items()}

    picked: list[WorkflowRunModel] = []
    while len(picked) < slots and ordered_users:
        uid = ordered_users.popleft()
        queue = user_deques[uid]
        if not queue:
            continue
        picked.append(queue.popleft())
        if queue:
            ordered_users.append(uid)

    unpicked: list[WorkflowRunModel] = []
    for uid in ordered_users:
        unpicked.extend(user_deques[uid])
    return picked, unpicked


CreateExecutionFn = Callable[
    [WorkflowRunModel, dict[str, Any]], Awaitable[str] | str
]
FetchGcpExecutionFn = Callable[
    [WorkflowRunModel, str],
    Awaitable[tuple[str | None, Any]] | tuple[str | None, Any],
]


class WorkflowDispatcher:
    """Claims due ``QUEUED`` runs under a global cap and starts GCP executions."""

    def __init__(
        self,
        run_repository: WorkflowRunRepository = Depends(),
        token_store: TokenStoreService = Depends(),
        run_state_service: RunStateService | None = None,
        *,
        create_execution_fn: CreateExecutionFn | None = None,
        fetch_gcp_execution_fn: FetchGcpExecutionFn | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        rng: random.Random | None = None,
        max_running_workflows: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        scan_limit: int = DEFAULT_SCAN_LIMIT,
        reconcile_limit: int = DEFAULT_RECONCILE_LIMIT,
        stale_claim_seconds: int = STALE_CLAIM_SECONDS,
    ) -> None:
        self._run_repo = run_repository
        self._token_store = token_store
        self._clock = clock or _utcnow
        self._rng = rng
        self._run_state_service = run_state_service or RunStateService(
            repository=run_repository,
            clock=self._clock,
            rng=self._rng,
        )
        self._create_execution_fn = create_execution_fn
        self._fetch_gcp_execution_fn = fetch_gcp_execution_fn
        self._max_running_workflows = (
            config_service.MAX_RUNNING_WORKFLOWS
            if max_running_workflows is None
            else int(max_running_workflows)
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
        self._scan_limit = int(scan_limit)
        self._reconcile_limit = int(reconcile_limit)
        self._stale_claim_seconds = int(stale_claim_seconds)
        self._last_dispatch_stamp: datetime.datetime | None = None
        self._db_lock = asyncio.Lock()
        self._executions_client: executions_v1.ExecutionsAsyncClient | None = (
            None
        )

    async def dispatch(
        self,
        trigger: str = "manual",
        user_id: int | None = None,
        *,
        run_reconciler: bool = True,
    ) -> list[WorkflowRunModel]:
        """Runs one dispatcher cycle (reconcile + claim + start executions)."""
        del user_id  # Used for logging / telemetry context.
        if run_reconciler and trigger not in ("submit", "batch_submit"):
            try:
                await self.reconcile()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Reconciler pass failed during dispatch.", exc_info=True
                )

        claimed = await self._claim_batch()
        if not claimed:
            return []

        results = await asyncio.gather(
            *(self._launch_claimed_run(item) for item in claimed),
            return_exceptions=True,
        )
        dispatched_runs: list[WorkflowRunModel] = []
        for item, result in zip(claimed, results):
            if isinstance(result, WorkflowRunModel):
                dispatched_runs.append(result)
            elif isinstance(result, BaseException):
                logger.error(
                    "Unexpected error launching claimed run %s: %s",
                    item.run.id,
                    result,
                )
        return dispatched_runs

    async def reconcile(self) -> list[WorkflowRunModel]:
        """Synchronizes active runs with GCP and expires stale claims (§8.4)."""
        active_runs = await self._run_repo.find_active_for_reconciliation(
            limit=self._reconcile_limit
        )
        if not active_runs:
            return []

        runs_to_fetch: list[WorkflowRunModel] = []
        for run in active_runs:
            try:
                status_enum = WorkflowRunStatusEnum(run.status)
            except ValueError:
                continue
            if (
                status_enum
                in (
                    WorkflowRunStatusEnum.RUNNING,
                    WorkflowRunStatusEnum.STEP_FAILED,
                )
                and run.execution_ids
            ):
                runs_to_fetch.append(run)

        gcp_results_by_run_id: dict[str, Any] = {}
        if runs_to_fetch:
            fetched_results = await asyncio.gather(
                *(
                    self._fetch_gcp_execution(
                        run, run.execution_ids[-1].execution_id
                    )
                    for run in runs_to_fetch
                ),
                return_exceptions=True,
            )
            gcp_results_by_run_id = {
                run.id: res for run, res in zip(runs_to_fetch, fetched_results)
            }

        reconciled: list[WorkflowRunModel] = []
        for run in active_runs:
            try:
                if run.id in gcp_results_by_run_id:
                    fetch_res = gcp_results_by_run_id[run.id]
                    if isinstance(fetch_res, BaseException):
                        raise fetch_res
                    gcp_state, gcp_error = fetch_res
                    updated = await self._run_state_service.reconcile_run(
                        run,
                        gcp_state=gcp_state,
                        gcp_error=gcp_error,
                        stale_claim_seconds=self._stale_claim_seconds,
                    )
                else:
                    updated = await self._run_state_service.reconcile_run(
                        run,
                        stale_claim_seconds=self._stale_claim_seconds,
                    )
                reconciled.append(updated)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to reconcile workflow run %s.",
                    run.id,
                    exc_info=True,
                )
        return reconciled

    # --- Claim phase (inside advisory-locked DB transaction) --------------

    async def _claim_batch(self) -> list[ClaimedRun]:
        now = _normalize_dt(self._clock()) or _utcnow()
        db = self._run_repo.db
        try:
            acquired = await self._run_repo.try_advisory_xact_lock(
                WORKFLOW_DISPATCH_LOCK_ID
            )
            if not acquired:
                await db.commit()
                return []

            running_total = await self._run_repo.count_running()
            slots = self._max_running_workflows - running_total
            if slots <= 0:
                await db.commit()
                return []

            raw_candidates = await self._run_repo.lock_due_queued_runs(
                now, limit=self._scan_limit
            )
            if not raw_candidates:
                await db.commit()
                return []

            due_candidates: list[
                tuple[WorkflowRunModel, datetime.datetime | None]
            ] = []
            for run, last_dispatched_at in raw_candidates:
                retry_at = _normalize_dt(run.next_retry_at)
                if retry_at is not None and retry_at > now:
                    continue
                due_candidates.append((run, last_dispatched_at))

            if not due_candidates:
                await db.commit()
                return []

            user_tokens: dict[int, str | None] = {}
            eligible_candidates: list[
                tuple[WorkflowRunModel, datetime.datetime | None]
            ] = []
            max_seen_dispatch_at: datetime.datetime | None = (
                self._last_dispatch_stamp
            )

            for run, last_dispatched_at in due_candidates:
                norm_last = _normalize_dt(last_dispatched_at)
                if norm_last is not None and (
                    max_seen_dispatch_at is None
                    or norm_last > max_seen_dispatch_at
                ):
                    max_seen_dispatch_at = norm_last

                uid = run.user_id
                if uid not in user_tokens:
                    user_tokens[uid] = await self._token_store.get_valid_token(
                        uid
                    )
                token = user_tokens[uid]
                if not token:
                    waiting_since = (
                        _normalize_dt(run.waiting_for_session_since) or now
                    )
                    if (
                        run.queue_reason != QueueReasonEnum.WAITING_FOR_SESSION
                        or run.waiting_for_session_since is None
                    ):
                        await self._run_repo.update_fields(
                            run.id,
                            {
                                "queue_reason": (
                                    QueueReasonEnum.WAITING_FOR_SESSION.value
                                ),
                                "waiting_for_session_since": waiting_since,
                                "next_retry_at": None,
                            },
                        )
                    continue
                eligible_candidates.append((run, norm_last))

            picked_runs, unpicked_runs = pick_runs_round_robin(
                eligible_candidates, slots
            )

            claimed: list[ClaimedRun] = []
            dispatch_stamp = now
            if (
                max_seen_dispatch_at is not None
                and dispatch_stamp <= max_seen_dispatch_at
            ):
                dispatch_stamp = max_seen_dispatch_at + datetime.timedelta(
                    microseconds=1
                )

            for index, run in enumerate(picked_runs):
                token = user_tokens.get(run.user_id) or ""
                prev_attempt = run.attempt_count or 0
                new_attempt = (
                    prev_attempt + 1
                    if should_increment_attempt_count(run)
                    else prev_attempt
                )
                folded_wait = fold_session_wait(run, now)
                updates: dict[str, Any] = {
                    "status": WorkflowRunStatusEnum.RUNNING.value,
                    "dispatched_at": now,
                    "queue_reason": None,
                    "next_retry_at": None,
                    "waiting_for_session_since": None,
                    "session_wait_seconds": folded_wait,
                    "attempt_count": new_attempt,
                }
                await self._run_repo.update_fields(run.id, updates)
                user_stamp = dispatch_stamp + datetime.timedelta(
                    microseconds=index
                )
                await self._token_store.touch_last_dispatched_at(
                    run.user_id, now=user_stamp
                )
                self._last_dispatch_stamp = user_stamp
                claimed_model = run.model_copy(
                    update={
                        **updates,
                        "status": WorkflowRunStatusEnum.RUNNING,
                        "queue_reason": None,
                    }
                )
                claimed.append(
                    ClaimedRun(
                        run=claimed_model,
                        previous_attempt_count=prev_attempt,
                        previous_queue_reason=run.queue_reason,
                        token=token,
                    )
                )

            for run in unpicked_runs:
                folded_wait = fold_session_wait(run, now)
                if (
                    run.queue_reason != QueueReasonEnum.WAITING_FOR_SLOT
                    or run.waiting_for_session_since is not None
                ):
                    await self._run_repo.update_fields(
                        run.id,
                        {
                            "queue_reason": (
                                QueueReasonEnum.WAITING_FOR_SLOT.value
                            ),
                            "waiting_for_session_since": None,
                            "session_wait_seconds": folded_wait,
                        },
                    )

            await db.commit()
            return claimed
        except Exception:
            await self._rollback()
            raise

    # --- Launch phase (outside advisory lock) -----------------------------

    async def _launch_claimed_run(
        self, claimed: ClaimedRun
    ) -> WorkflowRunModel:
        run = claimed.run
        now = _normalize_dt(self._clock()) or _utcnow()
        try:
            async with self._db_lock:
                fresh_token = (
                    await self._token_store.get_valid_token(run.user_id)
                    or claimed.token
                )
            args = build_execution_args(run, fresh_token)
            execution_id = await self._create_execution(run, args)
            entry = WorkflowRunExecution(
                execution_id=execution_id,
                started_at=now,
                state="ACTIVE",
            )
            async with self._db_lock:
                await self._run_repo.append_execution_id(
                    run.id,
                    entry.model_dump(mode="json", exclude_none=True),
                )
                await self._run_repo.db.commit()
            return run.model_copy(
                update={
                    "execution_ids": [*run.execution_ids, entry],
                }
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to start GCP execution for run %s: %s",
                run.id,
                exc,
            )
            next_retry_at = compute_next_retry_at(
                1,
                now,
                self._rng,
                base_seconds=self._retry_base_seconds,
                max_seconds=self._retry_max_seconds,
            )
            detail = sanitize_error_detail(
                f"Failed to start GCP workflow execution: {exc}"
            )
            fallback_updates: dict[str, Any] = {
                "status": WorkflowRunStatusEnum.QUEUED.value,
                "queue_reason": QueueReasonEnum.RETRY_SCHEDULED.value,
                "next_retry_at": next_retry_at,
                "attempt_count": claimed.previous_attempt_count,
                "last_error_category": ErrorCategory.TRANSIENT.value,
                "last_error_detail": detail,
            }
            async with self._db_lock:
                await self._rollback()
                try:
                    await self._run_repo.update_fields(run.id, fallback_updates)
                    await self._run_repo.db.commit()
                except Exception:  # pylint: disable=broad-exception-caught
                    await self._rollback()
                    logger.exception(
                        "Failed to re-queue run %s after create_execution error.",
                        run.id,
                    )
            return run.model_copy(
                update={
                    **fallback_updates,
                    "status": WorkflowRunStatusEnum.QUEUED,
                    "queue_reason": QueueReasonEnum.RETRY_SCHEDULED,
                    "last_error_category": ErrorCategory.TRANSIENT,
                }
            )

    def _get_executions_client(self) -> executions_v1.ExecutionsAsyncClient:
        if self._executions_client is None:
            self._executions_client = executions_v1.ExecutionsAsyncClient()
        return self._executions_client

    async def _create_execution(
        self, run: WorkflowRunModel, args: dict[str, Any]
    ) -> str:
        if self._create_execution_fn is not None:
            res = self._create_execution_fn(run, args)
            if inspect.isawaitable(res):
                res = await res
            return str(res)

        executions_client = self._get_executions_client()
        parent = (
            f"projects/{config_service.PROJECT_ID}"
            f"/locations/{config_service.WORKFLOWS_LOCATION}"
            f"/workflows/{run.workflow_id}"
        )
        execution = Execution(argument=json.dumps(args, default=str))
        response = await executions_client.create_execution(
            parent=parent, execution=execution
        )
        return response.name.split("/")[-1]

    async def _fetch_gcp_execution(
        self, run: WorkflowRunModel, execution_id: str
    ) -> tuple[str | None, Any]:
        if self._fetch_gcp_execution_fn is not None:
            res = self._fetch_gcp_execution_fn(run, execution_id)
            if inspect.isawaitable(res):
                res = await res
            return res

        try:
            executions_client = self._get_executions_client()
            name = (
                f"projects/{config_service.PROJECT_ID}"
                f"/locations/{config_service.WORKFLOWS_LOCATION}"
                f"/workflows/{run.workflow_id}"
                f"/executions/{execution_id}"
            )
            execution = await executions_client.get_execution(name=name)
            state_name = (
                execution.state.name
                if hasattr(execution.state, "name")
                else str(execution.state)
            )
            error_payload: Any = None
            if getattr(execution, "error", None):
                error_payload = {
                    "payload": getattr(execution.error, "payload", None),
                    "context": getattr(execution.error, "context", None),
                }
            return state_name, error_payload
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Could not fetch GCP execution %s for run %s.",
                execution_id,
                run.id,
                exc_info=True,
            )
            return None, None

    async def _rollback(self) -> None:
        try:
            await self._run_repo.db.rollback()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Rollback failed in WorkflowDispatcher.", exc_info=True
            )


# --- Process-wide throttled tick & post-auth hook wiring (§8.2, §8.5) -----

_last_tick_monotonic: float | None = None
_LAST_STORED_USER_TOKEN: dict[int, str] = {}


def reset_dispatch_tick_throttle() -> None:
    """Resets the per-instance dispatch tick throttle (used by tests)."""
    global _last_tick_monotonic  # pylint: disable=global-statement
    _last_tick_monotonic = None
    _LAST_STORED_USER_TOKEN.clear()


def should_run_throttled_tick(
    *,
    min_interval_seconds: float | None = None,
    monotonic_now: float | None = None,
) -> bool:
    """True when at least ``min_interval_seconds`` elapsed since the last tick."""
    global _last_tick_monotonic  # pylint: disable=global-statement
    interval = float(
        config_service.WORKFLOW_DISPATCH_TICK_MIN_INTERVAL_SECONDS
        if min_interval_seconds is None
        else min_interval_seconds
    )
    now_mono = time.monotonic() if monotonic_now is None else monotonic_now
    if (
        _last_tick_monotonic is not None
        and (now_mono - _last_tick_monotonic) < interval
    ):
        return False
    _last_tick_monotonic = now_mono
    return True


async def run_default_dispatch(
    trigger: str = "hook",
    user_id: int | None = None,
) -> list[WorkflowRunModel]:
    """Process-wide dispatch callback using a fresh ``async_session_local``."""
    async with async_session_local() as session:
        run_repo = WorkflowRunRepository(db=session)
        session_repo = WorkflowUserSessionRepository(db=session)
        token_store = TokenStoreService(repository=session_repo)
        state_service = RunStateService(repository=run_repo, dispatch_hook=None)
        dispatcher = WorkflowDispatcher(
            run_repository=run_repo,
            token_store=token_store,
            run_state_service=state_service,
        )
        return await dispatcher.dispatch(trigger=trigger, user_id=user_id)


async def handle_post_auth_session(
    user: UserModel,
    token: str,
    exp: Any,
    *,
    session_factory: Callable[[], Any] = async_session_local,
    dispatcher_factory: Callable[..., WorkflowDispatcher] | None = None,
    clock: Callable[[], datetime.datetime] | None = None,
) -> None:
    """Post-auth hook: stores encrypted ID token, unparks session-waiting runs,
    and runs a throttled dispatcher tick if due work exists (§8.2, §8.5).
    """
    if user.id is None:
        return
    raw_id_token = (token or "").strip()
    token_changed = bool(raw_id_token) and (
        _LAST_STORED_USER_TOKEN.get(user.id) != raw_id_token
    )
    run_tick = should_run_throttled_tick()
    if not token_changed and not run_tick:
        return

    now = (clock or _utcnow)()
    async with session_factory() as db:
        session_repo = WorkflowUserSessionRepository(db=db)
        token_store = TokenStoreService(repository=session_repo, clock=clock)
        run_repo = WorkflowRunRepository(db=db)

        unparked = 0
        if token_changed:
            stored = await token_store.store_token(
                user.id, raw_id_token, exp=exp, commit=False
            )
            if stored:
                unparked = await run_repo.unpark_session_waiting_runs(
                    user.id, now
                )
            await db.commit()
            if stored:
                _LAST_STORED_USER_TOKEN[user.id] = raw_id_token

        should_dispatch = unparked > 0
        if not should_dispatch and run_tick:
            should_dispatch = await run_repo.has_due_work(
                user_id=user.id, now=now
            )

        if should_dispatch:
            if dispatcher_factory is not None:
                dispatcher = dispatcher_factory(
                    run_repository=run_repo,
                    token_store=token_store,
                )
            else:
                state_service = RunStateService(
                    repository=run_repo, dispatch_hook=None, clock=clock
                )
                dispatcher = WorkflowDispatcher(
                    run_repository=run_repo,
                    token_store=token_store,
                    run_state_service=state_service,
                    clock=clock,
                )
            await dispatcher.dispatch(trigger="tick", user_id=user.id)
