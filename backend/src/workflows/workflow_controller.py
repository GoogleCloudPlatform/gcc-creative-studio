# Copyright 2025 Google LLC
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

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from fastapi.responses import JSONResponse

from src.auth.auth_guard import RoleChecker, get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.dto.batch_execution_dto import (
    BatchExecutionRequestDto,
    BatchExecutionResponseDto,
)
from src.workflows.dto.workflow_run_dto import (
    KEY_MAX_LENGTH,
    RUN_KEY_PATTERN,
    ResumeRunRequestDto,
    WorkflowRunDetailDto,
    WorkflowRunSummaryDto,
)
from src.workflows.dto.workflow_search_dto import WorkflowSearchDto
from src.workflows.queue.run_state_service import MissingResumeInputsError
from src.workflows.schema.workflow_model import (
    WorkflowCreateDto,
    WorkflowExecuteDto,
    WorkflowModel,
    WorkflowRunStatusEnum,
    WorkflowValidateDto,
    WorkflowValidationResponseDto,
)
from src.workflows.schema.workflow_run_model import QueueReasonEnum
from src.workflows.schema.workflow_template_model import (
    WorkflowTemplateCreateDto,
    WorkflowTemplateModel,
)
from src.workflows.workflow_service import (
    WorkflowConflictError,
    WorkflowService,
)
from src.workflows_executor.step_errors import StepError

router = APIRouter(
    prefix="/api/workflows",
    tags=["Workflows"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRoleEnum.USER,
                ]
            )
        )
    ],
)


