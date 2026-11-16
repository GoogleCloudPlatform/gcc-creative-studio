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
"""Tests for Tags Controller."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException, status

from main import app
from src.tags.tags_service import TagsService
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import WorkspaceAuth
from src.tags.schema.tags_model import TagModel


@pytest.fixture(name="mock_tags_service")
def fixture_mock_tags_service():
    """Provides a mocked TagsService."""
    return AsyncMock()


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    """Provides a mocked WorkspaceAuth."""
    mock = AsyncMock()
    mock.authorize.return_value = True
    return mock


@pytest.fixture(name="override_dependencies", autouse=True)
def fixture_override_dependencies(mock_tags_service, mock_workspace_auth):
    """Overrides dependencies in the app."""
    app.dependency_overrides[TagsService] = lambda: mock_tags_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth
    yield
    # Cleanup
    if TagsService in app.dependency_overrides:
        del app.dependency_overrides[TagsService]
    if WorkspaceAuth in app.dependency_overrides:
        del app.dependency_overrides[WorkspaceAuth]


class TestListTags:
    """Tests for POST /api/tags/search."""

    def test_list_tags_with_workspace_success(
        self, api_client, mock_tags_service
    ):
        from src.common.dto.pagination_response_dto import PaginationResponseDto

        mock_tags_service.list_tags.return_value = PaginationResponseDto[
            TagModel
        ](
            count=1,
            page=1,
            page_size=10,
            total_pages=1,
            data=[TagModel(id=1, name="tag1", workspace_id=1)],
        )

        response = api_client.post("/api/tags/search", json={"workspace_id": 1})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "tag1"

    def test_list_tags_non_admin_no_workspace_forbidden(self, api_client):
        # Regular user should be forbidden if no workspace is specified
        response = api_client.post("/api/tags/search", json={})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_list_tags_admin_no_workspace_success(
        self, admin_client, mock_tags_service
    ):
        from src.common.dto.pagination_response_dto import PaginationResponseDto

        mock_tags_service.list_tags.return_value = PaginationResponseDto[
            TagModel
        ](
            count=1,
            page=1,
            page_size=10,
            total_pages=1,
            data=[TagModel(id=1, name="tag1", workspace_id=1)],
        )

        response = admin_client.post("/api/tags/search", json={})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["data"]) == 1


class TestCreateTag:
    """Tests for POST /api/tags/."""

    def test_create_tag_success(
        self, api_client, mock_tags_service, mock_workspace_auth
    ):
        mock_tags_service.create_tag.return_value = TagModel(
            id=1, name="new_tag", workspace_id=1
        )

        response = api_client.post(
            "/api/tags/", json={"name": "new_tag", "workspace_id": 1}
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "new_tag"
        mock_workspace_auth.authorize_write.assert_awaited_once()


class TestDeleteTag:
    """Tests for DELETE /api/tags/{tag_id}."""

    def test_delete_tag_success(self, api_client, mock_tags_service):
        # Tag exists
        mock_tag = TagModel(id=1, name="tag1", workspace_id=1)
        mock_tags_service.repo.get_by_id.return_value = mock_tag
        mock_tags_service.delete_tag.return_value = True

        response = api_client.delete("/api/tags/1")

        assert response.status_code == status.HTTP_200_OK

    def test_delete_tag_not_found(self, api_client, mock_tags_service):
        mock_tags_service.repo.get_by_id.return_value = None

        response = api_client.delete("/api/tags/999")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestBulkAssign:
    """Tests for POST /api/tags/bulk-assign."""

    def test_bulk_assign_success(
        self, api_client, mock_tags_service, mock_workspace_auth
    ):
        mock_tags_service.bulk_assign.return_value = True

        response = api_client.post(
            "/api/tags/bulk-assign",
            json={
                "item_ids": [1, 2],
                "tag_names": ["tag10"],
                "item_type": "media_item",
                "workspace_id": 1,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        mock_workspace_auth.authorize_write.assert_awaited_once()


class TestUpdateTag:
    """Tests for PUT /api/tags/{tag_id}."""

    def test_update_tag_success(self, api_client, mock_tags_service):
        # Mock repo.get_by_id to return a tag
        mock_tags_service.repo.get_by_id.return_value = TagModel(
            id=1, name="old_name", workspace_id=1
        )
        mock_tags_service.update_tag.return_value = TagModel(
            id=1, name="new_name", workspace_id=1, color="#FF0000"
        )

        response = api_client.put(
            "/api/tags/1",
            json={"name": "new_name", "color": "#FF0000"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "new_name"
        assert data["color"] == "#FF0000"

    def test_update_tag_not_found(self, api_client, mock_tags_service):
        # Mock repo.get_by_id to return None
        mock_tags_service.repo.get_by_id.return_value = None

        response = api_client.put(
            "/api/tags/999",
            json={"name": "new_name"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTagRoleParity:
    """Verifies PRIVATE workspace OWNER/ADMIN/EDITOR/VIEWER parity on foreign tags."""

    @pytest.mark.parametrize(
        "role,expected_status",
        [
            (WorkspaceRoleEnum.OWNER, status.HTTP_200_OK),
            (WorkspaceRoleEnum.ADMIN, status.HTTP_200_OK),
            (WorkspaceRoleEnum.EDITOR, status.HTTP_403_FORBIDDEN),
            (WorkspaceRoleEnum.VIEWER, status.HTTP_403_FORBIDDEN),
        ],
    )
    def test_foreign_tag_update_and_delete_by_workspace_role(
        self,
        api_client,
        mock_workspace_auth,
        role,
        expected_status,
    ):
        mock_repo = AsyncMock()
        foreign_tag = TagModel(
            id=5, name="team_tag", workspace_id=10, user_id=999
        )
        mock_repo.get_by_id.return_value = foreign_tag
        mock_repo.update_tag.return_value = TagModel(
            id=5, name="renamed", workspace_id=10, user_id=999
        )
        mock_repo.delete.return_value = True

        real_service = TagsService(repo=mock_repo)
        app.dependency_overrides[TagsService] = lambda: real_service

        if role == WorkspaceRoleEnum.VIEWER:
            mock_workspace_auth.authorize_write.side_effect = HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Viewer role has read-only access to this workspace.",
            )
        else:
            mock_workspace_auth.authorize_write.side_effect = None
            mock_workspace_auth.authorize_write.return_value = WorkspaceModel(
                id=10,
                name="Private Team",
                owner_id=1 if role == WorkspaceRoleEnum.OWNER else 999,
                scope=WorkspaceScopeEnum.PRIVATE,
                current_user_role=role,
            )

        put_res = api_client.put("/api/tags/5", json={"name": "renamed"})
        del_res = api_client.delete("/api/tags/5")

        assert put_res.status_code == expected_status
        assert del_res.status_code == expected_status
