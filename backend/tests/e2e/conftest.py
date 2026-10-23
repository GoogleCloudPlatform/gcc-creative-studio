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
"""Conftest for E2E tests."""

import asyncio
import os
import shutil
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from src.auth.auth_guard import get_current_user
from src.common.storage_service import GcsService
from src.common.schema.genai_model_setup import GenAIModelSetup
from src.users.user_model import UserModel, UserRoleEnum


# --- 1. GCS Mock Methods ---


def mock_download_from_gcs(
    self, gcs_uri_path: str, destination_file_path: str
) -> str | None:
    os.makedirs(os.path.dirname(destination_file_path), exist_ok=True)
    with open(destination_file_path, "wb") as f:
        f.write(b"mock video data")
    return destination_file_path


def mock_download_bytes_from_gcs(self, gcs_uri: str) -> bytes | None:
    # 1x1 pixel PNG image bytes
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"


def mock_download_stream_from_gcs(self, gcs_uri: str):
    yield b"mock stream data"


def mock_upload_file_to_gcs(
    self, local_path: str, destination_blob_name: str, mime_type: str
) -> str:
    return f"gs://{self.bucket_name}/{destination_blob_name}"


def mock_upload_bytes_to_gcs(
    self, content_bytes: bytes, destination_blob_name: str, mime_type: str
) -> str:
    return f"gs://{self.bucket_name}/{destination_blob_name}"


def mock_store_to_gcs(
    self,
    folder: str,
    file_name: str,
    mime_type: str,
    contents,
    decode: bool = False,
    bucket_name: str | None = None,
) -> str:
    bucket = bucket_name or self.bucket_name
    return f"gs://{bucket}/{folder}/{file_name}"


def mock_delete_blob_from_uri(self, gcs_uri: str) -> bool:
    return True


