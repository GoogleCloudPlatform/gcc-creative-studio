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

"""Tests for Folder Controller."""

from unittest.mock import AsyncMock
import pytest
from fastapi import status

from main import app
from src.auth.auth_guard import get_current_user
from src.folders.dto.folder_dto import (
    FolderBreadcrumbDto,
    FolderResponseDto,
    FolderTreeNodeDto,
)
from src.folders.folder_service import FolderService
from src.workspaces.workspace_auth_guard import WorkspaceAuth


@pytest.fixture(name="mock_folder_service")
def fixture_mock_folder_service():
    """Provides a mocked FolderService."""
    return AsyncMock()


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    """Provides a mocked WorkspaceAuth."""
    mock = AsyncMock()
    mock.authorize.return_value = True
    return mock


@pytest.fixture(name="override_folder_dependencies", autouse=True)
def fixture_override_folder_dependencies(
    mock_folder_service, mock_workspace_auth, mock_user
):
    """Overrides dependencies in the app."""
    app.dependency_overrides[FolderService] = lambda: mock_folder_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
    if FolderService in app.dependency_overrides:
        del app.dependency_overrides[FolderService]
    if WorkspaceAuth in app.dependency_overrides:
        del app.dependency_overrides[WorkspaceAuth]
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


class TestCreateFolder:
    """Tests for POST /api/folders."""

    def test_create_folder_success(self, api_client, mock_folder_service):
        mock_folder_service.create_folder.return_value = FolderResponseDto(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="user@example.com",
            name="New Folder",
            parent_id=None,
            color="#FFFFFF",
            item_count=0,
            subfolder_count=0,
        )

        response = api_client.post(
            "/api/folders",
            json={
                "name": "New Folder",
                "workspaceId": 1,
                "parentId": None,
                "color": "#FFFFFF",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "New Folder"


class TestListFolders:
    """Tests for GET /api/folders."""

    def test_list_folders_success(self, api_client, mock_folder_service):
        mock_folder_service.get_folders.return_value = [
            FolderResponseDto(
                id=1,
                workspace_id=1,
                user_id=1,
                user_email="user@example.com",
                name="Folder A",
                parent_id=None,
                item_count=3,
                subfolder_count=1,
            )
        ]

        response = api_client.get("/api/folders?workspace_id=1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Folder A"
        assert data[0]["itemCount"] == 3


class TestGetFolderTree:
    """Tests for GET /api/folders/tree."""

    def test_get_folder_tree_success(self, api_client, mock_folder_service):
        mock_folder_service.get_folder_tree.return_value = [
            FolderTreeNodeDto(
                id=1,
                name="Root Folder",
                parent_id=None,
                children=[
                    FolderTreeNodeDto(
                        id=2, name="Child Folder", parent_id=1, children=[]
                    )
                ],
            )
        ]

        response = api_client.get("/api/folders/tree?workspace_id=1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Root Folder"
        assert len(data[0]["children"]) == 1


class TestGetFolderBreadcrumbs:
    """Tests for GET /api/folders/{folder_id}/breadcrumbs."""

    def test_get_breadcrumbs_success(self, api_client, mock_folder_service):
        mock_folder_service.get_breadcrumbs.return_value = [
            FolderBreadcrumbDto(id=1, name="Root", parent_id=None),
            FolderBreadcrumbDto(id=2, name="Child", parent_id=1),
        ]

        response = api_client.get("/api/folders/2/breadcrumbs")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Root"
        assert data[1]["name"] == "Child"
        mock_folder_service.get_breadcrumbs.assert_called_once_with(
            folder_id=2, workspace_id=None
        )

    def test_get_breadcrumbs_with_workspace_id(
        self, api_client, mock_folder_service, mock_workspace_auth
    ):
        mock_folder_service.get_breadcrumbs.return_value = [
            FolderBreadcrumbDto(id=2, name="Child", parent_id=None),
        ]

        response = api_client.get("/api/folders/2/breadcrumbs?workspace_id=1")
        assert response.status_code == status.HTTP_200_OK
        mock_workspace_auth.authorize.assert_called_once()
        mock_folder_service.get_breadcrumbs.assert_called_once_with(
            folder_id=2, workspace_id=1
        )


class TestGetFolderById:
    """Tests for GET /api/folders/{folder_id}."""

    def test_get_folder_by_id_success(self, api_client, mock_folder_service):
        mock_folder_service.get_folder_by_id.return_value = FolderResponseDto(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="user@example.com",
            name="Folder A",
            parent_id=None,
            item_count=5,
            subfolder_count=0,
        )

        response = api_client.get("/api/folders/1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == 1
        assert data["itemCount"] == 5
        mock_folder_service.get_folder_by_id.assert_called_once_with(
            folder_id=1, workspace_id=None
        )

    def test_get_folder_by_id_with_workspace_id(
        self, api_client, mock_folder_service, mock_workspace_auth
    ):
        mock_folder_service.get_folder_by_id.return_value = FolderResponseDto(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="user@example.com",
            name="Folder A",
            parent_id=None,
            item_count=5,
            subfolder_count=0,
        )

        response = api_client.get("/api/folders/1?workspace_id=1")
        assert response.status_code == status.HTTP_200_OK
        mock_workspace_auth.authorize.assert_called_once()
        mock_folder_service.get_folder_by_id.assert_called_once_with(
            folder_id=1, workspace_id=1
        )


class TestUpdateFolder:
    """Tests for PATCH /api/folders/{folder_id}."""

    def test_update_folder_success(
        self, api_client, mock_folder_service, mock_workspace_auth
    ):
        existing_folder = FolderResponseDto(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="user@example.com",
            name="Old Folder",
            parent_id=None,
            item_count=0,
            subfolder_count=0,
        )
        mock_folder_service.get_folder_by_id.return_value = existing_folder
        mock_folder_service.update_folder.return_value = FolderResponseDto(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="user@example.com",
            name="Renamed Folder",
            parent_id=None,
            color="#FF0000",
            item_count=0,
            subfolder_count=0,
        )

        response = api_client.patch(
            "/api/folders/1",
            json={"name": "Renamed Folder", "color": "#FF0000"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Renamed Folder"
        mock_workspace_auth.authorize.assert_called_once()


class TestDeleteFolder:
    """Tests for DELETE /api/folders/{folder_id}."""

    def test_delete_folder_success(
        self, api_client, mock_folder_service, mock_workspace_auth
    ):
        existing_folder = FolderResponseDto(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="user@example.com",
            name="Folder To Delete",
            parent_id=None,
            item_count=0,
            subfolder_count=0,
        )
        mock_folder_service.get_folder_by_id.return_value = existing_folder
        mock_folder_service.delete_folder.return_value = {"success": True}

        response = api_client.delete("/api/folders/1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        mock_workspace_auth.authorize.assert_called_once()


class TestMoveItems:
    """Tests for POST /api/folders/move-items."""

    def test_move_items_success(self, api_client, mock_folder_service):
        mock_folder_service.move_items.return_value = {
            "media_items_moved": 2,
            "source_assets_moved": 1,
            "folders_moved": 1,
            "total_moved": 4,
        }

        response = api_client.post(
            "/api/folders/move-items",
            json={
                "workspaceId": 1,
                "mediaItemIds": [1, 2],
                "sourceAssetIds": [5],
                "folderIds": [10],
                "destinationFolderId": 3,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_moved"] == 4
