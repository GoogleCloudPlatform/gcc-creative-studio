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
"""Tests for Imagen Controller."""


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.common.base_dto import GenerationModelEnum
from src.common.schema.media_item_model import JobStatusEnum, MimeTypeEnum
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.imagen_controller import router
from src.images.imagen_service import ImagenService
from src.images.schema.imagen_result_model import (
    CustomImagenResult,
    ImageGenerationResult,
)
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
    service.start_image_generation_job = AsyncMock()
    service.start_vto_generation_job = AsyncMock()
    service.start_upload_upscale_job = AsyncMock()
    service.upscale_image = AsyncMock()
    return service


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    auth = AsyncMock()
    auth.authorize = AsyncMock()
    return auth


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_service, mock_workspace_auth):
    app = FastAPI()
    app.state.executor = MagicMock()
    app.include_router(router)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[ImagenService] = lambda: mock_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth

    return TestClient(app)


def test_generate_images_success(client, mock_service, mock_workspace_auth):
    mock_response = MediaItemResponse(
        id=123,
        workspace_id=1,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        status=JobStatusEnum.PROCESSING,
        model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
        gcs_uris=[],
        presigned_urls=[],
        presigned_thumbnail_urls=[],
        aspect_ratio="1:1",
    )
    mock_service.start_image_generation_job.return_value = mock_response

    payload = {
        "prompt": "A sunset",
        "workspace_id": 1,
        "generation_model": "gemini-3.1-flash-image",
    }

    response = client.post("/api/images/generate-images", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == 123
    mock_workspace_auth.authorize.assert_called_once()
    mock_service.start_image_generation_job.assert_called_once()


def test_generate_images_vto_success(client, mock_service, mock_workspace_auth):
    _ = mock_workspace_auth
    mock_response = MediaItemResponse(
        id=222,
        workspace_id=1,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        status=JobStatusEnum.PROCESSING,
        model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE,
        gcs_uris=[],
        presigned_urls=[],
        aspect_ratio="1:1",
    )
    mock_service.start_vto_generation_job.return_value = mock_response

    payload = {
        "workspace_id": 1,
        "person_image": {"source_asset_id": 101},
        "top_image": {"source_asset_id": 102},
    }

    response = client.post("/api/images/generate-images-for-vto", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == 222


def test_upload_upscale_success(client, mock_service, mock_workspace_auth):
    _ = mock_workspace_auth
    mock_response = MediaItemResponse(
        id=333,
        workspace_id=1,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        status=JobStatusEnum.PROCESSING,
        model=GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
        gcs_uris=[],
        presigned_urls=[],
        aspect_ratio="1:1",
    )
    mock_service.start_upload_upscale_job.return_value = mock_response

    files = {"file": ("test.png", b"fake_bytes", "image/png")}
    data = {"workspaceId": "1"}

    response = client.post("/api/images/upload-upscale", files=files, data=data)

    assert response.status_code == 200
    assert response.json()["id"] == 333


def test_upscale_image_api_success(client, mock_service):
    mock_result = ImageGenerationResult(
        enhanced_prompt="",
        rai_filtered_reason="",
        image=CustomImagenResult(
            gcs_uri="gs://b/u.png",
            encoded_image="",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            presigned_url="",
        ),
    )
    mock_service.upscale_image.return_value = mock_result

    payload = {"user_image": "gs://b/i.png", "upscale_factor": "x2"}

    response = client.post("/api/images/upscale-image", json=payload)

    assert response.status_code == 200
    assert response.json()["image"]["gcsUri"] == "gs://b/u.png"


def test_generate_images_http_exception(client, mock_service):
    from fastapi import HTTPException

    mock_service.start_image_generation_job.side_effect = HTTPException(
        status_code=400,
        detail="Custom Bad Request",
    )

    payload = {
        "prompt": "A sunset",
        "workspace_id": 1,
        "generation_model": "gemini-3.1-flash-image",
    }

    response = client.post("/api/images/generate-images", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Custom Bad Request"


def test_generate_images_value_error(client, mock_service):
    mock_service.start_image_generation_job.side_effect = ValueError(
        "Invalid Prompt"
    )

    payload = {
        "prompt": "A sunset",
        "workspace_id": 1,
        "generation_model": "gemini-3.1-flash-image",
    }

    response = client.post("/api/images/generate-images", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Prompt"


def test_generate_images_general_exception(client, mock_service):
    mock_service.start_image_generation_job.side_effect = Exception(
        "System Crash"
    )

    payload = {
        "prompt": "A sunset",
        "workspace_id": 1,
        "generation_model": "gemini-3.1-flash-image",
    }

    response = client.post("/api/images/generate-images", json=payload)

    assert response.status_code == 500
    assert "System Crash" in response.json()["detail"]


def test_generate_images_vto_http_exception(client, mock_service):
    from fastapi import HTTPException

    mock_service.start_vto_generation_job.side_effect = HTTPException(
        status_code=400,
        detail="VTO Failed",
    )

    payload = {
        "workspace_id": 1,
        "person_image": {"source_asset_id": 101},
        "top_image": {"source_asset_id": 102},
    }

    response = client.post("/api/images/generate-images-for-vto", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "VTO Failed"


def test_upscale_image_api_http_exception(client, mock_service):
    from fastapi import HTTPException

    mock_service.upscale_image.side_effect = HTTPException(
        status_code=400,
        detail="Upscale Failed",
    )

    payload = {"user_image": "gs://b/i.png", "upscale_factor": "x2"}

    response = client.post("/api/images/upscale-image", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Upscale Failed"


def test_generate_images_vto_value_error(client, mock_service):
    mock_service.start_vto_generation_job.side_effect = ValueError(
        "Invalid VTO"
    )
    payload = {
        "workspace_id": 1,
        "person_image": {"source_asset_id": 101},
        "top_image": {"source_asset_id": 102},
    }
    response = client.post("/api/images/generate-images-for-vto", json=payload)
    assert response.status_code == 400


def test_generate_images_vto_general_exception(client, mock_service):
    mock_service.start_vto_generation_job.side_effect = Exception("VTO Crash")
    payload = {
        "workspace_id": 1,
        "person_image": {"source_asset_id": 101},
        "top_image": {"source_asset_id": 102},
    }
    response = client.post("/api/images/generate-images-for-vto", json=payload)
    assert response.status_code == 500


def test_upscale_image_api_value_error(client, mock_service):
    mock_service.upscale_image.side_effect = ValueError("Upscale Invalid")
    payload = {"user_image": "gs://b/i.png", "upscale_factor": "x2"}
    response = client.post("/api/images/upscale-image", json=payload)
    assert response.status_code == 400


def test_upscale_image_api_general_exception(client, mock_service):
    mock_service.upscale_image.side_effect = Exception("Upscale Crash")
    payload = {"user_image": "gs://b/i.png", "upscale_factor": "x2"}
    response = client.post("/api/images/upscale-image", json=payload)
    assert response.status_code == 500
