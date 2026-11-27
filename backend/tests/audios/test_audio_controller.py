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

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auth.auth_guard import get_current_user
from src.common.base_dto import MimeTypeEnum
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.users.user_model import UserModel
from src.audios.audio_controller import router
from src.audios.audio_service import AudioService
from src.audios.audio_stem_service import AudioStemService
from src.audios.dto.stem_audio_dto import (
    ExtractStemsResponseDto,
    StemNameEnum,
    StemPreviewItemDto,
)
from src.workspaces.workspace_auth_guard import WorkspaceAuth


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.fixture(name="mock_audio_service")
def fixture_mock_audio_service():
    service = AsyncMock()
    service.start_audio_generation_job = AsyncMock()
    return service


@pytest.fixture(name="mock_audio_stem_service")
def fixture_mock_audio_stem_service():
    service = AsyncMock()
    service.extract_stems = AsyncMock()
    service.get_stem_extraction_status = AsyncMock()
    service.save_stem_mix = AsyncMock()
    return service


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    auth = AsyncMock()
    auth.authorize = AsyncMock()
    auth.authorize_write = AsyncMock()
    return auth


@pytest.fixture(name="client")
def fixture_client(
    mock_user,
    mock_audio_service,
    mock_audio_stem_service,
    mock_workspace_auth,
):
    app = FastAPI()
    app.include_router(router)

    app.state.executor = MagicMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[AudioService] = lambda: mock_audio_service
    app.dependency_overrides[AudioStemService] = lambda: mock_audio_stem_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth

    return TestClient(app)


