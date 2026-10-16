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
"""Tests for Workflow Template Controller endpoints."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.schema.workflow_template_model import WorkflowTemplateModel
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
    service.list_templates = AsyncMock()
    service.create_template = AsyncMock()
    service.delete_template = AsyncMock()
    return service


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_service):
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[WorkflowService] = lambda: mock_service

    return TestClient(app)


def test_list_templates_success(client, mock_service, mock_user):
    mock_service.list_templates.return_value = [
        WorkflowTemplateModel(
            id="tmpl-1",
            user_id=mock_user.id,
            name="Template 1",
            description="First template",
            steps=[],
        )
    ]

    response = client.get("/api/workflows/templates")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "tmpl-1"
    assert data[0]["name"] == "Template 1"
    mock_service.list_templates.assert_called_once_with(user_id=mock_user.id)


def test_create_template_success(client, mock_service, mock_user):
    payload = {
        "name": "New Custom Template",
        "description": "Template description",
        "steps": [
            {
                "step_id": "step_1",
                "type": "image",
                "settings": {"mode": "generate_image"},
                "inputs": {"prompt": "a test prompt"},
                "outputs": {},
            }
        ],
    }

    mock_service.create_template.return_value = WorkflowTemplateModel(
        id="tmpl-new",
        user_id=mock_user.id,
        name=payload["name"],
        description=payload["description"],
        steps=payload["steps"],
    )

    response = client.post("/api/workflows/templates", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "tmpl-new"
    assert data["name"] == "New Custom Template"
    mock_service.create_template.assert_called_once()


def test_create_template_duplicate_name_conflict(client, mock_service):
    payload = {
        "name": "Existing Template",
        "description": "Duplicate description",
        "steps": [],
    }

    mock_service.create_template.side_effect = ValueError(
        "A template named 'Existing Template' already exists. Please choose a unique name."
    )

    response = client.post("/api/workflows/templates", json=payload)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_create_template_invalid_structure_bad_request(client, mock_service):
    payload = {
        "name": "Corrupt Template",
        "description": "Invalid steps",
        "steps": [],
    }

    mock_service.create_template.side_effect = ValueError(
        "Invalid workflow template structure: Cycle detected in workflow graph"
    )

    response = client.post("/api/workflows/templates", json=payload)

    assert response.status_code == 400
    assert "Invalid workflow template structure" in response.json()["detail"]


def test_delete_template_success(client, mock_service, mock_user):
    mock_service.delete_template.return_value = True

    response = client.delete("/api/workflows/templates/tmpl-123")

    assert response.status_code == 204
    mock_service.delete_template.assert_called_once_with(
        user_id=mock_user.id,
        template_id="tmpl-123",
    )


def test_delete_template_not_found(client, mock_service, mock_user):
    mock_service.delete_template.return_value = False

    response = client.delete("/api/workflows/templates/tmpl-999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
    mock_service.delete_template.assert_called_once_with(
        user_id=mock_user.id,
        template_id="tmpl-999",
    )
