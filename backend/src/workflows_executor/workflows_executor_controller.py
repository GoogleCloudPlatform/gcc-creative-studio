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

"""Routes called by the generated workflow YAML to run individual steps."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query

from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.workflows.dto.workflow_run_dto import (
    KEY_MAX_LENGTH,
    OPTIONAL_KEY_PATTERN,
    RUN_KEY_PATTERN,
    RunCheckpointResponseDto,
    RunFinishedCallbackDto,
    RunFinishedResponseDto,
)
from src.workflows.queue.run_state_service import (
    RunStateService,
    get_run_state_service,
)
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateAudioRequest,
    GenerateTextRequest,
    GenerateVideoRequest,
    ImageStepRequest,
)
from src.workflows_executor.idempotency import StepIdempotencyGuard
from src.workflows_executor.step_errors import StructuredErrorRoute
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)

# Every error is answered as {"error_category", "detail"}.
router = APIRouter(
    prefix="/api/workflows-executor",
    tags=["Workflows Executor"],
    responses={404: {"description": "Not found"}},
    route_class=StructuredErrorRoute,
)


@router.post("/generate_text")
async def generate_text(
    request: GenerateTextRequest,
    authorization: Annotated[str | None, Header()] = None,
    current_user: UserModel = Depends(get_current_user),
    run_repository: WorkflowRunRepository = Depends(),
    service: WorkflowsExecutorService = Depends(),
):
    guard = StepIdempotencyGuard.from_request(
        request, current_user.id, run_repository
    )
    return await service.generate_text(request, authorization, guard=guard)


@router.post("/image")
async def execute_image(
    request: ImageStepRequest,
    authorization: Annotated[str | None, Header()] = None,
    current_user: UserModel = Depends(get_current_user),
    run_repository: WorkflowRunRepository = Depends(),
    service: WorkflowsExecutorService = Depends(),
):
    guard = StepIdempotencyGuard.from_request(
        request, current_user.id, run_repository
    )
    return await service.execute_image(request, authorization, guard=guard)


@router.post("/generate_video")
async def generate_video(
    request: GenerateVideoRequest,
    authorization: Annotated[str | None, Header()] = None,
    current_user: UserModel = Depends(get_current_user),
    run_repository: WorkflowRunRepository = Depends(),
    service: WorkflowsExecutorService = Depends(),
):
    guard = StepIdempotencyGuard.from_request(
        request, current_user.id, run_repository
    )
    return await service.generate_video(request, authorization, guard=guard)


@router.post("/generate_audio")
async def generate_audio(
    request: GenerateAudioRequest,
    authorization: Annotated[str | None, Header()] = None,
    current_user: UserModel = Depends(get_current_user),
    run_repository: WorkflowRunRepository = Depends(),
    service: WorkflowsExecutorService = Depends(),
):
    guard = StepIdempotencyGuard.from_request(
        request, current_user.id, run_repository
    )
    return await service.generate_audio(request, authorization, guard=guard)


@router.get(
    "/runs/{run_id}/checkpoint", response_model=RunCheckpointResponseDto
)
async def get_run_checkpoint(
    run_id: Annotated[
        str,
        Path(min_length=1, max_length=KEY_MAX_LENGTH, pattern=RUN_KEY_PATTERN),
    ],
    execution_id: Annotated[
        str | None,
        Query(max_length=KEY_MAX_LENGTH, pattern=OPTIONAL_KEY_PATTERN),
    ] = None,
    current_user: UserModel = Depends(get_current_user),
    run_state_service: RunStateService = Depends(get_run_state_service),
):
    prior_outputs = await run_state_service.get_checkpoint(
        run_id, user_id=current_user.id, execution_id=execution_id
    )
    return RunCheckpointResponseDto(run_id=run_id, prior_outputs=prior_outputs)


@router.post("/runs/{run_id}/finished", response_model=RunFinishedResponseDto)
async def finish_run(
    run_id: Annotated[
        str,
        Path(min_length=1, max_length=KEY_MAX_LENGTH, pattern=RUN_KEY_PATTERN),
    ],
    request: RunFinishedCallbackDto,
    current_user: UserModel = Depends(get_current_user),
    run_state_service: RunStateService = Depends(get_run_state_service),
):
    run = await run_state_service.on_finished(
        run_id, request, user_id=current_user.id
    )
    return RunFinishedResponseDto(
        run_id=run.id,
        status=run.status,
        queue_reason=run.queue_reason,
        last_error_category=run.last_error_category,
    )