def mock_generate_thumbnail(video_path: str) -> str | None:
    if not video_path:
        return None
    thumb_path = os.path.splitext(video_path)[0] + "_thumbnail.png"
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    with open(thumb_path, "wb") as f:
        f.write(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    return thumb_path


# --- 2. Gemini Mock Client ---


class MockGenAIClient:
    def __init__(self):
        self.models = MagicMock()
        self.aio = MagicMock()
        self.aio.models = MagicMock()
        self.operations = MagicMock()

        # dynamic generate_content mock
        def sync_gen(model, contents, config=None, **kwargs):
            if (
                config
                and getattr(config, "response_modalities", None) is not None
            ):
                modalities = [
                    m.upper() for m in getattr(config, "response_modalities")
                ]
                if "AUDIO" in modalities:
                    resp = MagicMock()
                    part = MagicMock()
                    part.inline_data.data = b"\x00" * 48000
                    resp.candidates = [
                        MagicMock(content=MagicMock(parts=[part]))
                    ]
                    return resp
                elif "IMAGE" in modalities:
                    resp = MagicMock()
                    part = MagicMock()
                    part.inline_data.mime_type = "image/png"
                    part.inline_data.data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQdGSmAAAADElEQVR42mP8z8AABQAB/gX72gAAAABJRU5ErkJggg=="
                    resp.candidates = [
                        MagicMock(
                            content=MagicMock(parts=[part]),
                            grounding_metadata=None,
                        )
                    ]
                    return resp

            resp = MagicMock()
            if (
                config
                and getattr(config, "response_mime_type", None)
                == "application/json"
            ):
                schema_str = str(getattr(config, "response_schema", ""))
                if "Title" in schema_str or "GenerateTitle" in schema_str:
                    resp.text = '{"title": "Mock Text Title", "summary": "Mock Text Summary"}'
                else:
                    resp.text = '{"items": [{"title": "Mock Media Title", "description": "Mock Media Description"}]}'
            else:
                resp.text = "Mock Multimodal Generated Content Text"
            return resp

        self.models.generate_content = sync_gen

        # async generate_content mock
        async def async_gen(model, contents, config=None, **kwargs):
            resp = MagicMock()
            resp.text = "Mock Multimodal Generated Content Text"
            return resp

        self.aio.models.generate_content = async_gen

        # generate_images & edit_image mocks
        mock_generated_image = MagicMock()
        mock_generated_image.image.gcs_uri = (
            "gs://mock-bucket/imagen_generated.png"
        )
        mock_generated_image.image.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.grounding_metadata = None
        mock_generated_image.candidates = [mock_candidate]

        img_resp = MagicMock()
        img_resp.generated_images = [mock_generated_image]
        self.models.generate_images.return_value = img_resp
        self.models.edit_image.return_value = img_resp

        # generate_videos mock
        mock_operation = MagicMock()
        mock_operation.name = "operation_123"
        mock_operation.done = True
        mock_operation.error = None

        mock_gen_video = MagicMock()
        mock_gen_video.video.uri = "gs://mock-bucket/veo_generated.mp4"

        mock_operation.response.generated_videos = [mock_gen_video]
        self.models.generate_videos.return_value = mock_operation
        self.operations.get.return_value = mock_operation


mock_client_instance = MockGenAIClient()


def mock_get_client(cls):
    return mock_client_instance


def mock_get_omni_client(cls):
    return mock_client_instance


def mock_init():
    return mock_client_instance


# --- 3. Autouse Session Mocks for GcsService & GenAI ---


@pytest.fixture(autouse=True, scope="session")
def setup_e2e_mocks():
    # Configure SQLAlchemy engine to use NullPool to prevent loop/thread sharing conflicts
    from sqlalchemy.pool import NullPool
    from sqlalchemy.ext.asyncio import create_async_engine
    import src.database
    import io
    import wave
    import base64
    from unittest.mock import patch, MagicMock

    test_engine = create_async_engine(
        src.database.get_conn_string(),
        poolclass=NullPool,
        echo=src.database.config_service.LOG_LEVEL == "DEBUG",
    )
    src.database.engine = test_engine
    src.database.async_session_local.configure(bind=test_engine)

    # Store originals
    orig_download = GcsService.download_from_gcs
    orig_download_bytes = GcsService.download_bytes_from_gcs
    orig_download_stream = GcsService.download_stream_from_gcs
    orig_upload_file = GcsService.upload_file_to_gcs
    orig_upload_bytes = GcsService.upload_bytes_to_gcs
    orig_store = GcsService.store_to_gcs
    orig_delete = GcsService.delete_blob_from_uri

    # Apply GcsService class method overrides
    GcsService.download_from_gcs = mock_download_from_gcs
    GcsService.download_bytes_from_gcs = mock_download_bytes_from_gcs
    GcsService.download_stream_from_gcs = mock_download_stream_from_gcs
    GcsService.upload_file_to_gcs = mock_upload_file_to_gcs
    GcsService.upload_bytes_to_gcs = mock_upload_bytes_to_gcs
    GcsService.store_to_gcs = mock_store_to_gcs
    GcsService.delete_blob_from_uri = mock_delete_blob_from_uri

    # Apply generate_thumbnail override
    import src.common.media_utils
    import src.videos.veo_service

    src.common.media_utils.generate_thumbnail = mock_generate_thumbnail
    src.videos.veo_service.generate_thumbnail = mock_generate_thumbnail

    # Apply GenAIModelSetup overrides
    orig_get_client = GenAIModelSetup.get_client
    orig_get_omni_client = GenAIModelSetup.get_omni_client
    orig_get_global_client = GenAIModelSetup.get_global_client
    orig_get_regional_client = GenAIModelSetup.get_regional_client
    orig_init = GenAIModelSetup.init

    GenAIModelSetup.get_client = classmethod(mock_get_client)
    GenAIModelSetup.get_omni_client = classmethod(mock_get_omni_client)
    GenAIModelSetup.get_global_client = classmethod(mock_get_client)
    GenAIModelSetup.get_regional_client = classmethod(mock_get_client)
    GenAIModelSetup.init = staticmethod(mock_init)
    GenAIModelSetup._client = mock_client_instance
    GenAIModelSetup._omni_client = mock_client_instance
    GenAIModelSetup._global_client = mock_client_instance

    # Patch Vertex AI Prediction Service & Text-to-Speech
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44100)
        wav_file.writeframes(b"\x00" * 88200)  # 1 second of silence
    dummy_wav_bytes = wav_buf.getvalue()
    dummy_wav_b64 = base64.b64encode(dummy_wav_bytes).decode("utf-8")

    class MockPredictionServiceClient:
        def __init__(self, *args, **kwargs):
            pass

        def predict(self, endpoint, instances, parameters, **kwargs):
            resp = MagicMock()
            resp.predictions = [{"bytesBase64Encoded": dummy_wav_b64}]
            return resp

    class MockTextToSpeechClient:
        def __init__(self, *args, **kwargs):
            pass

        def synthesize_speech(self, request, **kwargs):
            resp = MagicMock()
            resp.audio_content = dummy_wav_bytes
            return resp

    patcher_predict = patch(
        "google.cloud.aiplatform.gapic.PredictionServiceClient",
        MockPredictionServiceClient,
    )
    patcher_tts = patch(
        "google.cloud.texttospeech_v1beta1.TextToSpeechClient",
        MockTextToSpeechClient,
    )
    patcher_predict.start()
    patcher_tts.start()

    yield mock_client_instance

    # Stop patches
    patcher_predict.stop()
    patcher_tts.stop()

    # Restore GcsService
    GcsService.download_from_gcs = orig_download
    GcsService.download_bytes_from_gcs = orig_download_bytes
    GcsService.download_stream_from_gcs = orig_download_stream
    GcsService.upload_file_to_gcs = orig_upload_file
    GcsService.upload_bytes_to_gcs = orig_upload_bytes
    GcsService.store_to_gcs = orig_store
    GcsService.delete_blob_from_uri = orig_delete

    # Restore GenAIModelSetup
    GenAIModelSetup.get_client = orig_get_client
    GenAIModelSetup.get_omni_client = orig_get_omni_client
    GenAIModelSetup.get_global_client = orig_get_global_client
    GenAIModelSetup.get_regional_client = orig_get_regional_client
    GenAIModelSetup.init = orig_init
    GenAIModelSetup._client = None
    GenAIModelSetup._omni_client = None
    GenAIModelSetup._global_client = None


