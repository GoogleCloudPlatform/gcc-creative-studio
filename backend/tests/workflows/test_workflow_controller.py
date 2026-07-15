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


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.workflow_controller import router
from src.workflows.workflow_service import WorkflowService


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
    service.get_execution_details = AsyncMock()
    service.list_executions = MagicMock()  # Synchronous method in service
    return service


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_service):
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[WorkflowService] = lambda: mock_service

    return TestClient(app)


def test_search_workflows_success(client, mock_service):
    from src.common.dto.pagination_response_dto import PaginationResponseDto

    # Provide complete fields for WorkflowModel
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

    # Steps must be a list
    payload = {"name": "New Workflow", "steps": []}
    response = client.post("/api/workflows", json=payload)

    # Note: create_workflow returns Response or object?
    # Controller uses status_code=201
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


def test_execute_workflow_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.execute_workflow.return_value = "exec_id_123"

    payload = {"args": {"param1": "val1"}}
    # Controller relies on body being parsed to WorkflowExecuteDto
    response = client.post("/api/workflows/wf1/workflow-execute", json=payload)

    assert response.status_code == 200
    assert response.json()["execution_id"] == "exec_id_123"


def test_execute_workflow_unauthorized(client, mock_service):
    mock_service.get_workflow.return_value = None

    payload = {"args": {"param1": "val1"}}
    response = client.post("/api/workflows/wf1/workflow-execute", json=payload)

    assert response.status_code == 404
    mock_service.execute_workflow.assert_not_called()


def test_update_workflow_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_by_id.return_value = mock_workflow

    mock_updated = {"id": "wf1", "name": "Updated", "steps": [], "user_id": 1}
    mock_service.update_workflow.return_value = mock_updated

    payload = {"name": "Updated", "steps": []}
    response = client.put("/api/workflows/wf1", json=payload)

    assert response.status_code == 200
    assert response.json()["name"] == "Updated"


def test_delete_workflow_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.delete_by_id.return_value = True

    response = client.delete("/api/workflows/wf1")

    assert response.status_code == 204


def test_get_execution_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.get_execution_details.return_value = {
        "execution_id": "exec1",
        "status": "running",
    }

    response = client.get("/api/workflows/wf1/executions/exec1")

    assert response.status_code == 200
    assert response.json()["execution_id"] == "exec1"


def test_list_executions_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow
    mock_service.list_executions.return_value = [{"execution_id": "exec1"}]

    response = client.get("/api/workflows/wf1/executions")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_batch_execute_success(client, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow

    mock_service.batch_execute_workflow.return_value = {
        "results": [
            {"row_index": 0, "execution_id": "exec_1", "status": "SUCCESS"}
        ]
    }

    payload = {"items": [{"row_index": 0, "args": {"param1": "val1"}}]}
    response = client.post("/api/workflows/wf1/batch-execute", json=payload)

    assert response.status_code == 200
    assert response.json()["results"][0]["execution_id"] == "exec_1"
    mock_service.batch_execute_workflow.assert_called_once()


def test_batch_execute_unauthorized(client, mock_service):
    mock_service.get_workflow.return_value = None

    payload = {"items": [{"row_index": 0, "args": {"param1": "val1"}}]}
    response = client.post("/api/workflows/wf1/batch-execute", json=payload)

    assert response.status_code == 404
    mock_service.batch_execute_workflow.assert_not_called()


def test_batch_execute_forbidden_for_regular_user(mock_service):
    # Setup app with a regular user
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
    mock_service.execute_workflow.return_value = "exec_id_123"

    payload = {"args": {"param1": "val1"}}
    response = client.post("/api/workflows/wf1/workflow-execute", json=payload)

    assert response.status_code == 200
    assert response.json()["execution_id"] == "exec_id_123"
    mock_service.execute_workflow.assert_called_once()
