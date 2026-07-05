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
"""Tests for Veo Controller."""


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.common.base_dto import MimeTypeEnum
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.users.user_model import UserModel
from src.videos.veo_controller import router
from src.videos.veo_service import VeoService
from src.workspaces.workspace_auth_guard import WorkspaceAuth


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.fixture(name="mock_veo_service")
def fixture_mock_veo_service():
    service = AsyncMock()
    service.start_video_generation_job = AsyncMock()
    service.start_video_concatenation_job = AsyncMock()
    return service


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    auth = AsyncMock()
    auth.authorize = AsyncMock()
    return auth


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_veo_service, mock_workspace_auth):
    app = FastAPI()
    app.include_router(router)

    # Setup app state
    app.state.executor = MagicMock()

    # Override dependencies
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[VeoService] = lambda: mock_veo_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth

    return TestClient(app)


def test_generate_videos_success(client, mock_veo_service, mock_workspace_auth):
    # Setup
    mock_response = MediaItemResponse(
        id=123,
        workspace_id=1,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.VIDEO_MP4,
        status="processing",
        original_prompt="Test",
        gcs_uris=[],
        thumbnail_uris=[],
        presigned_urls=[],
        presigned_thumbnail_urls=[],
        aspect_ratio="16:9",
        model="veo-3.0-generate-001",
    )
    mock_veo_service.start_video_generation_job.return_value = mock_response

    payload = {
        "prompt": "A running horse",
        "workspace_id": 1,
        "generation_model": "veo-3.0-generate-001",
        "aspect_ratio": "16:9",
        "duration_seconds": 5,
    }

    response = client.post("/api/videos/generate-videos", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == 123
    mock_workspace_auth.authorize.assert_called_once()
    mock_veo_service.start_video_generation_job.assert_called_once()


def test_concatenate_videos_success(
    client, mock_veo_service, mock_workspace_auth
):
    # Setup
    mock_response = MediaItemResponse(
        id=456,
        workspace_id=1,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.VIDEO_MP4,
        status="processing",
        original_prompt="Concat",
        gcs_uris=[],
        thumbnail_uris=[],
        presigned_urls=[],
        presigned_thumbnail_urls=[],
        aspect_ratio="16:9",
        model="veo-3.0-generate-001",
    )
    mock_veo_service.start_video_concatenation_job.return_value = mock_response

    payload = {
        "name": "Concatenated Video",
        "workspace_id": 1,
        "inputs": [
            {"type": "media_item", "id": 1},
            {"type": "media_item", "id": 2},
        ],
        "aspect_ratio": "16:9",
    }

    response = client.post("/api/videos/concatenate", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == 456
    mock_workspace_auth.authorize.assert_called_once()
    mock_veo_service.start_video_concatenation_job.assert_called_once()


def test_generate_videos_value_error(client, mock_veo_service):
    # Setup service to raise ValueError
    mock_veo_service.start_video_generation_job.side_effect = ValueError(
        "Test ValueError message",
    )

    payload = {
        "prompt": "A running horse",
        "workspace_id": 1,
        "generation_model": "veo-3.0-generate-001",
        "aspect_ratio": "16:9",
        "duration_seconds": 5,
    }

    response = client.post("/api/videos/generate-videos", json=payload)

    assert response.status_code == 400
    assert "Test ValueError message" in response.json()["detail"]


def test_generate_videos_http_exception(client, mock_workspace_auth):
    from fastapi import HTTPException

    mock_workspace_auth.authorize.side_effect = HTTPException(
        status_code=403, detail="Forbidden workspace access"
    )

    payload = {
        "prompt": "A running horse",
        "workspace_id": 1,
        "generation_model": "veo-3.0-generate-001",
        "aspect_ratio": "16:9",
        "duration_seconds": 5,
    }

    response = client.post("/api/videos/generate-videos", json=payload)
    assert response.status_code == 403
    assert "Forbidden workspace access" in response.json()["detail"]


def test_generate_videos_general_exception(client, mock_veo_service):
    mock_veo_service.start_video_generation_job.side_effect = Exception(
        "System crash"
    )

    payload = {
        "prompt": "A running horse",
        "workspace_id": 1,
        "generation_model": "veo-3.0-generate-001",
        "aspect_ratio": "16:9",
        "duration_seconds": 5,
    }

    response = client.post("/api/videos/generate-videos", json=payload)
    assert response.status_code == 500
    assert "System crash" in response.json()["detail"]


def test_concatenate_videos_http_exception(client, mock_workspace_auth):
    from fastapi import HTTPException

    mock_workspace_auth.authorize.side_effect = HTTPException(
        status_code=403, detail="Forbidden workspace access"
    )

    payload = {
        "name": "Concatenated Video",
        "workspace_id": 1,
        "inputs": [
            {"type": "media_item", "id": 1},
            {"type": "media_item", "id": 2},
        ],
        "aspect_ratio": "16:9",
    }

    response = client.post("/api/videos/concatenate", json=payload)
    assert response.status_code == 403
    assert "Forbidden workspace access" in response.json()["detail"]


def test_concatenate_videos_general_exception(client, mock_veo_service):
    mock_veo_service.start_video_concatenation_job.side_effect = Exception(
        "Database is down"
    )

    payload = {
        "name": "Concatenated Video",
        "workspace_id": 1,
        "inputs": [
            {"type": "media_item", "id": 1},
            {"type": "media_item", "id": 2},
        ],
        "aspect_ratio": "16:9",
    }

    response = client.post("/api/videos/concatenate", json=payload)
    assert response.status_code == 500
    assert "Database is down" in response.json()["detail"]
