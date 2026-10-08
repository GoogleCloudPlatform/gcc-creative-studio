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

import datetime
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseStringDocument
from src.database import Base
from src.workflows.schema.workflow_model import (
    StepStatusEnum,
    WorkflowRunStatusEnum,
)


class QueueReasonEnum(str, Enum):
    """Why a ``QUEUED`` run is waiting."""

    WAITING_FOR_SLOT = "WAITING_FOR_SLOT"
    WAITING_FOR_SESSION = "WAITING_FOR_SESSION"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    # A long generation job is still running (continuation).
    STEP_IN_PROGRESS = "STEP_IN_PROGRESS"
    RESUME_REQUESTED = "RESUME_REQUESTED"


from src.workflows.queue.failure_classifier import (  # noqa: E402  # pylint: disable=wrong-import-position
    ErrorCategory,
)


class WorkflowRun(Base):
    """SQLAlchemy model for the 'workflow_runs' table.
    Stores the execution history and the snapshot of the workflow definition.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index(
            "ix_workflow_runs_status_next_retry_at", "status", "next_retry_at"
        ),
        Index("ix_workflow_runs_user_id_status", "user_id", "status"),
        Index(
            "ix_workflow_runs_workflow_id_queued_at",
            "workflow_id",
            text("queued_at DESC"),
        ),
        Index("ix_workflow_runs_workflow_id_status", "workflow_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[int] = mapped_column(
        nullable=True,
    )  # Denormalized if needed, or linked to workspace table? Keeping generic int for now.

    status: Mapped[str] = mapped_column(
        String,
        default=WorkflowRunStatusEnum.RUNNING.value,
        nullable=False,
    )

    workflow_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )

    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --- Queue / checkpoint columns ---
    # All nullable: rows created before these columns existed keep NULL and
    # WorkflowRunModel maps NULL to generic defaults ({} / [] / 0).
    # User args as submitted; never contains the user's token.
    input_args: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # SHA-256 of the snapshot steps; NULL => treated as "changed".
    definition_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    queued_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queue_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    waiting_for_session_since: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Excluded from the run-age cap.
    session_wait_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, server_default=text("0")
    )
    current_step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Number of GCP executions started for this run.
    attempt_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, server_default=text("0")
    )
    next_retry_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_category: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    # Sanitised and truncated; never contains tokens.
    last_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"execution_id", "started_at", "ended_at", "state"}, ...]
    execution_ids: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    # {step_id: StepState}; written per step with jsonb_set.
    step_states: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    canceled_by_user: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )


class StepErrorInfo(BaseModel):
    """Last error of a step. ``detail`` is sanitised (no tokens)."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    category: ErrorCategory | None = None
    http_status: int | None = None
    detail: str | None = None


class StepState(BaseModel):
    """Checkpoint of one step inside ``workflow_runs.step_states``."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    status: StepStatusEnum = StepStatusEnum.PENDING
    # Concrete inputs resolved at execution time (None for legacy rows).
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    # Counts failures only; in-progress continuations are counted apart.
    attempts: int = 0
    in_progress_continuations: int = 0
    job_id: int | None = None
    # Run attempt_count when job_id was created: a failed job is only
    # regenerated once the dispatcher has started a new attempt.
    run_attempt: int | None = None
    # Executor call that is creating the job (guards concurrent calls).
    claim_id: str | None = None
    execution_id: str | None = None
    definition_hash: str | None = None
    started_at: datetime.datetime | None = None
    # Creation time of job_id; anchors WORKFLOW_MAX_STEP_DURATION_SECONDS.
    first_started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None
    error: StepErrorInfo | None = None

    @field_validator("attempts", "in_progress_continuations", mode="before")
    @classmethod
    def _null_counter_to_zero(cls, value: Any) -> Any:
        return 0 if value is None else value

    def to_json(self) -> dict[str, Any]:
        """JSON-safe dict for the JSONB column (NULL fields omitted)."""
        return self.model_dump(mode="json", exclude_none=True)


class WorkflowRunExecution(BaseModel):
    """A GCP execution started for a run (``execution_ids`` entry)."""

    model_config = ConfigDict(extra="allow")

    execution_id: str
    started_at: datetime.datetime | None = None
    ended_at: datetime.datetime | None = None
    state: str | None = None


class WorkflowRunModel(BaseStringDocument):
    """Pydantic model for Workflow Execution, including the snapshot.

    The queue / checkpoint columns are nullable; NULL gets a generic default
    (``{}`` / ``[]`` / ``0``) so every run follows the same code path.
    """

    workflow_id: str
    user_id: int
    workspace_id: int | None = None
    status: WorkflowRunStatusEnum = Field(default=WorkflowRunStatusEnum.RUNNING)
    started_at: datetime.datetime
    completed_at: datetime.datetime | None = None

    workflow_snapshot: dict[str, Any]

    # --- Queue / checkpoint ---
    input_args: dict[str, Any] = Field(default_factory=dict)
    definition_hash: str | None = None
    queued_at: datetime.datetime | None = None
    dispatched_at: datetime.datetime | None = None
    queue_reason: QueueReasonEnum | None = None
    waiting_for_session_since: datetime.datetime | None = None
    session_wait_seconds: int = 0
    current_step_id: str | None = None
    attempt_count: int = 0
    next_retry_at: datetime.datetime | None = None
    last_error_category: ErrorCategory | None = None
    last_error_detail: str | None = None
    execution_ids: list[WorkflowRunExecution] = Field(default_factory=list)
    step_states: dict[str, StepState] = Field(default_factory=dict)
    canceled_by_user: bool | None = None

    @field_validator("input_args", "step_states", mode="before")
    @classmethod
    def _null_to_empty_dict(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("execution_ids", mode="before")
    @classmethod
    def _null_to_empty_list(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("session_wait_seconds", "attempt_count", mode="before")
    @classmethod
    def _null_to_zero(cls, value: Any) -> Any:
        return 0 if value is None else value

    # The two JSONB structures dump JSON-safe values in every mode because
    # repositories write model_dump() output straight into JSONB columns.
    @field_serializer("execution_ids")
    def _serialize_execution_ids(
        self, value: list[WorkflowRunExecution]
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json", exclude_none=True) for item in value
        ]

    @field_serializer("step_states")
    def _serialize_step_states(
        self, value: dict[str, StepState]
    ) -> dict[str, Any]:
        return {step_id: state.to_json() for step_id, state in value.items()}


class WorkflowUserSession(Base):
    """SQLAlchemy model for the ``workflow_user_sessions`` table."""

    __tablename__ = "workflow_user_sessions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_dispatched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkflowUserSessionModel(BaseModel):
    """Pydantic representation of a ``workflow_user_sessions`` row."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    encrypted_token: str | None = None
    token_expires_at: datetime.datetime
    updated_at: datetime.datetime | None = None
    last_dispatched_at: datetime.datetime | None = None
