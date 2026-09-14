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
"""Tests for Gallery Controller."""


from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.galleries.gallery_controller import router
from src.galleries.gallery_service import GalleryService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth


@pytest.fixture(name="mock_admin")
def fixture_mock_admin():
    return UserModel(
        id=1,
        email="admin@example.com",
        name="Admin",
        roles=[UserRoleEnum.ADMIN],
    )


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=2,
        email="user@example.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )


@pytest.fixture(name="mock_service")
def fixture_mock_service():
    service = AsyncMock()
    service.get_paginated_gallery = AsyncMock()
    service.get_media_by_id = AsyncMock()
    service.bulk_delete = AsyncMock()
    service.restore_item = AsyncMock()
    service.bulk_download = AsyncMock()
    service.bulk_copy = AsyncMock()
    service.bulk_move = AsyncMock()
    return service


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    auth = AsyncMock()
    auth.authorize = AsyncMock()
    return auth


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_service, mock_workspace_auth):
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[GalleryService] = lambda: mock_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth

    return TestClient(app)


def test_search_gallery_items_non_admin_no_workspace(client, mock_service):
    _ = mock_service
    # User is not admin. search_dto missing workspace_id should fail with 400
    payload = {"limit": 12, "offset": 0}
    response = client.post("/api/gallery/search", json=payload)
    assert response.status_code == 400


def test_search_gallery_items_admin_with_workspace(
    mock_admin,
    mock_service,
    mock_workspace_auth,
):
    # Create client with admin override
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[GalleryService] = lambda: mock_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth
    admin_client = TestClient(app)

    # Admin with workspace_id
    mock_service.get_paginated_gallery.return_value = PaginationResponseDto(
        count=1,
        data=[],
        page=1,
        page_size=10,
        total_pages=1,
    )

    payload = {"limit": 10, "offset": 0, "workspace_id": 100}
    response = admin_client.post("/api/gallery/search", json=payload)

    assert response.status_code == 200
    mock_workspace_auth.authorize.assert_called_once()
    mock_service.get_paginated_gallery.assert_called_once()


def test_get_single_gallery_item_not_found(client, mock_service):
    mock_service.get_media_by_id.return_value = None
    response = client.get("/api/gallery/item/999")
    assert response.status_code == 404


def test_bulk_delete_items_success(client, mock_service):
    mock_service.bulk_delete.return_value = True
    payload = {"items": [{"id": 1, "type": "media_item"}], "workspace_id": 1}
    response = client.post("/api/gallery/bulk-delete", json=payload)
    assert response.status_code == 200


def test_restore_gallery_item_success(client, mock_service):
    mock_service.restore_item.return_value = True
    response = client.post("/api/gallery/items/1/restore?item_type=media_item")
    assert response.status_code == 200


def test_bulk_download_items_success(client, mock_service):
    mock_service.bulk_download.return_value = "gs://bucket/downloads.zip"
    payload = {"items": [{"id": 1, "type": "media_item"}], "workspace_id": 1}
    response = client.post("/api/gallery/bulk-download", json=payload)
    assert response.status_code == 200


def test_bulk_copy_items_success(client, mock_service):
    mock_service.bulk_copy.return_value = {"copied_count": 1}
    payload = {
        "items": [{"id": 1, "type": "media_item"}],
        "target_workspace_id": 2,
    }
    response = client.post("/api/gallery/bulk-copy", json=payload)
    assert response.status_code == 200
    assert response.json() == {"copied_count": 1}
    mock_service.bulk_copy.assert_called_once()


def test_bulk_copy_folders_success(client, mock_service):
    mock_service.bulk_copy.return_value = {"copied_count": 1}
    payload = {
        "items": [{"id": 10, "type": "folder"}],
        "target_workspace_id": 2,
    }
    response = client.post("/api/gallery/bulk-copy", json=payload)
    assert response.status_code == 200
    assert response.json() == {"copied_count": 1}
    mock_service.bulk_copy.assert_called_once()


def test_bulk_move_items_success(client, mock_service):
    mock_service.bulk_move.return_value = {"moved_count": 1}
    payload = {
        "items": [{"id": 1, "type": "media_item"}],
        "target_workspace_id": 2,
    }
    response = client.post("/api/gallery/bulk-move", json=payload)
    assert response.status_code == 200
    assert response.json() == {"moved_count": 1}
    mock_service.bulk_move.assert_called_once()


def test_bulk_move_folders_success(client, mock_service):
    mock_service.bulk_move.return_value = {"moved_count": 1}
    payload = {
        "items": [{"id": 10, "type": "folder"}],
        "target_workspace_id": 2,
    }
    response = client.post("/api/gallery/bulk-move", json=payload)
    assert response.status_code == 200
    assert response.json() == {"moved_count": 1}
    mock_service.bulk_move.assert_called_once()
