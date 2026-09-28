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

"""Data access for ``workflow_runs``, incl. the step checkpoint writes."""

import dataclasses
import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import Depends
from sqlalchemy import Text, and_, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseStringRepository
from src.config.config_service import config_service
from src.database import get_db
from src.workflows.schema.workflow_model import WorkflowRunStatusEnum
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    WorkflowRun,
    WorkflowRunModel,
    WorkflowUserSession,
)


@dataclasses.dataclass(frozen=True)
class RunStepContext:
    """Run fields the step idempotency guard reads under the row lock."""

    user_id: int
    attempt_count: int
    step_states: dict[str, Any]


class WorkflowRunRepository(
    BaseStringRepository[WorkflowRun, WorkflowRunModel]
):
    """Repository for WorkflowRun."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(WorkflowRun, WorkflowRunModel, db)

    async def get_by_id(
        self,
        item_id: str,
        include_deleted: bool = False,
    ) -> WorkflowRunModel | None:
        """Retrieves a workflow run by ID, refreshing any cached identity-map entry."""
        query = (
            select(self.model)
            .where(self.model.id == item_id)
            .execution_options(
                include_deleted=include_deleted,
                populate_existing=True,
            )
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return (
            item
            if isinstance(item, WorkflowRunModel)
            else self.schema.model_validate(item)
        )

    async def lock_step_context(self, run_id: str) -> RunStepContext | None:
        """Locks the run row (``SELECT ... FOR UPDATE``) and reads it.

        Does not commit: the caller owns the transaction and must commit or
        roll back to release the lock. NULL columns get generic defaults.
        """
        result = await self.db.execute(
            select(
                WorkflowRun.user_id,
                WorkflowRun.attempt_count,
                WorkflowRun.step_states,
            )
            .where(WorkflowRun.id == run_id)
            .with_for_update(),
        )
        row = result.one_or_none()
        if row is None:
            return None
        return RunStepContext(
            user_id=row.user_id,
            attempt_count=row.attempt_count or 0,
            step_states=row.step_states or {},
        )

    async def set_step_state(
        self,
        run_id: str,
        step_id: str,
        state: dict[str, Any],
    ) -> None:
        """Atomically writes ``step_states[step_id]`` with ``jsonb_set``.

        Only that step's key changes, so writers of other steps never lose
        updates. ``state`` must be JSON-safe. Does not commit.
        """
        await self.db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(
                step_states=func.jsonb_set(
                    func.coalesce(WorkflowRun.step_states, literal({}, JSONB)),
                    literal([step_id], ARRAY(Text)),
                    literal(state, JSONB),
                    True,
                ),
            ),
        )

    async def lock_run(self, run_id: str) -> WorkflowRunModel | None:
        """Locks the run row (``SELECT ... FOR UPDATE``) and reads it fresh.

        Does not commit: the caller owns the transaction and must commit or
        roll back to release the lock.
        """
        result = await self.db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        return None if row is None else self.schema.model_validate(row)

    async def update_fields(
        self, run_id: str, values: Mapping[str, Any]
    ) -> None:
        """Partial ``UPDATE`` of the run's columns. Does not commit.

        ``values`` must be JSON-safe for JSONB columns.
        """
        await self.db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(**dict(values)),
        )

    async def try_advisory_xact_lock(self, lock_key: int) -> bool:
        """Acquires a transaction-scoped PostgreSQL advisory lock if free."""
        result = await self.db.execute(
            select(func.pg_try_advisory_xact_lock(lock_key))
        )
        return bool(result.scalar_one())

    async def count_running(self) -> int:
        """Counts runs currently occupying a global execution slot."""
        result = await self.db.execute(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.status == WorkflowRunStatusEnum.RUNNING.value)
        )
        return int(result.scalar_one() or 0)

    async def count_active_by_workflow(self, workflow_id: str) -> int:
        """Counts ``QUEUED``, ``RUNNING``, or ``STEP_FAILED`` runs for ``workflow_id`` (Q1)."""
        result = await self.db.execute(
            select(func.count())
            .select_from(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status.in_(
                    [
                        WorkflowRunStatusEnum.QUEUED.value,
                        WorkflowRunStatusEnum.RUNNING.value,
                        WorkflowRunStatusEnum.STEP_FAILED.value,
                    ]
                ),
            )
        )
        return int(result.scalar_one() or 0)

    async def has_due_work(
        self,
        *,
        user_id: int | None = None,
        now: datetime.datetime | None = None,
        max_running_workflows: int | None = None,
    ) -> bool:
        """True when there is at least one due ``QUEUED`` (with free capacity) or
        reconcilable ``RUNNING`` run.
        """
        current_now = now or datetime.datetime.now(datetime.UTC)
        cap = max_running_workflows or config_service.MAX_RUNNING_WORKFLOWS
        running_count_subq = (
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.status == WorkflowRunStatusEnum.RUNNING.value)
            .scalar_subquery()
        )
        due_clause = or_(
            WorkflowRun.next_retry_at.is_(None),
            WorkflowRun.next_retry_at <= current_now,
        )
        if user_id is not None:
            condition = or_(
                due_clause,
                (WorkflowRun.user_id == user_id)
                & (
                    WorkflowRun.queue_reason
                    == QueueReasonEnum.WAITING_FOR_SESSION.value
                ),
            )
        else:
            condition = due_clause

        due_queued = and_(
            WorkflowRun.status == WorkflowRunStatusEnum.QUEUED.value,
            condition,
            running_count_subq < cap,
        )
        reconcile_cutoff = current_now - datetime.timedelta(seconds=60)
        due_running = and_(
            WorkflowRun.status == WorkflowRunStatusEnum.RUNNING.value,
            or_(
                WorkflowRun.dispatched_at.is_(None),
                WorkflowRun.dispatched_at <= reconcile_cutoff,
            ),
        )
        stmt = (
            select(WorkflowRun.id).where(or_(due_queued, due_running)).limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def unpark_session_waiting_runs(
        self,
        user_id: int,
        now: datetime.datetime,
    ) -> int:
        """Unparks ``WAITING_FOR_SESSION`` runs for ``user_id`` when a token arrives.

        Folds ``now - waiting_for_session_since`` into ``session_wait_seconds``,
        clears ``waiting_for_session_since``, sets ``queue_reason =
        WAITING_FOR_SLOT``, and sets ``next_retry_at = now``. Does not commit.
        """
        result = await self.db.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.user_id == user_id,
                WorkflowRun.status == WorkflowRunStatusEnum.QUEUED.value,
                WorkflowRun.queue_reason
                == QueueReasonEnum.WAITING_FOR_SESSION.value,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        rows = result.scalars().all()
        count = 0
        for row in rows:
            run = self.schema.model_validate(row)
            accumulated = max(0, run.session_wait_seconds or 0)
            if run.waiting_for_session_since is not None:
                since = run.waiting_for_session_since
                if since.tzinfo is None:
                    since = since.replace(tzinfo=datetime.UTC)
                elapsed = max(0, int((now - since).total_seconds()))
                accumulated += elapsed
            await self.update_fields(
                run.id,
                {
                    "queue_reason": QueueReasonEnum.WAITING_FOR_SLOT.value,
                    "waiting_for_session_since": None,
                    "session_wait_seconds": accumulated,
                    "next_retry_at": now,
                },
            )
            count += 1
        return count

    async def lock_due_queued_runs(
        self,
        now: datetime.datetime,
        *,
        limit: int = 100,
    ) -> list[tuple[WorkflowRunModel, datetime.datetime | None]]:
        """Locks due ``QUEUED`` runs with ``FOR UPDATE OF workflow_runs SKIP LOCKED``.

        Returns ``(run, last_dispatched_at)`` pairs ordered by
        ``last_dispatched_at ASC NULLS FIRST, queued_at ASC NULLS LAST,
        started_at ASC``. Does not commit.
        """
        result = await self.db.execute(
            select(WorkflowRun, WorkflowUserSession.last_dispatched_at)
            .outerjoin(
                WorkflowUserSession,
                WorkflowUserSession.user_id == WorkflowRun.user_id,
            )
            .where(
                WorkflowRun.status == WorkflowRunStatusEnum.QUEUED.value,
                or_(
                    WorkflowRun.next_retry_at.is_(None),
                    WorkflowRun.next_retry_at <= now,
                ),
            )
            .order_by(
                WorkflowUserSession.last_dispatched_at.asc().nulls_first(),
                WorkflowRun.queued_at.asc().nulls_last(),
                WorkflowRun.started_at.asc(),
            )
            .limit(limit)
            .with_for_update(of=WorkflowRun, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        items: list[tuple[WorkflowRunModel, datetime.datetime | None]] = []
        for row in result.all():
            run_obj, last_dispatched_at = row[0], row[1]
            run_model = (
                run_obj
                if isinstance(run_obj, WorkflowRunModel)
                else self.schema.model_validate(run_obj)
            )
            items.append((run_model, last_dispatched_at))
        return items

    async def find_active_for_reconciliation(
        self,
        *,
        limit: int = 50,
    ) -> list[WorkflowRunModel]:
        """Returns active or session-waiting runs for reconciler inspection (§8.4)."""
        result = await self.db.execute(
            select(WorkflowRun)
            .where(
                or_(
                    WorkflowRun.status.in_(
                        [
                            WorkflowRunStatusEnum.RUNNING.value,
                            WorkflowRunStatusEnum.STEP_FAILED.value,
                        ]
                    ),
                    (WorkflowRun.status == WorkflowRunStatusEnum.QUEUED.value)
                    & (
                        WorkflowRun.queue_reason
                        == QueueReasonEnum.WAITING_FOR_SESSION.value
                    ),
                )
            )
            .order_by(WorkflowRun.started_at.asc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return [
            (
                item
                if isinstance(item, WorkflowRunModel)
                else self.schema.model_validate(item)
            )
            for item in result.scalars().all()
        ]

    async def append_execution_id(
        self,
        run_id: str,
        execution_entry: Mapping[str, Any],
    ) -> None:
        """Appends an entry to ``execution_ids`` JSONB array. Does not commit."""
        await self.db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(
                execution_ids=func.coalesce(
                    WorkflowRun.execution_ids, literal([], JSONB)
                ).op("||")(literal([dict(execution_entry)], JSONB)),
            )
        )

    async def list_by_workflow(
        self,
        workflow_id: str,
        *,
        user_id: int,
        status: WorkflowRunStatusEnum | str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[WorkflowRunModel], int]:
        """Lists DB runs for ``workflow_id`` owned by ``user_id`` (spec §9.2)."""
        filters = [
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.user_id == user_id,
        ]
        if status is not None:
            status_val = (
                status.value
                if isinstance(status, WorkflowRunStatusEnum)
                else str(status)
            )
            filters.append(WorkflowRun.status == status_val)

        count_res = await self.db.execute(
            select(func.count()).select_from(WorkflowRun).where(*filters)
        )
        total = int(count_res.scalar_one() or 0)

        rows_res = await self.db.execute(
            select(WorkflowRun)
            .where(*filters)
            .order_by(
                func.coalesce(
                    WorkflowRun.queued_at, WorkflowRun.started_at
                ).desc(),
                WorkflowRun.started_at.desc(),
            )
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        items = [
            (
                row
                if isinstance(row, WorkflowRunModel)
                else self.schema.model_validate(row)
            )
            for row in rows_res.scalars().all()
        ]
        return items, total

    async def compute_queue_positions(
        self,
        run_ids: Sequence[str],
    ) -> dict[str, int]:
        """Returns 1-based global queue positions for ``run_ids`` that are ``QUEUED``."""
        wanted = set(run_ids)
        if not wanted:
            return {}
        result = await self.db.execute(
            select(WorkflowRun.id)
            .where(WorkflowRun.status == WorkflowRunStatusEnum.QUEUED.value)
            .order_by(
                func.coalesce(
                    WorkflowRun.queued_at, WorkflowRun.started_at
                ).asc(),
                WorkflowRun.id.asc(),
            )
        )
        positions: dict[str, int] = {}
        for index, queued_id in enumerate(result.scalars().all(), start=1):
            if queued_id in wanted:
                positions[queued_id] = index
        return positions

    claim_dispatchable = lock_due_queued_runs
    find_stale_running = find_active_for_reconciliation
