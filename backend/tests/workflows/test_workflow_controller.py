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
"""Tests for Workflow Controller."""

import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.auth.auth_guard import get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.dto.workflow_run_dto import (
    WorkflowRunDetailDto,
    WorkflowRunSummaryDto,
)
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.queue.run_state_service import MissingResumeInputsError
from src.workflows.schema.workflow_model import WorkflowRunStatusEnum
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    WorkflowRunModel,
)
from src.workflows.workflow_controller import router
from src.workflows.workflow_service import (
    WorkflowConflictError,
    WorkflowService,
)
from src.workflows_executor.step_errors import StepError

FIXED_NOW = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1,
        email="test@example.com",
        name="Test User",
        roles=[UserRoleEnum.USER, UserRoleEnum.WORKFLOWS],
    )


@pytest.fixture(name="mock_service")
def fixture_mock_service():
    service = AsyncMock()
    service.query_workflows = AsyncMock()
    service.create_workflow = AsyncMock()
    service.get_by_id = AsyncMock()
    service.update_workflow = AsyncMock()
    service.get_workflow = AsyncMock()
    service.delete_by_id = AsyncMock()
    service.execute_workflow = AsyncMock()
    service.batch_execute_workflow = AsyncMock()
    service.get_run_details = AsyncMock()
    service.list_runs = AsyncMock()
    service.resume_run = AsyncMock()
    service.cancel_run = AsyncMock()
    service.validate_workflow = MagicMock()
    return service


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_service):
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[WorkflowService] = lambda: mock_service

    return TestClient(app)


def _sample_run_model(
    run_id: str = "run-123",
    status: WorkflowRunStatusEnum = WorkflowRunStatusEnum.QUEUED,
) -> WorkflowRunModel:
    return WorkflowRunModel(
        id=run_id,
        workflow_id="wf1",
        user_id=1,
        workspace_id=1,
        status=status,
        started_at=FIXED_NOW,
        queued_at=FIXED_NOW,
        queue_reason=QueueReasonEnum.WAITING_FOR_SLOT,
        workflow_snapshot={"name": "WF", "steps": []},
        input_args={"workspace_id": 1},
    )


def test_search_workflows_success(client, mock_service):
    from src.common.dto.pagination_response_dto import PaginationResponseDto

    mock_item = {"id": "wf1", "name": "WF", "user_id": 1, "steps": []}
    mock_response = PaginationResponseDto(
        count=1,
        data=[mock_item],
        page=1,
        page_size=10,
        total_pages=1,
    )
    mock_service.query_workflows.return_value = mock_response

    payload = {"limit": 10, "offset": 0}
    response = client.post("/api/workflows/search", json=payload)

    assert response.status_code == 200
    mock_service.query_workflows.assert_called_once()


def test_create_workflow_success(client, mock_service):
    mock_workflow = {"id": "wf1", "name": "WF", "steps": []}
    mock_service.create_workflow.return_value = mock_workflow

    payload = {"name": "New Workflow", "steps": []}
    response = client.post("/api/workflows", json=payload)

    assert response.status_code == 201
    mock_service.create_workflow.assert_called_once()


def test_get_workflow_success(client, mock_service):
    mock_workflow = {"id": "wf1", "name": "WF", "user_id": 1, "steps": []}
    mock_service.get_workflow.return_value = mock_workflow

    response = client.get("/api/workflows/wf1")

    assert response.status_code == 200
    assert response.json()["id"] == "wf1"


def test_get_workflow_not_found(client, mock_service):
    mock_service.get_workflow.return_value = None

    response = client.get("/api/workflows/absent")

    assert response.status_code == 404