@router.get("/templates", response_model=list[WorkflowTemplateModel])
async def list_templates(
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Lists all workflow templates created by the current user."""
    return await workflow_service.list_templates(user_id=current_user.id)


@router.post(
    "/templates",
    response_model=WorkflowTemplateModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    template_data: WorkflowTemplateCreateDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Creates a new workflow template."""
    try:
        return await workflow_service.create_template(
            template_data,
            current_user,
        )
    except ValueError as e:
        status_code = (
            status.HTTP_409_CONFLICT
            if "already exists" in str(e).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(e),
        )


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(
    template_id: str,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Deletes a workflow template created by the current user."""
    deleted = await workflow_service.delete_template(
        user_id=current_user.id,
        template_id=template_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template with ID '{template_id}' not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/validate",
    response_model=WorkflowValidationResponseDto,
    status_code=status.HTTP_200_OK,
)
async def validate_workflow(
    workflow_data: WorkflowValidateDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Validates a workflow structure without saving or deploying it."""
    try:
        return workflow_service.validate_workflow(
            workflow_data,
            current_user,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/search", response_model=PaginationResponseDto[WorkflowModel])
async def search_workflows(
    search_params: WorkflowSearchDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Lists all workflows for the current user."""
    return await workflow_service.query_workflows(
        user_id=current_user.id,
        search_dto=search_params,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    workflow_data: WorkflowCreateDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Creates a new workflow definition."""
    try:
        created_workflow = await workflow_service.create_workflow(
            workflow_data,
            current_user,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    return created_workflow


@router.put(
    "/{workflow_id}",
    response_model=WorkflowModel,
)
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowCreateDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Updates an existing workflow definition."""
    existing_workflow = await workflow_service.get_by_id(workflow_id)
    if not existing_workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow with ID '{workflow_id}' not found.",
        )

    if existing_workflow.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this workflow.",
        )

    try:
        return await workflow_service.update_workflow(
            workflow_id,
            workflow_data,
            current_user,
        )
    except WorkflowConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.get("/{workflow_id}", response_model=WorkflowModel)
async def get_workflow(
    workflow_id,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    try:
        workflow = await workflow_service.get_workflow(
            current_user.id, workflow_id
        )
        if workflow:
            return workflow
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response(
            content=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a Workflow",
)
async def delete_workflow(
    workflow_id: str,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Permanently deletes a workflow from the database.
    This functionality is restricted to owners of the workflow.
    """
    workflow = await workflow_service.get_workflow(
        current_user.id,
        workflow_id,  # type: ignore
    )

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        deleted = await workflow_service.delete_by_id(workflow_id)
    except WorkflowConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e

    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")


@router.post("/{workflow_id}/workflow-execute")
async def execute_workflow(
    workflow_id: str,
    workflow_execute_dto: WorkflowExecuteDto,
    authorization: str | None = Header(default=None),
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Submits a workflow run to the queue without persisting user_auth_header."""
    del authorization  # Token is stored via post-auth hook, never persisted in args.
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    cleaned_args = dict(workflow_execute_dto.args or {})
    cleaned_args.pop("user_auth_header", None)

    response = await workflow_service.execute_workflow(
        workflow_id=workflow_id,
        args=cleaned_args,
        user=current_user,
    )
    if isinstance(response, str):
        return {
            "run_id": response,
            "execution_id": response,
            "status": WorkflowRunStatusEnum.QUEUED.value,
            "queue_reason": QueueReasonEnum.WAITING_FOR_SLOT.value,
        }
    run_id = getattr(response, "id", None) or str(response)
    run_status = getattr(response, "status", WorkflowRunStatusEnum.QUEUED)
    status_val = (
        run_status.value if hasattr(run_status, "value") else str(run_status)
    )
    q_reason = getattr(response, "queue_reason", None)
    reason_val = (
        q_reason.value
        if hasattr(q_reason, "value")
        else (str(q_reason) if q_reason is not None else None)
    )
    return {
        "run_id": run_id,
        "execution_id": run_id,
        "status": status_val,
        "queue_reason": reason_val,
    }


@router.post(
    "/{workflow_id}/batch-execute", response_model=BatchExecutionResponseDto
)
async def batch_execute_workflow(
    workflow_id: str,
    batch_dto: BatchExecutionRequestDto,
    authorization: str | None = Header(default=None),
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
    _: None = Depends(
        RoleChecker([UserRoleEnum.WORKFLOWS, UserRoleEnum.ADMIN])
    ),
):
    """Queues a batch of workflow runs without persisting user_auth_header."""
    del authorization  # Token is stored via post-auth hook, never persisted in args.
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    for item in batch_dto.items:
        item.args.pop("user_auth_header", None)

    return await workflow_service.batch_execute_workflow(
        workflow_id=workflow_id,
        batch_dto=batch_dto,
        user=current_user,
    )


@router.get(
    "/{workflow_id}/runs",
    response_model=PaginationResponseDto[WorkflowRunSummaryDto],
)
async def list_runs(
    workflow_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: WorkflowRunStatusEnum | None = Query(
        default=None, alias="status"
    ),
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Lists workflow runs for ``workflow_id`` from PostgreSQL (DB-only)."""
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return await workflow_service.list_runs(
        workflow_id=workflow_id,
        user_id=current_user.id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{workflow_id}/runs/{run_id}",
    response_model=WorkflowRunDetailDto,
)
async def get_run(
    workflow_id: str,
    run_id: str = Path(
        min_length=1, max_length=KEY_MAX_LENGTH, pattern=RUN_KEY_PATTERN
    ),
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Retrieves full DB-backed details of a workflow run (no GCP calls)."""
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_details = await workflow_service.get_run_details(
        workflow_id=workflow_id,
        run_id=run_id,
        user_id=current_user.id,
    )
    if not run_details:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run_details


@router.post("/{workflow_id}/runs/{run_id}/resume")
async def resume_run(
    workflow_id: str,
    run_id: str = Path(
        min_length=1, max_length=KEY_MAX_LENGTH, pattern=RUN_KEY_PATTERN
    ),
    payload: ResumeRunRequestDto | None = Body(default=None),
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Resumes a paused or session-waiting workflow run (owner-only)."""
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        resumed = await workflow_service.resume_run(
            workflow_id=workflow_id,
            run_id=run_id,
            user=current_user,
            args_override=payload.args_override if payload else None,
        )
    except MissingResumeInputsError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": {
                    "message": str(e.detail),
                    "missing_inputs": e.missing_inputs,
                },
                "missing_inputs": e.missing_inputs,
            },
        )
    except StepError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    run_status = getattr(resumed, "status", WorkflowRunStatusEnum.QUEUED)
    q_reason = getattr(
        resumed, "queue_reason", QueueReasonEnum.RESUME_REQUESTED
    )
    resolved_id = getattr(resumed, "id", run_id)
    return {
        "id": resolved_id,
        "run_id": resolved_id,
        "status": (
            run_status.value
            if hasattr(run_status, "value")
            else str(run_status)
        ),
        "queue_reason": (
            q_reason.value
            if hasattr(q_reason, "value")
            else (str(q_reason) if q_reason is not None else None)
        ),
    }


@router.post("/{workflow_id}/runs/{run_id}/cancel")
async def cancel_run(
    workflow_id: str,
    run_id: str = Path(
        min_length=1, max_length=KEY_MAX_LENGTH, pattern=RUN_KEY_PATTERN
    ),
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Cancels a queued, running, or paused workflow run (owner-only, §9.1, §10)."""
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        canceled = await workflow_service.cancel_run(
            workflow_id=workflow_id,
            run_id=run_id,
            user=current_user,
        )
    except StepError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    run_status = getattr(canceled, "status", WorkflowRunStatusEnum.CANCELED)
    resolved_id = getattr(canceled, "id", run_id)
    return {
        "id": resolved_id,
        "run_id": resolved_id,
        "status": (
            run_status.value
            if hasattr(run_status, "value")
            else str(run_status)
        ),
        "canceled_by_user": bool(getattr(canceled, "canceled_by_user", True)),
    }
