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
"""Tests for Workspace Controller."""


from unittest.mock import AsyncMock

import pytest
from fastapi import status

from main import app
from src.workspaces.schema.workspace_model import WorkspaceModel
from src.workspaces.workspace_service import WorkspaceService


@pytest.fixture(name="mock_workspace_service")
def fixture_mock_workspace_service():
    """Provides a mocked WorkspaceService."""
    return AsyncMock()


@pytest.fixture(name="override_workspace_service", autouse=True)
def fixture_override_workspace_service(mock_workspace_service):
    """Overrides the WorkspaceService dependency in the app."""
    app.dependency_overrides[WorkspaceService] = lambda: mock_workspace_service
    yield
    if WorkspaceService in app.dependency_overrides:
        del app.dependency_overrides[WorkspaceService]


class TestCreateWorkspace:
    """Tests for POST /api/workspaces."""

    def test_create_workspace_success(
        self,
        api_client,
        mock_workspace_service,
        mock_user,
    ):
        mock_workspace = WorkspaceModel(
            id=1,
            name="My Workspace",
            owner_id=mock_user.id,
        )
        mock_workspace_service.create_workspace.return_value = mock_workspace

        response = api_client.post(
            "/api/workspaces", json={"name": "My Workspace"}
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "My Workspace"
        assert data["id"] == 1


class TestListMyWorkspaces:
    """Tests for GET /api/workspaces."""

    def test_list_my_workspaces_success(
        self,
        api_client,
        mock_workspace_service,
        mock_user,
    ):
        workspace = WorkspaceModel(id=1, name="Work 1", owner_id=mock_user.id)
        mock_workspace_service.list_workspaces_for_user.return_value = [
            workspace
        ]

        response = api_client.get("/api/workspaces")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Work 1"


class TestInviteUser:
    """Tests for POST /api/workspaces/{id}/invites."""

    def test_invite_user_success(
        self, api_client, mock_workspace_service, mock_user
    ):
        workspace = WorkspaceModel(id=1, name="Work 1", owner_id=mock_user.id)
        mock_workspace_service.invite_user_to_workspace.return_value = workspace

        response = api_client.post(
            "/api/workspaces/1/invites",
            json={"email": "guest@example.com", "role": "viewer"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == 1

    def test_invite_user_not_found(self, api_client, mock_workspace_service):
        mock_workspace_service.invite_user_to_workspace.return_value = None

        response = api_client.post(
            "/api/workspaces/1/invites",
            json={"email": "unknown@example.com", "role": "viewer"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert (
            "Workspace or user to invite not found" in response.json()["detail"]
        )


class TestUpdateMemberRole:
    """Tests for PUT /api/workspaces/{workspace_id}/members/{user_id}."""

    def test_update_member_role_success(
        self, api_client, mock_workspace_service, mock_user
    ):
        workspace = WorkspaceModel(id=1, name="Work 1", owner_id=mock_user.id)
        mock_workspace_service.update_member_role.return_value = workspace

        response = api_client.put(
            "/api/workspaces/1/members/2",
            json={"role": "editor"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == 1
        mock_workspace_service.update_member_role.assert_called_once()

    def test_update_member_role_not_found(
        self, api_client, mock_workspace_service
    ):
        from fastapi import HTTPException

        mock_workspace_service.update_member_role.side_effect = HTTPException(
            status_code=404,
            detail="Member not found in this workspace.",
        )

        response = api_client.put(
            "/api/workspaces/1/members/99",
            json={"role": "editor"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Member not found" in response.json()["detail"]