def test_execute_workflow_success_returns_run_summary(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.execute_workflow.return_value = _sample_run_model("run_id_123")

    payload = {"args": {"param1": "val1"}}
    response = client.post("/api/workflows/wf1/workflow-execute", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run_id_123"
    assert body["execution_id"] == "run_id_123"
    assert body["status"] == "queued"
    assert body["queue_reason"] == "WAITING_FOR_SLOT"


def test_execute_workflow_unauthorized(client, mock_service):
    mock_service.get_workflow.return_value = None

    payload = {"args": {"param1": "val1"}}
    response = client.post("/api/workflows/wf1/workflow-execute", json=payload)

    assert response.status_code == 404
    mock_service.execute_workflow.assert_not_called()


def test_update_workflow_success_and_409_conflict(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_by_id.return_value = mock_workflow

    mock_updated = {"id": "wf1", "name": "Updated", "steps": [], "user_id": 1}
    mock_service.update_workflow.return_value = mock_updated

    payload = {"name": "Updated", "steps": []}
    response = client.put("/api/workflows/wf1", json=payload)

    assert response.status_code == 200
    assert response.json()["name"] == "Updated"

    # 409 when active runs exist
    mock_service.update_workflow.side_effect = WorkflowConflictError(
        "Cannot edit workflow 'wf1' while 2 run(s) are active"
    )
    conflict_resp = client.put("/api/workflows/wf1", json=payload)
    assert conflict_resp.status_code == 409
    assert "active" in conflict_resp.json()["detail"]


def test_delete_workflow_success_and_409_conflict(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.delete_by_id.return_value = True

    response = client.delete("/api/workflows/wf1")
    assert response.status_code == 204

    mock_service.delete_by_id.side_effect = WorkflowConflictError(
        "Cannot delete workflow 'wf1' while 1 run(s) are active"
    )
    conflict_resp = client.delete("/api/workflows/wf1")
    assert conflict_resp.status_code == 409
    assert "active" in conflict_resp.json()["detail"]


def test_list_runs_and_get_run_details(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow

    run_summary = WorkflowRunSummaryDto(
        id="run-1",
        workflow_id="wf1",
        user_id=1,
        status=WorkflowRunStatusEnum.QUEUED,
        started_at=FIXED_NOW,
        queued_at=FIXED_NOW,
        queue_reason=QueueReasonEnum.WAITING_FOR_SLOT,
        queue_position=1,
    )
    mock_service.list_runs.return_value = PaginationResponseDto(
        count=1,
        data=[run_summary],
        page=1,
        page_size=20,
        total_pages=1,
    )

    list_resp = client.get("/api/workflows/wf1/runs")
    assert list_resp.status_code == 200
    assert list_resp.json()["data"][0]["id"] == "run-1"
    assert list_resp.json()["data"][0]["queuePosition"] == 1

    mock_service.get_run_details.return_value = WorkflowRunDetailDto(
        id="run-1",
        workflow_id="wf1",
        user_id=1,
        status=WorkflowRunStatusEnum.RUNNING,
        started_at=FIXED_NOW,
        step_entries=[{"step_id": "step_a", "state": "STATE_IN_PROGRESS"}],
    )
    detail_resp = client.get("/api/workflows/wf1/runs/run-1")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == "run-1"
    assert detail_resp.json()["stepEntries"][0]["step_id"] == "step_a"

    # 404 when run not found
    mock_service.get_run_details.return_value = None
    not_found_resp = client.get("/api/workflows/wf1/runs/missing")
    assert not_found_resp.status_code == 404


def test_resume_run_and_cancel_run_routes(client, mock_service):
    resumed_model = _sample_run_model("run-1", WorkflowRunStatusEnum.QUEUED)
    mock_service.resume_run.return_value = resumed_model

    resume_resp = client.post(
        "/api/workflows/wf1/runs/run-1/resume",
        json={"args_override": {"topic": "space"}},
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["id"] == "run-1"
    assert resume_resp.json()["status"] == "queued"

    # 422 when MissingResumeInputsError is raised
    mock_service.resume_run.side_effect = MissingResumeInputsError(
        ["topic", "style"]
    )
    err_422 = client.post("/api/workflows/wf1/runs/run-1/resume", json={})
    assert err_422.status_code == 422
    assert err_422.json()["detail"]["missing_inputs"] == ["topic", "style"]

    # 409 when StepError(409) is raised on resume
    mock_service.resume_run.side_effect = StepError(
        409,
        ErrorCategory.INVALID_INPUT,
        "Cannot resume workflow run in status 'running'.",
    )
    err_409 = client.post("/api/workflows/wf1/runs/run-1/resume", json={})
    assert err_409.status_code == 409

    # Cancel route 200 and 409
    canceled_model = _sample_run_model(
        "run-1", WorkflowRunStatusEnum.CANCELED
    ).model_copy(update={"canceled_by_user": True})
    mock_service.cancel_run.return_value = canceled_model

    cancel_resp = client.post("/api/workflows/wf1/runs/run-1/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "canceled"
    assert cancel_resp.json()["canceled_by_user"] is True

    mock_service.cancel_run.side_effect = StepError(
        409,
        ErrorCategory.INVALID_INPUT,
        "Cannot cancel workflow run in terminal status 'completed'.",
    )
    cancel_409 = client.post("/api/workflows/wf1/runs/run-1/cancel")
    assert cancel_409.status_code == 409


def test_batch_execute_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow

    mock_service.batch_execute_workflow.return_value = {
        "results": [
            {
                "row_index": 0,
                "run_id": "run_1",
                "execution_id": "run_1",
                "status": "SUCCESS",
                "run_status": "queued",
                "queue_reason": "WAITING_FOR_SLOT",
            }
        ]
    }

    payload = {"items": [{"row_index": 0, "args": {"param1": "val1"}}]}
    response = client.post("/api/workflows/wf1/batch-execute", json=payload)

    assert response.status_code == 200
    assert response.json()["results"][0]["run_id"] == "run_1"
    mock_service.batch_execute_workflow.assert_called_once()


def test_batch_execute_unauthorized(client, mock_service):
    mock_service.get_workflow.return_value = None

    payload = {"items": [{"row_index": 0, "args": {"param1": "val1"}}]}
    response = client.post("/api/workflows/wf1/batch-execute", json=payload)

    assert response.status_code == 404
    mock_service.batch_execute_workflow.assert_not_called()


def test_batch_execute_forbidden_for_regular_user(mock_service):
    app = FastAPI()
    app.include_router(router)

    regular_user = UserModel(
        id=2,
        email="user@example.com",
        name="Regular User",
        roles=[UserRoleEnum.USER],
    )
    app.dependency_overrides[get_current_user] = lambda: regular_user
    app.dependency_overrides[WorkflowService] = lambda: mock_service

    client = TestClient(app)

    payload = {"items": [{"row_index": 0, "args": {"param1": "val1"}}]}
    response = client.post("/api/workflows/wf1/batch-execute", json=payload)

    assert response.status_code == 403
    mock_service.batch_execute_workflow.assert_not_called()


def test_regular_user_can_access_other_endpoints(mock_service):
    app = FastAPI()
    app.include_router(router)

    regular_user = UserModel(
        id=2,
        email="user@example.com",
        name="Regular User",
        roles=[UserRoleEnum.USER],
    )
    app.dependency_overrides[get_current_user] = lambda: regular_user
    app.dependency_overrides[WorkflowService] = lambda: mock_service

    client = TestClient(app)

    mock_workflow = MagicMock()
    mock_workflow.user_id = 2
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.execute_workflow.return_value = _sample_run_model(
        "exec_id_123"
    )

    payload = {"args": {"param1": "val1"}}
    response = client.post("/api/workflows/wf1/workflow-execute", json=payload)

    assert response.status_code == 200
    assert response.json()["execution_id"] == "exec_id_123"
    mock_service.execute_workflow.assert_called_once()


def test_validate_workflow_success(client, mock_service):
    mock_service.validate_workflow.return_value = {
        "valid": True,
        "message": "Workflow structure is valid.",
    }
    payload = {
        "name": "Test Workflow",
        "description": "Validation test",
        "steps": [],
    }
    response = client.post("/api/workflows/validate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["message"] == "Workflow structure is valid."
    mock_service.validate_workflow.assert_called_once()


def test_validate_workflow_invalid_raises_400(client, mock_service):
    mock_service.validate_workflow.side_effect = ValueError(
        "Cycle detected in workflow graph"
    )
    payload = {
        "name": "Cyclic Workflow",
        "description": "Validation test with cycle",
        "steps": [],
    }
    response = client.post("/api/workflows/validate", json=payload)

    assert response.status_code == 400
    assert "Cycle detected in workflow graph" in response.json()["detail"]
    mock_service.validate_workflow.assert_called_once()