def test_generate_audio_success(
    client, mock_audio_service, mock_workspace_auth
):
    mock_response = MediaItemResponse(
        id=123,
        workspace_id=1,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.AUDIO_WAV,
        status="processing",
        original_prompt="Test",
        gcs_uris=[],
        thumbnail_uris=[],
        presigned_urls=[],
        presigned_thumbnail_urls=[],
        aspect_ratio="16:9",
        model="lyria-002",
    )
    mock_audio_service.start_audio_generation_job.return_value = mock_response

    payload = {
        "prompt": "Create an epic song",
        "workspace_id": 1,
        "model": "lyria-002",
        "sample_count": 1,
    }

    response = client.post("/api/audios/generate", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == 123
    mock_workspace_auth.authorize.assert_called_once()
    mock_audio_service.start_audio_generation_job.assert_called_once()
    request_dto = (
        mock_audio_service.start_audio_generation_job.call_args.kwargs[
            "request_dto"
        ]
    )
    assert request_dto.folder_id is None


AUDIO_PAYLOAD = {
    "prompt": "Create an epic song",
    "workspace_id": 1,
    "model": "lyria-002",
}


@pytest.mark.parametrize("folder_key", ["folderId", "folder_id"])
def test_generate_audio_accepts_folder_id(
    client, mock_audio_service, folder_key
):
    mock_audio_service.start_audio_generation_job.return_value = (
        MediaItemResponse(
            id=124,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.AUDIO_WAV,
            status="processing",
            gcs_uris=[],
            aspect_ratio="16:9",
            model="lyria-002",
        )
    )

    response = client.post(
        "/api/audios/generate", json={**AUDIO_PAYLOAD, folder_key: 42}
    )

    assert response.status_code == 200
    request_dto = (
        mock_audio_service.start_audio_generation_job.call_args.kwargs[
            "request_dto"
        ]
    )
    assert request_dto.folder_id == 42


@pytest.mark.parametrize("folder_id", [0, -1, "abc"])
def test_generate_audio_rejects_invalid_folder_id(
    client, mock_audio_service, folder_id
):
    response = client.post(
        "/api/audios/generate", json={**AUDIO_PAYLOAD, "folderId": folder_id}
    )

    assert response.status_code == 422
    mock_audio_service.start_audio_generation_job.assert_not_called()


@pytest.mark.parametrize(
    "override",
    [
        {"metadataGenerationModel": "../../publishers/google/models/foo"},
        {"metadataGenerationModel": "lyria-002"},
        {"workspaceId": 0},
        {"workspaceId": -5},
    ],
)
def test_generate_audio_rejects_unallowed_metadata_model_and_invalid_workspace_id(
    client, mock_audio_service, override
):
    response = client.post(
        "/api/audios/generate", json={**AUDIO_PAYLOAD, **override}
    )

    assert response.status_code == 422
    mock_audio_service.start_audio_generation_job.assert_not_called()


def test_generate_audio_rejects_unauthorized_403(
    client, mock_audio_service, mock_workspace_auth
):
    from fastapi import HTTPException

    mock_workspace_auth.authorize.side_effect = HTTPException(
        status_code=403, detail="Forbidden workspace access"
    )
    response = client.post("/api/audios/generate", json=AUDIO_PAYLOAD)
    assert response.status_code == 403
    mock_audio_service.start_audio_generation_job.assert_not_called()


def test_extract_stems_endpoint_authorizes_and_returns_stems(
    client, mock_audio_stem_service, mock_workspace_auth
):
    mock_audio_stem_service.extract_stems.return_value = (
        ExtractStemsResponseDto(
            cache_hit=True,
            source_name="Track 1",
            duration_seconds=30.0,
            stems=[
                StemPreviewItemDto(
                    name=StemNameEnum.VOCALS,
                    label="Vocals",
                    gcs_uri="gs://bucket/vocals.mp3",
                    presigned_url="https://signed.example/vocals.mp3",
                    peak_level=0.8,
                    has_energy=True,
                )
            ],
        )
    )

    response = client.post(
        "/api/audios/stems/extract",
        json={
            "workspaceId": 3,
            "source": {"id": 99, "type": "media_item", "index": 0},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cacheHit"] is True
    assert body["stems"][0]["name"] == "vocals"
    mock_workspace_auth.authorize.assert_called_once()
    mock_audio_stem_service.extract_stems.assert_called_once()


def test_get_stems_status_endpoint_authorizes_and_returns_status(
    client, mock_audio_stem_service, mock_workspace_auth
):
    mock_audio_stem_service.get_stem_extraction_status.return_value = (
        ExtractStemsResponseDto(
            status="processing",
            cache_hit=False,
            source_name="Track 1",
            stems=[],
        )
    )

    response = client.post(
        "/api/audios/stems/status",
        json={
            "workspaceId": 3,
            "source": {"id": 99, "type": "media_item", "index": 0},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["stems"] == []
    mock_workspace_auth.authorize.assert_called_once()
    mock_audio_stem_service.get_stem_extraction_status.assert_called_once()


def test_save_stem_mix_endpoint_validates_and_saves(
    client, mock_audio_stem_service, mock_workspace_auth
):
    mock_audio_stem_service.save_stem_mix.return_value = MediaItemResponse(
        id=777,
        workspace_id=3,
        user_id=1,
        user_email="test@example.com",
        mime_type=MimeTypeEnum.AUDIO_MPEG,
        status="completed",
        gcs_uris=["gs://bucket/stemmed_audio/mix.mp3"],
        presigned_urls=["https://signed.example/mix.mp3"],
        aspect_ratio="16:9",
        model="htdemucs-6s",
    )

    response = client.post(
        "/api/audios/stems/save",
        json={
            "workspaceId": 3,
            "source": {"id": 99, "type": "media_item", "index": 0},
            "selectedStems": ["drums", "bass"],
            "saveMode": "combined",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == 777
    assert response.json()["model"] == "htdemucs-6s"
    mock_workspace_auth.authorize.assert_called_once()
    mock_audio_stem_service.save_stem_mix.assert_called_once()

    # Empty selectedStems -> 422
    bad_response = client.post(
        "/api/audios/stems/save",
        json={
            "workspaceId": 3,
            "source": {"id": 99, "type": "media_item"},
            "selectedStems": [],
        },
    )
    assert bad_response.status_code == 422
