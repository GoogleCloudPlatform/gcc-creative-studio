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

"""DTOs for workflow run callbacks, checkpoint fetches and run queries."""

import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.base_dto import BaseDto
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.schema.workflow_model import WorkflowRunStatusEnum
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepState,
    WorkflowRunExecution,
)

RUN_KEY_PATTERN = r"^[A-Za-z0-9_-]+$"
OPTIONAL_KEY_PATTERN = r"^[A-Za-z0-9_-]*$"
KEY_MAX_LENGTH = 128


class ExecutionCallbackStatusEnum(str, Enum):
    """Terminal GCP execution outcomes sent to ``/runs/{run_id}/finished``."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    # Internal Domain & gRPC Convention uses the single-L spelling.
    CANCELED = "CANCELED"


class RunFinishedCallbackDto(BaseModel):
    """Payload posted by the generated YAML when an execution ends."""

    execution_id: str = Field(
        min_length=1, max_length=KEY_MAX_LENGTH, pattern=RUN_KEY_PATTERN
    )
    status: ExecutionCallbackStatusEnum
    step_id: str | None = Field(
        default=None, max_length=KEY_MAX_LENGTH, pattern=OPTIONAL_KEY_PATTERN
    )
    error: Any = None


class RunFinishedResponseDto(BaseModel):
    """Response of ``POST /api/workflows-executor/runs/{run_id}/finished``."""

    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    status: WorkflowRunStatusEnum
    applied: bool = True
    queue_reason: QueueReasonEnum | None = None
    last_error_category: ErrorCategory | None = None


class RunCheckpointResponseDto(BaseModel):
    """Response of ``GET /api/workflows-executor/runs/{run_id}/checkpoint``."""

    run_id: str
    prior_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ResumeRunRequestDto(BaseDto):
    """Request body for ``POST /api/workflows/{workflow_id}/runs/{run_id}/resume``."""

    args_override: dict[str, Any] | None = None


class WorkflowRunSummaryDto(BaseDto):
    """Summary of a workflow run for Execution History listings."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        populate_by_name=True,
        alias_generator=BaseDto.model_config["alias_generator"],
    )

    id: str
    workflow_id: str
    user_id: int
    workspace_id: int | None = None
    status: WorkflowRunStatusEnum
    started_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    queued_at: datetime.datetime | None = None
    dispatched_at: datetime.datetime | None = None
    queue_reason: QueueReasonEnum | None = None
    current_step_id: str | None = None
    attempt_count: int = 0
    next_retry_at: datetime.datetime | None = None
    last_error_category: ErrorCategory | None = None
    last_error_detail: str | None = None
    queue_position: int | None = None


class WorkflowRunDetailDto(WorkflowRunSummaryDto):
    """Full details of a workflow run, including step states and snapshot."""

    input_args: dict[str, Any] = Field(default_factory=dict)
    workflow_snapshot: dict[str, Any] = Field(default_factory=dict)
    step_states: dict[str, StepState] = Field(default_factory=dict)
    step_entries: list[dict[str, Any]] = Field(default_factory=list)
    execution_ids: list[WorkflowRunExecution] = Field(default_factory=list)
    waiting_for_session_since: datetime.datetime | None = None
    session_wait_seconds: int = 0
    canceled_by_user: bool | None = None
