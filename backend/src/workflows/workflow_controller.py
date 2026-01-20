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

from fastapi import APIRouter, Depends, HTTPException, Response, status, Header

from src.auth.auth_guard import RoleChecker, get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.dto.workflow_search_dto import WorkflowSearchDto
from src.workflows.schema.workflow_model import WorkflowCreateDto, WorkflowModel, WorkflowExecuteDto
from src.workflows.workflow_service import WorkflowService
from src.workspaces.workspace_auth_guard import workspace_auth_service

router = APIRouter(
    prefix="/api/workflows",
    tags=["Workflows"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[
                    UserRoleEnum.ADMIN,
                ]
            )
        )
    ],
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


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow_data: WorkflowCreateDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Creates a new workflow definition."""
    created_workflow = await workflow_service.create_workflow(
        workflow_data, current_user
    )

    return created_workflow


@router.put("/{workflow_id}", response_model=WorkflowModel)
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowCreateDto,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Updates an existing workflow definition."""
    # 1. Fetch the existing workflow first to ensure it exists.
    existing_workflow = await workflow_service.get_by_id(workflow_id)
    if not existing_workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow with ID '{workflow_id}' not found.",
        )

    # 2. Verify that the workflow belongs to the user or handle auth as needed.
    # (Since it's shared across workspaces, we use user-level auth)
    if existing_workflow.user_id != current_user.id:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this workflow.",
        )

    # 4. Pass the DTO to the service to handle the update logic.
    # Service update_workflow returns the coroutine from repo.update_workflow, so we await it.
    return await workflow_service.update_workflow(
        workflow_id, workflow_data, current_user
    )


@router.get("/{workflow_id}", response_model=WorkflowModel)
async def get_workflow(
    workflow_id,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    try:
        workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
        if workflow:
            return workflow
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response(
            content=str(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
    """
    Permanently deletes a workflow from the database.
    This functionality is restricted to owners of the workflow.
    """
    workflow = await workflow_service.get_workflow(
        current_user.id, workflow_id  # type: ignore
    )

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not await workflow_service.delete_by_id(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    return

@router.post("/{workflow_id}/workflow-execute")
async def execute_workflow(
    workflow_id: str,
    workflow_execute_dto: WorkflowExecuteDto,
    authorization: str | None = Header(default=None),
    workflow_service: WorkflowService = Depends(),
):
    """
    This function is the controller that calls the service to generate the workflow.
    """
    workflow_execute_dto.args["user_auth_header"] = authorization

    response = workflow_service.execute_workflow(
        workflow_id=workflow_id, args=workflow_execute_dto.args
    )
    print(f"Created execution: {response}")
    return {"execution_id": response}


@router.get("/{workflow_id}/executions/{execution_id}")
async def get_execution(
    workflow_id: str,
    execution_id: str,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Retrieves the details of a workflow execution."""
    # We might want to authorize against the workspace of the workflow here
    # But for now let's just check if the user has access to the workflow
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    execution = await workflow_service.get_execution_details(workflow_id, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return execution


@router.get("/{workflow_id}/executions")
async def list_executions(
    workflow_id: str,
    limit: int = 10,
    page_token: str = None,
    status: str = None,
    current_user: UserModel = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(),
):
    """Lists executions for a workflow."""
    # Check access
    workflow = await workflow_service.get_workflow(current_user.id, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    filter_str = None
    if status and status != "ALL":
        filter_str = f'state="{status}"'

    return workflow_service.list_executions(
        workflow_id=workflow_id, limit=limit, page_token=page_token, filter_str=filter_str
    )