# --- 4. Authenticated Clients Fixtures ---


async def _create_e2e_api_client(user_model):
    from src.database import async_session_local
    from src.users.user_model import User
    from sqlalchemy import select

    async with async_session_local() as session:
        res = await session.execute(
            select(User).where(User.id == user_model.id)
        )
        u = res.scalar_one_or_none()
        if not u:
            new_user = User(
                id=user_model.id,
                email=user_model.email,
                roles=[
                    r.value if hasattr(r, "value") else r
                    for r in user_model.roles
                ],
                name=user_model.name,
                picture=user_model.picture,
            )
            session.add(new_user)
            await session.commit()

    def override_get_current_user():
        return user_model

    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="e2e_client")
async def fixture_e2e_client(mock_user):
    async for client in _create_e2e_api_client(mock_user):
        yield client


@pytest.fixture(name="e2e_admin_client")
async def fixture_e2e_admin_client(mock_admin):
    async for client in _create_e2e_api_client(mock_admin):
        yield client


@pytest.fixture(name="e2e_creator_client")
async def fixture_e2e_creator_client(mock_creator):
    async for client in _create_e2e_api_client(mock_creator):
        yield client


@pytest.fixture(name="e2e_unauthenticated_client")
def fixture_e2e_unauthenticated_client():
    with TestClient(app) as client:
        yield client


# --- 5. Workspace Lifecycle Fixture ---


@pytest.fixture(name="e2e_test_workspace")
async def fixture_e2e_test_workspace(e2e_client):
    # Create workspace
    resp = e2e_client.post(
        "/api/workspaces", json={"name": "E2E Temporary Test Workspace"}
    )
    assert resp.status_code == 201
    workspace_data = resp.json()
    workspace_id = workspace_data["id"]

    yield workspace_id

    # Teardown: cascade delete from database
    from src.database import async_session_local
    from src.workspaces.schema.workspace_model import (
        Workspace,
        WorkspaceMemberAssociation,
    )
    from src.common.schema.media_item_model import MediaItem
    from src.source_assets.schema.source_asset_model import SourceAsset
    from src.brand_guidelines.schema.brand_guideline_model import BrandGuideline
    from sqlalchemy import delete

    async with async_session_local() as session:
        await session.execute(
            delete(BrandGuideline).where(
                BrandGuideline.workspace_id == workspace_id
            )
        )
        await session.execute(
            delete(MediaItem).where(MediaItem.workspace_id == workspace_id)
        )
        await session.execute(
            delete(SourceAsset).where(SourceAsset.workspace_id == workspace_id)
        )
        await session.execute(
            delete(WorkspaceMemberAssociation).where(
                WorkspaceMemberAssociation.workspace_id == workspace_id
            )
        )
        await session.execute(
            delete(Workspace).where(Workspace.id == workspace_id)
        )
        await session.commit()


# --- 6. Engine Disposal Autouse Fixture ---


@pytest.fixture(autouse=True)
async def dispose_db_engine():
    yield
    from src.database import engine

    await engine.dispose()
