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
"""Tests for Source Asset Controller."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.common.base_dto import MimeTypeEnum
from src.source_assets.dto.source_asset_response_dto import (
    SourceAssetResponseDto,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
)
from src.source_assets.source_asset_controller import router
from src.source_assets.source_asset_service import SourceAssetService
from src.users.user_model import UserModel
from src.workspaces.workspace_auth_guard import WorkspaceAuth


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.fixture(name="mock_service")
def fixture_mock_service():
    service = AsyncMock()
    service.upload_asset = AsyncMock()
    service.convert_to_png = AsyncMock()
    service.list_assets_for_user = AsyncMock()
    service.get_all_vto_assets = AsyncMock()
    service.delete_asset = AsyncMock()
    service.get_asset_by_id = AsyncMock()
    service.generate_signed_upload_url = AsyncMock()
    service.finalize_direct_upload = AsyncMock()
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

    # Override dependencies
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[SourceAssetService] = lambda: mock_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth

    return TestClient(app)


def test_upload_source_asset_success(
    client,
    mock_service,
    mock_workspace_auth,
    mock_user,
):
    # Setup
    mock_response = SourceAssetResponseDto(
        id=10,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b/1",
        original_filename="test.png",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        aspect_ratio="1:1",
        file_hash="h",
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        presigned_url="https://signed.url",
        presigned_original_url="",
        presigned_thumbnail_url="",
        user_email="test@example.com",
    )
    mock_service.upload_asset.return_value = mock_response

    files = {"file": ("test.png", b"fake_image_bytes", "image/png")}
    data = {"workspaceId": "1"}

    response = client.post("/api/source_assets/upload", files=files, data=data)

    assert response.status_code == 200
    assert response.json()["id"] == 10
    assert response.json()["presignedUrl"] == "https://signed.url"
    mock_workspace_auth.authorize.assert_called_once()
    mock_service.upload_asset.assert_called_once()


def test_convert_image_to_png_success(client, mock_service):
    mock_service.convert_to_png.return_value = b"png_data"

    files = {"file": ("test.jpg", b"fake_jpg_bytes", "image/jpeg")}

    response = client.post("/api/source_assets/convert-to-png", files=files)

    assert response.status_code == 200
    assert response.content == b"png_data"
    mock_service.convert_to_png.assert_called_once()


def test_list_source_assets_regular_user(client, mock_service, mock_user):
    from src.common.dto.pagination_response_dto import PaginationResponseDto

    mock_response = PaginationResponseDto[SourceAssetResponseDto](
        count=0,
        page=1,
        page_size=10,
        total_pages=0,
        data=[],
    )
    # We mock service to return a dict or object that matches Pydantic dump.
    # FastAPI does the serialization.
    mock_service.list_assets_for_user.return_value = mock_response

    payload = {"limit": 10, "offset": 0}

    response = client.post("/api/source_assets/search", json=payload)

    assert response.status_code == 200
    assert response.json()["data"] == []
    mock_service.list_assets_for_user.assert_called_once()
    # verify regular user forcing target_user_id
    call_args = mock_service.list_assets_for_user.call_args[1]
    assert call_args["target_user_id"] == mock_user.id


def test_delete_source_asset_forbidden_for_user(client, mock_service):
    mock_service.delete_asset.return_value = True

    response = client.delete("/api/source_assets/1")

    assert response.status_code == 403
    mock_service.delete_asset.assert_not_called()


def test_delete_source_asset_admin_role_needed(client, mock_service, mock_user):
    # Update mock_user to resemble Admin
    mock_user.roles = ["admin"]
    mock_service.delete_asset.return_value = True

    response = client.delete("/api/source_assets/1")

    assert response.status_code == 204
    mock_service.delete_asset.assert_called_once_with(1)


def test_delete_source_asset_not_found(client, mock_service, mock_user):
    mock_user.roles = ["admin"]
    mock_service.delete_asset.return_value = False

    response = client.delete("/api/source_assets/999")

    assert response.status_code == 404
    mock_service.delete_asset.assert_called_once_with(999)


@pytest.mark.anyio
async def test_list_source_assets_admin_search_self(
    client, mock_service, mock_user
):
    from src.common.dto.pagination_response_dto import PaginationResponseDto

    mock_user.roles = ["admin"]
    mock_service.list_assets_for_user.return_value = PaginationResponseDto(
        count=0,
        data=[],
        page=1,
        page_size=10,
        total_pages=0,
    )

    payload = {"user_email": "test@example.com"}
    response = client.post("/api/source_assets/search", json=payload)

    assert response.status_code == 200
    call_args = mock_service.list_assets_for_user.call_args[1]
    assert call_args["target_user_id"] == mock_user.id


@pytest.mark.anyio
async def test_list_source_assets_admin_search_other(
    client, mock_service, mock_user
):
    from src.common.dto.pagination_response_dto import PaginationResponseDto

    mock_user.roles = ["admin"]
    mock_service.list_assets_for_user.return_value = PaginationResponseDto(
        count=0,
        data=[],
        page=1,
        page_size=10,
        total_pages=0,
    )

    mock_target_user = MagicMock()
    mock_target_user.id = 99

    # We also need to mock user_repo which is used inside the async task
    # In controller: user_repo: UserRepository = Depends()
    # But Depends() without override will execute. Usually we mock what it does.
    with patch(
        "src.source_assets.source_asset_controller.asyncio.to_thread",
    ) as mock_to_thread:
        mock_to_thread.return_value = mock_target_user

        payload = {"user_email": "other@example.com"}
        response = client.post("/api/source_assets/search", json=payload)

        assert response.status_code == 200
        call_args = mock_service.list_assets_for_user.call_args[1]
        assert call_args["target_user_id"] == 99


@pytest.mark.anyio
async def test_list_source_assets_admin_search_other_not_found(
    client,
    mock_service,
    mock_user,
):
    mock_user.roles = ["admin"]
    with patch(
        "src.source_assets.source_asset_controller.asyncio.to_thread",
    ) as mock_to_thread:
        mock_to_thread.return_value = None

        payload = {"user_email": "missing@example.com"}
        response = client.post("/api/source_assets/search", json=payload)
        assert response.status_code == 404


def test_get_vto_assets_exception(client, mock_service):
    mock_service.get_all_vto_assets.side_effect = Exception("Service error")
    response = client.get("/api/source_assets/vto-assets")
    assert response.status_code == 500


def test_get_source_asset_not_found(client, mock_service):
    mock_service.get_asset_by_id.return_value = None
    response = client.get("/api/source_assets/999")
    assert response.status_code == 404


def test_generate_source_asset_upload_url_success(
    client, mock_service, mock_workspace_auth
):
    from src.source_assets.dto.generate_upload_url_dto import (
        GenerateSourceAssetUploadUrlResponseDto,
    )

    mock_service.generate_signed_upload_url.return_value = (
        GenerateSourceAssetUploadUrlResponseDto(
            upload_url="https://signed.gcs/upload",
            gcs_uri="gs://b/source_assets/1/uploads/uuid/test.png",
            file_uuid="uuid-123",
        )
    )

    payload = {
        "workspaceId": 1,
        "filename": "test.png",
        "contentType": "image/png",
        "size": 1024,
    }
    response = client.post(
        "/api/source_assets/generate-upload-url", json=payload
    )
    assert response.status_code == 200
    data = response.json()
    assert data["uploadUrl"] == "https://signed.gcs/upload"
    assert data["gcsUri"] == "gs://b/source_assets/1/uploads/uuid/test.png"
    assert data["fileUuid"] == "uuid-123"
    mock_workspace_auth.authorize.assert_called_once()


def test_generate_source_asset_upload_url_too_large(client):
    payload = {
        "workspaceId": 1,
        "filename": "huge.mp4",
        "contentType": "video/mp4",
        "size": 600 * 1024 * 1024,
    }
    response = client.post(
        "/api/source_assets/generate-upload-url", json=payload
    )
    assert response.status_code == 413


def test_generate_source_asset_upload_url_invalid_format(client):
    payload = {
        "workspaceId": 1,
        "filename": "document.pdf",
        "contentType": "application/pdf",
        "size": 1024,
    }
    response = client.post(
        "/api/source_assets/generate-upload-url", json=payload
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file format."


def test_finalize_source_asset_upload_success(
    client, mock_service, mock_workspace_auth, mock_user
):
    mock_response = SourceAssetResponseDto(
        id=10,
        workspace_id=1,
        user_id=mock_user.id,
        gcs_uri="gs://b/source_assets/1/uploads/uuid/test.png",
        original_filename="test.png",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        aspect_ratio="1:1",
        file_hash="hash123",
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        presigned_url="https://signed.url",
        presigned_original_url="",
        presigned_thumbnail_url="",
        user_email=mock_user.email,
    )
    mock_service.finalize_direct_upload.return_value = mock_response

    payload = {
        "workspaceId": 1,
        "gcsUri": "gs://b/source_assets/1/uploads/uuid/test.png",
        "filename": "test.png",
        "mimeType": "image/png",
        "size": 1024,
    }
    response = client.post("/api/source_assets/finalize-upload", json=payload)
    assert response.status_code == 201
    assert response.json()["id"] == 10
