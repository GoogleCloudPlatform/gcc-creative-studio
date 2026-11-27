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

import base64
from contextlib import contextmanager
import io
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import wave
from pydantic import ValidationError
import pytest
from fastapi import HTTPException

from src.common.base_dto import AssetReferenceDto, GenerationModelEnum
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    MediaItemModel,
    MimeTypeEnum,
    JobStatusEnum,
    SourceMediaItemLink,
)
from src.source_assets.schema.source_asset_model import AssetScopeEnum
from src.users.user_model import UserModel
from src.audios.dto.create_audio_dto import CreateAudioDto, LYRIA_MAX_SEED
from src.audios.audio_service import (
    LYRIA_3_CONTENT_BLOCKED_MESSAGE,
    LYRIA_3_CONTENT_BLOCKED_NO_RETRY_MESSAGE,
    MAX_AUDIO_ITERATION_STEPS,
    AudioGenerationError,
    AudioService,
    _build_lyria3_prompt,
    _extract_lyria3_audio,
    _extract_lyria3_text,
    _has_lyria3_vocal_intent,
    _is_lyria3_content_blocked,
    _is_valid_int_seed,
    _process_audio_in_background,
    _resolve_lyria3_reference_images,
    _resolve_reference_audio,
    _simplify_lyria3_prompt,
)
from src.audios.audio_constants import LanguageEnum, VoiceEnum


@pytest.fixture(name="mock_media_repo")
def fixture_mock_media_repo():
    repo = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    repo.db = MagicMock()
    repo.db.execute = AsyncMock(return_value=execute_result)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    return repo


@pytest.fixture(name="audio_service")
def fixture_audio_service(mock_media_repo):
    return AudioService(
        media_repo=mock_media_repo,
        iam_signer_credentials=MagicMock(),
    )


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.fixture(name="sample_create_lyria_dto")
def fixture_sample_create_lyria_dto():
    return CreateAudioDto(
        workspace_id=1,
        prompt="A cute cat running",
        model=GenerationModelEnum.LYRIA_002,
        sample_count=1,
    )


@pytest.fixture(name="sample_create_tts_dto")
def fixture_sample_create_tts_dto():
    return CreateAudioDto(
        workspace_id=1,
        prompt="Sample speech text",
        model=GenerationModelEnum.CHIRP_3,
        language_code=LanguageEnum.EN_US,
        voice_name=VoiceEnum.PUCK,
    )


class TestAudioServiceMethods:

    @pytest.fixture(autouse=True)
    def _mock_generation_workspace(self):
        personal_ws = MagicMock(id=1, scope="personal")
        with (
            patch(
                "src.workspaces.generation_workspace.WorkspaceRepository"
            ) as repo_cls,
            patch(
                "src.workspaces.generation_workspace.WorkspaceAuth"
            ) as auth_cls,
            patch(
                "src.workspaces.generation_workspace.resolve_output_folder_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            repo_cls.return_value.ensure_personal_workspace = AsyncMock(
                return_value=personal_ws
            )
            auth_cls.return_value.authorize = AsyncMock(
                return_value=personal_ws
            )
            yield repo_cls, auth_cls

    @pytest.mark.anyio
    async def test_start_audio_generation_job_success(
        self,
        audio_service,
        mock_media_repo,
        sample_create_lyria_dto,
        sample_user,
    ):
        placeholder = MediaItemModel(
            id=123,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.AUDIO_WAV,
            model=GenerationModelEnum.LYRIA_002,
            aspect_ratio="16:9",
            gcs_uris=[],
            thumbnail_uris=[],
        )
        mock_media_repo.create.return_value = placeholder
        mock_executor = MagicMock()

        response = await audio_service.start_audio_generation_job(
            request_dto=sample_create_lyria_dto,
            user=sample_user,
            executor=mock_executor,
        )

        assert response is not None
        assert response.id == 123
        mock_media_repo.create.assert_called_once()
        saved_lyria_model = mock_media_repo.create.call_args[0][0]
        assert saved_lyria_model.voice_name is None
        assert saved_lyria_model.language_code is None
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    @pytest.mark.parametrize("requested_folder_id", [42, None])
    async def test_start_audio_generation_job_uses_resolved_output_folder(
        self,
        requested_folder_id,
        audio_service,
        mock_media_repo,
        sample_create_lyria_dto,
        sample_user,
    ):
        request_dto = sample_create_lyria_dto.model_copy(
            update={"folder_id": requested_folder_id}
        )

        async def _create(item):
            item.id = 900
            return item

        mock_media_repo.create.side_effect = _create
        mock_executor = MagicMock()

        with patch(
            "src.workspaces.generation_workspace.resolve_output_folder_id",
            AsyncMock(return_value=77),
        ) as resolver:
            response = await audio_service.start_audio_generation_job(
                request_dto=request_dto,
                user=sample_user,
                executor=mock_executor,
            )

        resolver.assert_awaited_once_with(
            mock_media_repo.db, 1, sample_user, requested_folder_id
        )
        assert mock_media_repo.create.call_args.args[0].folder_id == 77
        assert response.folder_id == 77
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_start_audio_generation_job_invalid_folder_creates_nothing(
        self,
        audio_service,
        mock_media_repo,
        sample_create_lyria_dto,
        sample_user,
    ):
        request_dto = sample_create_lyria_dto.model_copy(
            update={"folder_id": 999}
        )
        mock_executor = MagicMock()

        with (
            patch(
                "src.workspaces.generation_workspace.resolve_output_folder_id",
                AsyncMock(
                    side_effect=HTTPException(
                        status_code=422, detail="Folder not found"
                    )
                ),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await audio_service.start_audio_generation_job(
                request_dto=request_dto,
                user=sample_user,
                executor=mock_executor,
            )

        assert exc_info.value.status_code == 422
        mock_media_repo.create.assert_not_called()
        mock_executor.submit.assert_not_called()

    @pytest.mark.anyio
    async def test_start_audio_generation_job_tts_keeps_voice_and_language(
        self,
        audio_service,
        mock_media_repo,
        sample_create_tts_dto,
        sample_user,
    ):
        placeholder = MediaItemModel(
            id=124,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.AUDIO_WAV,
            model=GenerationModelEnum.CHIRP_3,
            aspect_ratio="16:9",
            voice_name=VoiceEnum.PUCK,
            language_code=LanguageEnum.EN_US,
            gcs_uris=[],
            thumbnail_uris=[],
        )
        mock_media_repo.create.return_value = placeholder
        mock_executor = MagicMock()

        await audio_service.start_audio_generation_job(
            request_dto=sample_create_tts_dto,
            user=sample_user,
            executor=mock_executor,
        )

        saved_tts_model = mock_media_repo.create.call_args[0][0]
        assert saved_tts_model.voice_name == VoiceEnum.PUCK
        assert saved_tts_model.language_code == LanguageEnum.EN_US

    @pytest.mark.anyio
    async def test_start_audio_generation_job_routes_shared_ws_to_personal(
        self,
        _mock_generation_workspace,
        audio_service,
        mock_media_repo,
        sample_create_lyria_dto,
        sample_user,
    ):
        repo_cls, auth_cls = _mock_generation_workspace
        shared_ws = MagicMock(id=30, scope="private")
        personal_ws = MagicMock(id=10, scope="personal")
        auth_cls.return_value.authorize.return_value = shared_ws
        repo_cls.return_value.ensure_personal_workspace.return_value = (
            personal_ws
        )

        async def _create(item):
            item.id = 901
            return item

        mock_media_repo.create.side_effect = _create
        mock_executor = MagicMock()

        response = await audio_service.start_audio_generation_job(
            request_dto=sample_create_lyria_dto.model_copy(
                update={"workspace_id": 30}
            ),
            user=sample_user,
            executor=mock_executor,
        )

        assert mock_media_repo.create.call_args.args[0].workspace_id == 10
        assert response.workspace_id == 10
        submitted_dto = mock_executor.submit.call_args.args[2]
        assert submitted_dto.workspace_id == 10

    @pytest.mark.anyio
    async def test_start_audio_generation_job_authorizes_cross_workspace_inputs(
        self,
        _mock_generation_workspace,
        audio_service,
        mock_media_repo,
        sample_user,
    ):
        repo_cls, auth_cls = _mock_generation_workspace
        personal_ws = MagicMock(id=10, scope="personal")
        auth_cls.return_value.authorize.return_value = personal_ws
        repo_cls.return_value.ensure_personal_workspace.return_value = (
            personal_ws
        )

        async def _create(item):
            item.id = 902
            return item

        mock_media_repo.create.side_effect = _create
        mock_executor = MagicMock()

        dto = CreateAudioDto(
            workspace_id=10,
            prompt="Add brighter synth pads",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            source_asset_ids=[71],
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=81, media_index=0, role=AssetRoleEnum.INPUT
                )
            ],
            reference_audio=AssetReferenceDto(
                id=82, type="media_item", index=0
            ),
        )

        with patch(
            "src.audios.audio_service.ensure_can_reference_inputs",
            new=AsyncMock(return_value={30, 40}),
        ) as mock_ref_auth:
            await audio_service.start_audio_generation_job(
                request_dto=dto,
                user=sample_user,
                executor=mock_executor,
            )

        mock_ref_auth.assert_awaited_once_with(
            mock_media_repo.db,
            sample_user,
            media_item_ids=[81, 82],
            source_asset_ids=[71],
        )
        allowed_ws = mock_executor.submit.call_args.args[5]
        assert allowed_ws == frozenset({10, 30, 40})

        # Unauthorized reference input fails closed with 403 before creating a job row.
        mock_media_repo.create.reset_mock()
        mock_executor.submit.reset_mock()
        with patch(
            "src.audios.audio_service.ensure_can_reference_inputs",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await audio_service.start_audio_generation_job(
                    request_dto=dto,
                    user=sample_user,
                    executor=mock_executor,
                )
        assert exc.value.status_code == 403
        mock_media_repo.create.assert_not_awaited()
        mock_executor.submit.assert_not_called()

    @pytest.mark.anyio
    async def test_cross_workspace_audio_and_image_references_resolve_for_personal_output(
        self,
    ):
        media_repo = AsyncMock()
        asset_repo = AsyncMock()

        shared_audio = SimpleNamespace(
            id=82,
            workspace_id=30,
            deleted_at=None,
            status=JobStatusEnum.COMPLETED,
            gcs_uris=["gs://bucket/shared-track.wav"],
            mime_type=MimeTypeEnum.AUDIO_WAV,
            prompt="Warm lo-fi beat",
            original_prompt="Warm lo-fi beat",
            audio_analysis=None,
            seed=None,
        )
        shared_image_item = SimpleNamespace(
            id=81,
            workspace_id=30,
            deleted_at=None,
            status=JobStatusEnum.COMPLETED,
            gcs_uris=["gs://bucket/shared-cover.png"],
            mime_type=MimeTypeEnum.IMAGE_PNG,
        )
        shared_image_asset = SimpleNamespace(
            id=71,
            workspace_id=30,
            deleted_at=None,
            scope=AssetScopeEnum.PRIVATE,
            gcs_uri="gs://bucket/shared-ref.png",
            mime_type=MimeTypeEnum.IMAGE_PNG,
        )
        media_repo.get_by_id.side_effect = lambda mid: (
            shared_audio if mid == 82 else shared_image_item
        )
        asset_repo.get_by_id.return_value = shared_image_asset

        # Worker DTO targets personal workspace 10 while inputs live in authorized shared workspace 30.
        worker_dto = CreateAudioDto(
            workspace_id=10,
            prompt="Iterate with acoustic guitar",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            source_asset_ids=[71],
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=81, media_index=0, role=AssetRoleEnum.INPUT
                )
            ],
            reference_audio=AssetReferenceDto(
                id=82, type="media_item", index=0
            ),
        )
        allowed = frozenset({10, 30})

        img_inputs, asset_links, media_links = (
            await _resolve_lyria3_reference_images(
                worker_dto,
                media_repo,
                asset_repo,
                allowed_workspace_ids=allowed,
            )
        )
        assert len(img_inputs) == 2
        assert [a.asset_id for a in asset_links] == [71]
        assert [m.media_item_id for m in media_links] == [81]

        ref_ctx, ref_asset, ref_media = await _resolve_reference_audio(
            worker_dto, media_repo, asset_repo, allowed_workspace_ids=allowed
        )
        assert ref_ctx["uri"] == "gs://bucket/shared-track.wav"
        assert ref_asset is None
        assert ref_media is not None and ref_media.media_item_id == 82

        # Without workspace 30 authorized, both resolvers reject fail-closed.
        with pytest.raises(
            AudioGenerationError, match="not found in this workspace"
        ):
            await _resolve_reference_audio(
                worker_dto,
                media_repo,
                asset_repo,
                allowed_workspace_ids=frozenset({10}),
            )
        with pytest.raises(
            AudioGenerationError, match="not found in this workspace"
        ):
            await _resolve_lyria3_reference_images(
                worker_dto,
                media_repo,
                asset_repo,
                allowed_workspace_ids=frozenset({10}),
            )


class TestBackgroundWorkers:

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.aiplatform.gapic.PredictionServiceClient")
    @patch("src.audios.audio_service.GcsService")
    def test_process_lyria_in_background_sync(
        self,
        mock_gcs,
        mock_aiplatform,
        mock_repo_cls,
        mock_worker_db,
        sample_create_lyria_dto,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_session = AsyncMock()
        mock_db_factory.return_value.__aenter__.return_value = mock_db_session

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_gcs_singleton = MagicMock()
        mock_gcs_singleton.store_to_gcs.return_value = "gs://foo/bar.wav"
        mock_gcs.return_value = mock_gcs_singleton

        mock_ai_instance = MagicMock()
        mock_ai_instance.predict.return_value = MagicMock(
            predictions=[{"bytesBase64Encoded": "SGVsbG8="}]
        )
        mock_aiplatform.return_value = mock_ai_instance

        with patch(
            "src.audios.audio_service.random.randint", return_value=424242
        ):
            _process_audio_in_background(
                media_item_id=123,
                request_dto=sample_create_lyria_dto,
                user_email=sample_user.email,
                user_id=sample_user.id,
            )

        mock_repo.update.assert_called_with(
            123,
            {
                "status": JobStatusEnum.COMPLETED,
                "gcs_uris": ["gs://foo/bar.wav"],
                "generation_time": pytest.approx(
                    0, abs=10.0
                ),  # loose assertion
                "seed": 424242,
                "audio_analysis": {
                    "tracks": [{"seed": 424242}],
                    "iteration_steps": ["A cute cat running"],
                },
            },
        )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.texttospeech.TextToSpeechClient")
    @patch("src.audios.audio_service.GcsService")
    def test_process_tts_in_background_sync(
        self,
        mock_gcs,
        mock_tts_client,
        mock_repo_cls,
        mock_worker_db,
        sample_create_tts_dto,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_session = AsyncMock()
        mock_db_factory.return_value.__aenter__.return_value = mock_db_session

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_gcs_singleton = MagicMock()
        mock_gcs_singleton.store_to_gcs.return_value = "gs://foo/tts.wav"
        mock_gcs.return_value = mock_gcs_singleton

        mock_tts_instance = MagicMock()
        mock_tts_instance.synthesize_speech.return_value = MagicMock(
            audio_content=b"123"
        )
        mock_tts_client.return_value = mock_tts_instance

        _process_audio_in_background(
            media_item_id=125,
            request_dto=sample_create_tts_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        mock_repo.update.assert_called_with(
            125,
            {
                "status": JobStatusEnum.COMPLETED,
                "gcs_uris": ["gs://foo/tts.wav"],
                "generation_time": pytest.approx(0, abs=10.0),
            },
        )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_process_gemini_in_background_sync(
        self,
        mock_gcs,
        mock_genai,
        mock_repo_cls,
        mock_worker_db,
        sample_user,
    ):
        gemini_dto = CreateAudioDto(
            workspace_id=1,
            prompt="Gemini prompt",
            model=GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
            sample_count=1,
            language_code=LanguageEnum.EN_US,
            voice_name=VoiceEnum.AOEDE,
        )

        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_session = AsyncMock()
        mock_db_factory.return_value.__aenter__.return_value = mock_db_session

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_gcs_singleton = MagicMock()
        mock_gcs_singleton.store_to_gcs.return_value = "gs://foo/gemini.wav"
        mock_gcs.return_value = mock_gcs_singleton

        mock_client = MagicMock()
        mock_content = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = "SGVsbG8="  # Base64
        mock_content.parts = [mock_part]

        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_client.models.generate_content.return_value = MagicMock(
            candidates=[mock_candidate]
        )
        mock_genai.init.return_value = mock_client

        _process_audio_in_background(
            media_item_id=126,
            request_dto=gemini_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        mock_repo.update.assert_called_once()
        updated_id, updated_payload = mock_repo.update.call_args[0]
        assert updated_id == 126
        assert updated_payload["status"] == JobStatusEnum.COMPLETED
        assert updated_payload["gcs_uris"] == ["gs://foo/gemini.wav"]
        assert updated_payload["generation_time"] == pytest.approx(0, abs=10.0)
        assert len(updated_payload["audio_analysis"]["tracks"]) == 1
        assert (
            len(updated_payload["audio_analysis"]["tracks"][0]["waveform"])
            == 120
        )
        mock_client.models.generate_content.assert_called_once()
        _, call_kwargs = mock_client.models.generate_content.call_args
        called_config = call_kwargs.get("config")
        assert called_config is not None
        assert (
            called_config.speech_config.voice_config.prebuilt_voice_config.voice_name
            == "Aoede"
        )

    def test_new_audio_models_validation(self):
        lyria3_dto = CreateAudioDto(
            workspace_id=1,
            prompt="Lyria 3 prompt",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            sample_count=1,
        )
        assert lyria3_dto.model == GenerationModelEnum.LYRIA_3_CLIP_PREVIEW

        gemini31_dto = CreateAudioDto(
            workspace_id=1,
            prompt="Gemini 3.1 prompt",
            model=GenerationModelEnum.GEMINI_3_1_FLASH_TTS_PREVIEW,
            language_code=LanguageEnum.EN_US,
            voice_name=VoiceEnum.PUCK,
        )
        assert (
            gemini31_dto.model
            == GenerationModelEnum.GEMINI_3_1_FLASH_TTS_PREVIEW
        )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_process_lyria3_in_background_uses_interactions_api(
        self,
        mock_gcs,
        mock_genai_setup,
        mock_repo_cls,
        mock_worker_db,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_session = AsyncMock()
        mock_db_factory.return_value.__aenter__.return_value = mock_db_session

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_gcs_singleton = MagicMock()
        mock_gcs_singleton.store_to_gcs.return_value = "gs://foo/lyria3.mp3"
        mock_gcs.return_value = mock_gcs_singleton

        interaction = MagicMock()
        interaction.id = "int-1"
        interaction.output_audio = MagicMock(
            type="audio", mime_type="audio/mpeg", data="SGVsbG8="
        )
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = interaction
        mock_genai_setup.get_omni_client.return_value = mock_client

        lyria3_dto = CreateAudioDto(
            workspace_id=1,
            prompt="Warm lo-fi beat",
            negative_prompt="vocals",
            model=GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
            sample_count=2,
        )

        _process_audio_in_background(
            media_item_id=127,
            request_dto=lyria3_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        # Lyria 3 must never go through the legacy :predict client.
        mock_genai_setup.get_omni_client.assert_called_once()
        assert mock_client.interactions.create.call_count == 2
        _, call_kwargs = mock_client.interactions.create.call_args
        assert call_kwargs["model"] == "lyria-3-pro-preview"
        assert call_kwargs["input"] == [
            {"type": "text", "text": "Warm lo-fi beat\n\nAvoid: vocals"}
        ]
        assert call_kwargs["timeout"] == AudioService.LYRIA_3_TIMEOUT_SECONDS

        store_kwargs = mock_gcs_singleton.store_to_gcs.call_args.kwargs
        assert store_kwargs["file_name"].endswith(".mp3")
        assert store_kwargs["mime_type"] == "audio/mpeg"
        assert store_kwargs["contents"] == b"Hello"

        mock_repo.update.assert_called_with(
            127,
            {
                "status": JobStatusEnum.COMPLETED,
                "gcs_uris": ["gs://foo/lyria3.mp3", "gs://foo/lyria3.mp3"],
                "generation_time": pytest.approx(0, abs=10.0),
                "mime_type": MimeTypeEnum.AUDIO_MPEG,
                "audio_analysis": {"iteration_steps": ["Warm lo-fi beat"]},
            },
        )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_process_lyria3_in_background_fails_without_audio(
        self,
        mock_gcs,
        mock_genai_setup,
        mock_repo_cls,
        mock_worker_db,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_factory.return_value.__aenter__.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        interaction = MagicMock(output_audio=None, steps=[], outputs=[])
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = interaction
        mock_genai_setup.get_omni_client.return_value = mock_client

        lyria3_dto = CreateAudioDto(
            workspace_id=1,
            prompt="Silence",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            sample_count=1,
        )

        _process_audio_in_background(
            media_item_id=128,
            request_dto=lyria3_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        mock_gcs.return_value.store_to_gcs.assert_not_called()
        mock_repo.update.assert_called_with(
            128,
            {
                "status": JobStatusEnum.FAILED,
                "error_message": "Failed to generate any audio samples.",
            },
        )

    # The exact brief Lyria 3 refused in a real Ads-X run (media item 75).
    BLOCKED_PROMPT = (
        "A pulsing, heavy synthwave bassline paired with sharp, high-tempo "
        "electronic beats, accented by deep, resonant mechanical swells that "
        "evoke a powerful engine roaring to life. Instrumental only: no "
        "vocals, no singing, no spoken word, no lyrics. This is a background "
        "bed beneath a separate voiceover."
    )
    BLOCKED_ERROR = Exception(
        "Error code: 400 - {'error': {'message': 'Request blocked for an "
        "unspecified policy reason. Please modify your input and retry.', "
        "'code': 'content_blocked'}}"
    )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_process_lyria3_retries_with_simplified_prompt_when_blocked(
        self,
        mock_gcs,
        mock_genai_setup,
        mock_repo_cls,
        mock_worker_db,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_factory.return_value.__aenter__.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_gcs_singleton = MagicMock()
        mock_gcs_singleton.store_to_gcs.return_value = "gs://foo/retry.mp3"
        mock_gcs.return_value = mock_gcs_singleton

        interaction = MagicMock()
        interaction.id = "int-retry"
        interaction.output_audio = MagicMock(
            type="audio", mime_type="audio/mpeg", data="SGVsbG8="
        )
        mock_client = MagicMock()
        # First call: policy refusal. Second call (reworded brief): success.
        mock_client.interactions.create.side_effect = [
            self.BLOCKED_ERROR,
            interaction,
        ]
        mock_genai_setup.get_omni_client.return_value = mock_client

        lyria3_dto = CreateAudioDto(
            workspace_id=1,
            prompt=self.BLOCKED_PROMPT,
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            sample_count=1,
        )

        _process_audio_in_background(
            media_item_id=129,
            request_dto=lyria3_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        assert mock_client.interactions.create.call_count == 2
        first_call, second_call = mock_client.interactions.create.call_args_list
        assert first_call.kwargs["input"][0]["text"] == self.BLOCKED_PROMPT
        retry_text = second_call.kwargs["input"][0]["text"]
        assert retry_text == _simplify_lyria3_prompt(self.BLOCKED_PROMPT)
        assert "engine roaring" not in retry_text
        assert "voiceover" not in retry_text
        # Retry stays on Lyria 3 - never falls back to another model.
        assert second_call.kwargs["model"] == "lyria-3-clip-preview"

        mock_repo.update.assert_called_with(
            129,
            {
                "status": JobStatusEnum.COMPLETED,
                "gcs_uris": ["gs://foo/retry.mp3"],
                "generation_time": pytest.approx(0, abs=10.0),
                "mime_type": MimeTypeEnum.AUDIO_MPEG,
                "prompt": retry_text,
                "audio_analysis": {"iteration_steps": [self.BLOCKED_PROMPT]},
            },
        )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_process_lyria3_reports_content_blocked_when_retry_also_blocked(
        self,
        mock_gcs,
        mock_genai_setup,
        mock_repo_cls,
        mock_worker_db,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_factory.return_value.__aenter__.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = self.BLOCKED_ERROR
        mock_genai_setup.get_omni_client.return_value = mock_client

        lyria3_dto = CreateAudioDto(
            workspace_id=1,
            prompt=self.BLOCKED_PROMPT,
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            sample_count=1,
        )

        _process_audio_in_background(
            media_item_id=130,
            request_dto=lyria3_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        # Exactly one reword retry, then give up with an actionable message.
        assert mock_client.interactions.create.call_count == 2
        mock_gcs.return_value.store_to_gcs.assert_not_called()
        mock_repo.update.assert_called_with(
            130,
            {
                "status": JobStatusEnum.FAILED,
                "error_message": LYRIA_3_CONTENT_BLOCKED_MESSAGE,
            },
        )

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_process_lyria3_does_not_retry_other_errors(
        self,
        mock_gcs,
        mock_genai_setup,
        mock_repo_cls,
        mock_worker_db,
        sample_user,
    ):
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_factory.return_value.__aenter__.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = RuntimeError("quota")
        mock_genai_setup.get_omni_client.return_value = mock_client

        lyria3_dto = CreateAudioDto(
            workspace_id=1,
            prompt=self.BLOCKED_PROMPT,
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            sample_count=1,
        )

        _process_audio_in_background(
            media_item_id=131,
            request_dto=lyria3_dto,
            user_email=sample_user.email,
            user_id=sample_user.id,
        )

        mock_client.interactions.create.assert_called_once()
        mock_gcs.return_value.store_to_gcs.assert_not_called()
        mock_repo.update.assert_called_with(
            131,
            {
                "status": JobStatusEnum.FAILED,
                "error_message": "Failed to generate any audio samples.",
            },
        )


class TestLyria3Helpers:

    def test_model_sets_are_partitioned(self):
        assert AudioService.LYRIA_2_MODELS == {GenerationModelEnum.LYRIA_002}
        assert AudioService.LYRIA_3_MODELS == {
            GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        }
        assert AudioService.MUSIC_MODELS == (
            AudioService.LYRIA_2_MODELS | AudioService.LYRIA_3_MODELS
        )

    def test_build_prompt_without_negative(self):
        dto = CreateAudioDto(
            workspace_id=1,
            prompt="  Upbeat synthwave  ",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        )
        assert _build_lyria3_prompt(dto) == "Upbeat synthwave"

    def test_build_prompt_folds_negative_prompt(self):
        dto = CreateAudioDto(
            workspace_id=1,
            prompt="Upbeat synthwave",
            negative_prompt=" drums ",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        )
        assert _build_lyria3_prompt(dto) == "Upbeat synthwave\n\nAvoid: drums"

    def test_is_content_blocked_detects_code_attribute_and_message(self):
        with_code = Exception("blocked")
        with_code.code = "content_blocked"  # type: ignore[attr-defined]
        assert _is_lyria3_content_blocked(with_code)
        assert _is_lyria3_content_blocked(
            Exception("400 {'error': {'code': 'content_blocked'}}")
        )
        assert not _is_lyria3_content_blocked(Exception("recitation"))
        assert not _is_lyria3_content_blocked(RuntimeError("quota"))

    def test_simplify_prompt_keeps_style_head_only(self):
        simplified = _simplify_lyria3_prompt(
            "A pulsing, heavy synthwave bassline paired with sharp beats that "
            "evoke an engine roaring. Instrumental only: no vocals. This is a "
            "bed beneath a separate voiceover."
        )
        assert simplified.startswith("A pulsing, heavy synthwave bassline.")
        assert "engine" not in simplified
        assert "voiceover" not in simplified
        assert simplified.endswith("no vocals.")

    def test_simplify_prompt_caps_long_heads(self):
        head = " ".join(f"word{i}" for i in range(20))
        simplified = _simplify_lyria3_prompt(head)
        assert simplified.startswith(" ".join(f"word{i}" for i in range(12)))
        assert "word12" not in simplified

    def test_simplify_prompt_returns_empty_when_nothing_usable(self):
        assert _simplify_lyria3_prompt("") == ""
        assert _simplify_lyria3_prompt("   ") == ""
        assert _simplify_lyria3_prompt("with drums") == ""

    def test_has_vocal_intent_distinguishes_vocals_from_negated_phrases(self):
        assert not _has_lyria3_vocal_intent(
            "Instrumental only: no vocals, no singing, no spoken word, "
            "no lyrics. Background bed beneath a separate voiceover."
        )
        assert not _has_lyria3_vocal_intent(
            "Clean electric guitar with chorus pedal, without singing or vocals"
        )
        assert not _has_lyria3_vocal_intent("Non-vocal ambient synth pad")
        assert _has_lyria3_vocal_intent(
            "90s R&B ballad with emotional female vocals"
        )
        assert _has_lyria3_vocal_intent(
            "Upbeat indie pop, Female Alto\n\nLyrics:\n[Chorus]\nStay tonight"
        )
        assert _has_lyria3_vocal_intent("Verse 1: Walking down the avenue")

    def test_extract_prefers_sdk_output_audio(self):
        interaction = MagicMock()
        interaction.output_audio = MagicMock(
            type="audio", mime_type="audio/mp3", data="SGVsbG8="
        )
        audio, mime = _extract_lyria3_audio(interaction)
        assert audio == b"Hello"
        # audio/mp3 is normalised to the canonical audio/mpeg.
        assert mime == "audio/mpeg"

    def test_extract_falls_back_to_steps_content(self):
        text_item = MagicMock(type="text", text="lyrics", data=None)
        audio_item = MagicMock(type="audio", mime_type=None, data=b"\x00\x01")
        step = MagicMock(type="model_output", content=[text_item, audio_item])
        interaction = MagicMock(output_audio=None, steps=[step], outputs=None)
        audio, mime = _extract_lyria3_audio(interaction)
        assert audio == b"\x00\x01"
        assert mime == "audio/mpeg"

    def test_extract_handles_raw_rest_dict(self):
        interaction = {
            "status": "completed",
            "outputs": [
                {"type": "text", "text": "Caption"},
                {"type": "audio", "mime_type": "audio/wav", "data": "SGk="},
            ],
        }
        audio, mime = _extract_lyria3_audio(interaction)
        assert audio == b"Hi"
        assert mime == "audio/wav"

    def test_extract_returns_none_without_audio(self):
        interaction = {"outputs": [{"type": "text", "text": "only text"}]}
        audio, mime = _extract_lyria3_audio(interaction)
        assert audio is None
        assert mime == "audio/mpeg"


@contextmanager
def _audio_worker_env(
    *,
    gcs_uris="gs://foo/out.mp3",
    media_item=None,
    asset=None,
    enhance_return=None,
    metadata_return=None,
):
    with (
        patch("src.database.WorkerDatabase") as mock_worker_db,
        patch(
            "src.audios.audio_service.SourceAssetRepository"
        ) as mock_asset_cls,
        patch("src.audios.audio_service.MediaRepository") as mock_media_cls,
        patch("src.audios.audio_service.GeminiService") as mock_gemini_cls,
        patch("src.audios.audio_service.GenAIModelSetup") as mock_genai_setup,
        patch(
            "src.audios.audio_service.aiplatform.gapic.PredictionServiceClient"
        ) as mock_aiplatform,
        patch(
            "src.audios.audio_service.texttospeech.TextToSpeechClient"
        ) as mock_tts_cls,
        patch("src.audios.audio_service.GcsService") as mock_gcs_cls,
    ):
        db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = db_factory
        db_factory.return_value.__aenter__.return_value = AsyncMock()

        media_repo = AsyncMock()
        if isinstance(media_item, list):
            media_repo.get_by_id.side_effect = media_item
        else:
            media_repo.get_by_id.return_value = media_item
        mock_media_cls.return_value = media_repo

        asset_repo = AsyncMock()
        if isinstance(asset, list):
            asset_repo.get_by_id.side_effect = asset
        else:
            asset_repo.get_by_id.return_value = asset
        mock_asset_cls.return_value = asset_repo

        gemini = MagicMock()
        gemini.enhance_prompt_from_dto = AsyncMock(return_value=enhance_return)
        gemini.generate_media_metadata.return_value = metadata_return or {}
        mock_gemini_cls.return_value = gemini

        gcs = MagicMock()
        if isinstance(gcs_uris, list):
            gcs.store_to_gcs.side_effect = gcs_uris
        else:
            gcs.store_to_gcs.return_value = gcs_uris
        mock_gcs_cls.return_value = gcs

        omni_client = MagicMock()
        mock_genai_setup.get_omni_client.return_value = omni_client

        ai_client = MagicMock()
        ai_client.predict.return_value = MagicMock(
            predictions=[{"bytesBase64Encoded": "SGVsbG8="}]
        )
        mock_aiplatform.return_value = ai_client

        tts_client = MagicMock()
        tts_client.synthesize_speech.return_value = MagicMock(
            audio_content=b"123"
        )
        mock_tts_cls.return_value = tts_client

        yield SimpleNamespace(
            media_repo=media_repo,
            asset_repo=asset_repo,
            gemini=gemini,
            gcs=gcs,
            genai_setup=mock_genai_setup,
            omni_client=omni_client,
            ai_client=ai_client,
            tts_client=tts_client,
            run=lambda item_id, dto, user: _process_audio_in_background(
                media_item_id=item_id,
                request_dto=dto,
                user_email=user.email,
                user_id=user.id,
            ),
        )


class TestCreateAudioDtoReferenceImages:

    def test_rejects_empty_or_whitespace_prompt(self):
        with pytest.raises(ValidationError, match="prompt cannot be empty"):
            CreateAudioDto(
                workspace_id=1,
                prompt="   ",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                source_asset_ids=[1],
            )

    def test_accepts_reference_images_on_lyria3_models(self):
        dto = CreateAudioDto(
            workspace_id=1,
            prompt="Cinematic ambient track",
            model=GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
            source_asset_ids=[1, 2],
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=10, media_index=0, role=AssetRoleEnum.INPUT
                )
            ],
        )
        assert dto.source_asset_ids == [1, 2]
        assert len(dto.source_media_items or []) == 1

    @pytest.mark.parametrize(
        "unsupported_model",
        [
            GenerationModelEnum.LYRIA_002,
            GenerationModelEnum.CHIRP_3,
            GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
        ],
    )
    def test_rejects_reference_images_on_non_lyria3_models(
        self, unsupported_model
    ):
        with pytest.raises(
            ValidationError,
            match="Reference images are only supported for Lyria 3 models",
        ):
            CreateAudioDto(
                workspace_id=1,
                prompt="Test prompt",
                model=unsupported_model,
                source_asset_ids=[1],
            )

    def test_rejects_more_than_ten_combined_reference_images(self):
        with pytest.raises(
            ValidationError, match="At most 10 reference images"
        ):
            CreateAudioDto(
                workspace_id=1,
                prompt="Test prompt",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                source_asset_ids=[1, 2, 3, 4, 5, 6],
                source_media_items=[
                    SourceMediaItemLink(
                        media_item_id=i, media_index=0, role=AssetRoleEnum.INPUT
                    )
                    for i in range(10, 15)
                ],
            )


class TestLyria3ReferenceImages:

    def test_process_lyria3_passes_multimodal_images_and_persists_lineage(
        self, sample_user
    ):
        ws_asset = MagicMock(
            id=11,
            workspace_id=1,
            scope=AssetScopeEnum.PRIVATE,
            mime_type=MimeTypeEnum.IMAGE_JPEG,
            gcs_uri="gs://bucket/upload_11.jpg",
        )
        system_asset = MagicMock(
            id=12,
            workspace_id=999,
            scope=AssetScopeEnum.SYSTEM,
            mime_type="image/webp",
            gcs_uri="gs://bucket/system_12.webp",
        )
        media_item = MagicMock(
            id=50,
            workspace_id=1,
            mime_type=MimeTypeEnum.IMAGE_PNG,
            gcs_uris=["gs://bucket/gen_0.png", "gs://bucket/gen_1.png"],
        )
        with _audio_worker_env(
            gcs_uris="gs://foo/lyria3_ref.mp3",
            media_item=media_item,
            asset=[ws_asset, system_asset],
        ) as env:
            env.omni_client.interactions.create.return_value = MagicMock(
                id="int-ref",
                output_audio=MagicMock(
                    type="audio", mime_type="audio/mpeg", data="SGVsbG8="
                ),
            )
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Ethereal soundtrack matching these visuals",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                sample_count=1,
                source_asset_ids=[11, 12],
                source_media_items=[
                    SourceMediaItemLink(
                        media_item_id=50,
                        media_index=1,
                        role=AssetRoleEnum.INPUT,
                    )
                ],
            )
            env.run(200, dto, sample_user)

            assert env.omni_client.interactions.create.call_args.kwargs[
                "input"
            ] == [
                {
                    "type": "text",
                    "text": "Ethereal soundtrack matching these visuals",
                },
                {
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "uri": "gs://bucket/upload_11.jpg",
                },
                {
                    "type": "image",
                    "mime_type": "image/webp",
                    "uri": "gs://bucket/system_12.webp",
                },
                {
                    "type": "image",
                    "mime_type": "image/png",
                    "uri": "gs://bucket/gen_1.png",
                },
            ]
            env.media_repo.update.assert_called_with(
                200,
                {
                    "status": JobStatusEnum.COMPLETED,
                    "gcs_uris": ["gs://foo/lyria3_ref.mp3"],
                    "generation_time": pytest.approx(0, abs=10.0),
                    "mime_type": MimeTypeEnum.AUDIO_MPEG,
                    "audio_analysis": {
                        "iteration_steps": [
                            "Ethereal soundtrack matching these visuals"
                        ]
                    },
                    "source_assets": [
                        {"asset_id": 11, "role": AssetRoleEnum.INPUT},
                        {"asset_id": 12, "role": AssetRoleEnum.INPUT},
                    ],
                    "source_media_items": [
                        {
                            "media_item_id": 50,
                            "media_index": 1,
                            "role": AssetRoleEnum.INPUT,
                        }
                    ],
                },
            )

    @pytest.mark.parametrize(
        ("asset_mock", "media_mock", "dto_kwargs", "expected_error"),
        [
            (
                MagicMock(
                    id=11,
                    workspace_id=2,
                    scope=AssetScopeEnum.PRIVATE,
                    mime_type=MimeTypeEnum.IMAGE_PNG,
                    gcs_uri="gs://bucket/other_ws.png",
                ),
                None,
                {"source_asset_ids": [11]},
                "Source asset 11 was not found in this workspace.",
            ),
            (
                MagicMock(
                    id=11,
                    workspace_id=1,
                    scope=AssetScopeEnum.PRIVATE,
                    mime_type=MimeTypeEnum.VIDEO_MP4,
                    gcs_uri="gs://bucket/clip.mp4",
                ),
                None,
                {"source_asset_ids": [11]},
                "Source asset 11 is not a valid image asset.",
            ),
            (
                None,
                MagicMock(
                    id=50,
                    workspace_id=2,
                    mime_type=MimeTypeEnum.IMAGE_PNG,
                    gcs_uris=["gs://bucket/img.png"],
                ),
                {
                    "source_media_items": [
                        SourceMediaItemLink(
                            media_item_id=50,
                            media_index=0,
                            role=AssetRoleEnum.INPUT,
                        )
                    ]
                },
                "Media item 50 was not found in this workspace.",
            ),
            (
                None,
                MagicMock(
                    id=50,
                    workspace_id=1,
                    mime_type=MimeTypeEnum.IMAGE_PNG,
                    gcs_uris=["gs://bucket/img.png"],
                ),
                {
                    "source_media_items": [
                        SourceMediaItemLink(
                            media_item_id=50,
                            media_index=3,
                            role=AssetRoleEnum.INPUT,
                        )
                    ]
                },
                "Media item 50 index 3 is out of bounds.",
            ),
            (
                None,
                MagicMock(
                    id=50,
                    workspace_id=1,
                    mime_type=MimeTypeEnum.AUDIO_MPEG,
                    gcs_uris=["gs://bucket/song.mp3"],
                ),
                {
                    "source_media_items": [
                        SourceMediaItemLink(
                            media_item_id=50,
                            media_index=0,
                            role=AssetRoleEnum.INPUT,
                        )
                    ]
                },
                "Media item 50 is not an image item.",
            ),
        ],
    )
    def test_process_lyria3_rejects_invalid_reference_inputs(
        self,
        asset_mock,
        media_mock,
        dto_kwargs,
        expected_error,
        sample_user,
    ):
        with _audio_worker_env(media_item=media_mock, asset=asset_mock) as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Ambient track",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                sample_count=1,
                **dto_kwargs,
            )
            env.run(201, dto, sample_user)

            env.genai_setup.get_omni_client.assert_not_called()
            env.gcs.store_to_gcs.assert_not_called()
            env.media_repo.update.assert_called_with(
                201,
                {
                    "status": JobStatusEnum.FAILED,
                    "error_message": expected_error,
                },
            )


class TestLyria3LyricsAndStructure:

    def test_extract_text_returns_none_for_bare_mock_or_audio_only(self):
        bare_mock = MagicMock(
            id="inter_bare",
            output_audio=MagicMock(
                type="audio", mime_type="audio/mp3", data="SGVsbG8="
            ),
        )
        assert _extract_lyria3_text(bare_mock) is None
        assert (
            _extract_lyria3_text(
                {"outputs": [{"type": "audio", "data": "SGVsbG8="}]}
            )
            is None
        )

    @pytest.mark.parametrize(
        ("raw_text", "expected"),
        [
            (
                "[Verse 1]\nNeon lights on wet asphalt\n\n[Chorus]\nRun into the night",
                {
                    "raw_text": (
                        "[Verse 1]\nNeon lights on wet asphalt\n\n"
                        "[Chorus]\nRun into the night"
                    ),
                    "lyrics": (
                        "[Verse 1]\nNeon lights on wet asphalt\n\n"
                        "[Chorus]\nRun into the night"
                    ),
                },
            ),
            (
                "[0.0:5.3] Darkness descends on a world torn asunder\n"
                "[5.3:10.6] THE SKY BREAKS APART WITH A CATACLYSMIC THUNDER\n\n"
                "Caption: Maximalist Symphonic Metal built to evoke an ocean storm.\n"
                "Driving double-kick drums and soaring strings.\n"
                "Mosic: 4.5\n"
                "BPM: 90.0",
                {
                    "raw_text": (
                        "[0.0:5.3] Darkness descends on a world torn asunder\n"
                        "[5.3:10.6] THE SKY BREAKS APART WITH A CATACLYSMIC THUNDER\n\n"
                        "Caption: Maximalist Symphonic Metal built to evoke an ocean storm.\n"
                        "Driving double-kick drums and soaring strings.\n"
                        "Mosic: 4.5\n"
                        "BPM: 90.0"
                    ),
                    "lyrics": (
                        "[0.0:5.3] Darkness descends on a world torn asunder\n"
                        "[5.3:10.6] THE SKY BREAKS APART WITH A CATACLYSMIC THUNDER"
                    ),
                    "structure": {
                        "caption": (
                            "Maximalist Symphonic Metal built to evoke an ocean storm. "
                            "Driving double-kick drums and soaring strings."
                        ),
                        "mosic": 4.5,
                        "bpm": 90,
                    },
                },
            ),
            (
                "Caption: Warm lo-fi hip-hop instrumental with Rhodes chords.\n"
                "Mosic: 4.5\n"
                "BPM: 84.5",
                {
                    "raw_text": (
                        "Caption: Warm lo-fi hip-hop instrumental with Rhodes chords.\n"
                        "Mosic: 4.5\n"
                        "BPM: 84.5"
                    ),
                    "structure": {
                        "caption": (
                            "Warm lo-fi hip-hop instrumental with Rhodes chords."
                        ),
                        "mosic": 4.5,
                        "bpm": 84.5,
                    },
                },
            ),
        ],
    )
    def test_extract_text_from_output_text_variants(self, raw_text, expected):
        interaction = MagicMock(steps=None, outputs=None, output_text=raw_text)
        assert _extract_lyria3_text(interaction) == expected

    def test_extract_text_from_steps_ignores_user_input_and_parses_structure(
        self,
    ):
        structure_obj = {
            "tempo": "122 BPM",
            "key": "A minor",
            "sections": [
                {"name": "Intro", "duration": "0:00-0:08"},
                {"name": "Chorus", "duration": "0:08-0:30"},
            ],
        }
        user_step = MagicMock(
            type="user_input",
            content=[MagicMock(type="text", text="User prompt text")],
        )
        model_step = MagicMock(
            type="model_output",
            content=[
                MagicMock(type="text", text=json.dumps(structure_obj)),
                MagicMock(
                    type="text", text="[Chorus]\nElectric dreams tonight"
                ),
                MagicMock(type="audio", data=b"\x00\x01"),
            ],
        )
        interaction = MagicMock(
            steps=[user_step, model_step],
            outputs=None,
            output_text="ignored fallback",
        )
        result = _extract_lyria3_text(interaction)
        assert result is not None
        assert result["structure"] == structure_obj
        assert result["lyrics"] == "[Chorus]\nElectric dreams tonight"
        assert "User prompt text" not in result["raw_text"]

    def test_extract_text_from_rest_outputs_extracts_section_lyrics(self):
        payload = {
            "bpm": 110,
            "sections": [
                {"name": "Verse 1", "lyrics": "Walking by the sea"},
                {"name": "Chorus", "lyrics": "Golden horizon"},
            ],
        }
        interaction = {
            "outputs": [
                {"type": "text", "text": json.dumps(payload)},
                {"type": "audio", "mime_type": "audio/mpeg", "data": "SGk="},
            ]
        }
        result = _extract_lyria3_text(interaction)
        assert result is not None
        assert result["structure"] == payload
        assert (
            result["lyrics"]
            == "[Verse 1]\nWalking by the sea\n\n[Chorus]\nGolden horizon"
        )

    def test_process_lyria3_persists_aligned_multi_sample_audio_analysis(
        self, sample_user
    ):
        with _audio_worker_env(
            gcs_uris=["gs://bucket/track_0.mp3", "gs://bucket/track_2.mp3"]
        ) as env:
            env.omni_client.interactions.create.side_effect = [
                MagicMock(
                    id="i0",
                    steps=None,
                    outputs=None,
                    output_audio=MagicMock(
                        type="audio", mime_type="audio/mp3", data="SGVsbG8="
                    ),
                    output_text="[Verse]\nTrack zero lyrics",
                ),
                MagicMock(
                    id="i1",
                    steps=None,
                    outputs=None,
                    output_audio=None,
                    output_text="Orphaned text",
                ),
                MagicMock(
                    id="i2",
                    steps=None,
                    outputs=None,
                    output_audio=MagicMock(
                        type="audio", mime_type="audio/mp3", data="V29ybGQ="
                    ),
                    output_text=None,
                ),
            ]
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Indie pop anthem",
                model=GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
                sample_count=3,
            )
            env.run(305, dto, sample_user)

            env.media_repo.update.assert_called_with(
                305,
                {
                    "status": JobStatusEnum.COMPLETED,
                    "gcs_uris": [
                        "gs://bucket/track_0.mp3",
                        "gs://bucket/track_2.mp3",
                    ],
                    "generation_time": pytest.approx(0, abs=10.0),
                    "num_media": 2,
                    "mime_type": MimeTypeEnum.AUDIO_MPEG,
                    "audio_analysis": {
                        "tracks": [
                            {
                                "raw_text": "[Verse]\nTrack zero lyrics",
                                "lyrics": "[Verse]\nTrack zero lyrics",
                            },
                            None,
                        ],
                        "iteration_steps": ["Indie pop anthem"],
                    },
                },
            )

    def test_process_lyria_enhances_prompt_when_requested(self, sample_user):
        with _audio_worker_env(
            gcs_uris="gs://foo/enhanced.wav",
            enhance_return="Enhanced warm acoustic guitar melody at 95 BPM.",
        ) as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="acoustic guitar",
                model=GenerationModelEnum.LYRIA_002,
                seed=0,
                enhance_prompt=True,
            )
            env.run(401, dto, sample_user)

            env.gemini.enhance_prompt_from_dto.assert_called_once()
            predict_instances = env.ai_client.predict.call_args.kwargs[
                "instances"
            ]
            assert (
                predict_instances[0].struct_value.fields["seed"].number_value
                == 0
            )
            env.media_repo.update.assert_called_with(
                401,
                {
                    "status": JobStatusEnum.COMPLETED,
                    "gcs_uris": ["gs://foo/enhanced.wav"],
                    "generation_time": pytest.approx(0, abs=10.0),
                    "prompt": "Enhanced warm acoustic guitar melody at 95 BPM.",
                    "seed": 0,
                    "audio_analysis": {
                        "tracks": [{"seed": 0}],
                        "iteration_steps": ["acoustic guitar"],
                    },
                },
            )

    def test_process_tts_ignores_enhance_prompt(self, sample_user):
        with _audio_worker_env(gcs_uris="gs://foo/tts.wav") as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Exact script to read aloud",
                model=GenerationModelEnum.CHIRP_3,
                language_code=LanguageEnum.EN_US,
                voice_name=VoiceEnum.PUCK,
                enhance_prompt=True,
            )
            env.run(402, dto, sample_user)

            env.gemini.enhance_prompt_from_dto.assert_not_called()
            env.media_repo.update.assert_called_with(
                402,
                {
                    "status": JobStatusEnum.COMPLETED,
                    "gcs_uris": ["gs://foo/tts.wav"],
                    "generation_time": pytest.approx(0, abs=10.0),
                },
            )

    def test_lyria3_enhance_preserves_original_and_negative_on_retry(
        self, sample_user
    ):
        ref_asset = MagicMock(
            id=10,
            workspace_id=1,
            scope=AssetScopeEnum.PRIVATE,
            mime_type=MimeTypeEnum.IMAGE_JPEG,
            gcs_uri="gs://bucket/ref.jpg",
        )
        with _audio_worker_env(
            gcs_uris="gs://foo/lyria3_retry.mp3",
            asset=ref_asset,
            enhance_return="Cinematic orchestral swell with roaring engines.",
        ) as env:
            env.omni_client.interactions.create.side_effect = [
                Exception("400 {'code': 'content_blocked'}"),
                MagicMock(
                    id="inter_ok",
                    output_audio=MagicMock(
                        type="audio", data="SGVsbG8=", mime_type="audio/mpeg"
                    ),
                    steps=[],
                    outputs=[],
                ),
            ]
            user_prompt = (
                "Warm indie folk acoustic guitar featuring roaring engines"
            )
            dto = CreateAudioDto(
                workspace_id=1,
                prompt=user_prompt,
                negative_prompt="heavy percussion",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                enhance_prompt=True,
                source_asset_ids=[10],
            )
            env.run(403, dto, sample_user)

            assert dto.prompt == user_prompt
            extra_parts = env.gemini.enhance_prompt_from_dto.call_args.kwargs[
                "extra_parts"
            ]
            assert len(extra_parts) == 1
            assert extra_parts[0].file_data.file_uri == "gs://bucket/ref.jpg"
            assert env.omni_client.interactions.create.call_count == 2

            calls = env.omni_client.interactions.create.call_args_list
            first_inputs = calls[0].kwargs["input"]
            retry_inputs = calls[1].kwargs["input"]
            assert len(first_inputs) == 2
            assert len(retry_inputs) == 1
            first_text = first_inputs[0]["text"]
            retry_text = retry_inputs[0]["text"]

            assert first_text.startswith("Cinematic orchestral swell")
            assert first_text.endswith("\n\nAvoid: heavy percussion")
            assert retry_text.startswith("Warm indie folk acoustic guitar.")
            assert retry_text.endswith("\n\nAvoid: heavy percussion")
            assert env.media_repo.update.call_args.args[1]["prompt"] == (
                retry_text
            )

    def test_process_lyria3_validates_references_before_enhance_prompt(
        self, sample_user
    ):
        foreign_asset = MagicMock(
            id=99,
            workspace_id=999,
            scope=AssetScopeEnum.PRIVATE,
            mime_type=MimeTypeEnum.IMAGE_PNG,
            gcs_uri="gs://bucket/foreign.png",
        )
        with _audio_worker_env(asset=foreign_asset) as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Ambient pads",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                enhance_prompt=True,
                source_asset_ids=[99],
            )
            env.run(404, dto, sample_user)

            env.gemini.enhance_prompt_from_dto.assert_not_called()
            env.media_repo.update.assert_called_once_with(
                404,
                {
                    "status": JobStatusEnum.FAILED,
                    "error_message": (
                        "Source asset 99 was not found in this workspace."
                    ),
                },
            )


class TestReferenceAudioIteration:
    def test_dto_accepts_reference_audio_for_all_lyria_models(self):
        for model in (
            GenerationModelEnum.LYRIA_002,
            GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
        ):
            dto = CreateAudioDto.model_validate(
                {
                    "workspaceId": 1,
                    "prompt": "Evolve with brass section",
                    "model": model.value,
                    "referenceAudio": {
                        "id": 77,
                        "type": "media_item",
                        "index": 1,
                    },
                }
            )
            assert dto.reference_audio is not None
            assert (
                dto.reference_audio.id,
                dto.reference_audio.type,
                dto.reference_audio.index,
            ) == (77, "media_item", 1)

    @pytest.mark.parametrize(
        ("model", "ref_type", "index", "err_match"),
        [
            (
                GenerationModelEnum.CHIRP_3,
                "source_asset",
                0,
                "Reference audio is only supported for Lyria music models",
            ),
            (
                GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                "unknown",
                0,
                "Input should be 'source_asset' or 'media_item'",
            ),
            (
                GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                "media_item",
                -1,
                "greater than or equal to 0",
            ),
        ],
    )
    def test_dto_rejects_reference_audio_for_tts_and_invalid_fields(
        self, model, ref_type, index, err_match
    ):
        with pytest.raises(ValidationError, match=err_match):
            CreateAudioDto(
                workspace_id=1,
                prompt="Faster beat",
                model=model,
                reference_audio={"id": 1, "type": ref_type, "index": index},
            )

    @pytest.mark.anyio
    async def test_resolve_reference_audio_source_asset_and_errors(self):
        media_repo, asset_repo = AsyncMock(), AsyncMock()

        def _dto(asset_id: int) -> CreateAudioDto:
            return CreateAudioDto(
                workspace_id=1,
                prompt="Add drums",
                model=GenerationModelEnum.LYRIA_002,
                reference_audio=AssetReferenceDto(
                    id=asset_id, type="source_asset", index=0
                ),
            )

        asset_repo.get_by_id.return_value = MagicMock(
            id=5,
            workspace_id=999,
            scope=AssetScopeEnum.SYSTEM,
            mime_type=MimeTypeEnum.AUDIO_MP3,
            gcs_uri="gs://bucket/system_loop.mp3",
        )
        ctx, asset_link, media_link = await _resolve_reference_audio(
            _dto(5), media_repo, asset_repo
        )
        assert ctx == {
            "uri": "gs://bucket/system_loop.mp3",
            "mime_type": "audio/mpeg",
        }
        assert asset_link is not None
        assert (asset_link.asset_id, asset_link.role) == (
            5,
            AssetRoleEnum.AUDIO_REFERENCE,
        )
        assert media_link is None

        for asset_id, ws_id, mime, err_msg in (
            (
                6,
                999,
                MimeTypeEnum.AUDIO_WAV,
                "Source asset 6 was not found in this workspace",
            ),
            (
                7,
                1,
                MimeTypeEnum.IMAGE_PNG,
                "Source asset 7 is not a valid audio asset",
            ),
        ):
            asset_repo.get_by_id.return_value = MagicMock(
                id=asset_id,
                workspace_id=ws_id,
                scope=AssetScopeEnum.PRIVATE,
                mime_type=mime,
                gcs_uri="gs://bucket/file",
            )
            with pytest.raises(ValueError, match=err_msg):
                await _resolve_reference_audio(
                    _dto(asset_id), media_repo, asset_repo
                )

    @pytest.mark.anyio
    async def test_resolve_reference_audio_media_item_extracts_track_analysis(
        self,
    ):
        media_repo, asset_repo = AsyncMock(), AsyncMock()
        media_repo.get_by_id.return_value = MagicMock(
            id=88,
            workspace_id=1,
            mime_type=MimeTypeEnum.AUDIO_WAV,
            gcs_uris=["gs://bucket/t0.mp3", "gs://bucket/t1.mp3"],
            prompt="Dreamy synthwave intro at 100 BPM",
            original_prompt="synthwave",
            audio_analysis={
                "tracks": [
                    {"raw_text": "Track 0"},
                    {
                        "raw_text": "[Verse]\nMidnight highway\nBPM: 100",
                        "lyrics": "[Verse]\nMidnight highway",
                        "structure": {"bpm": 100},
                    },
                ]
            },
        )

        def _dto(idx: int = 1) -> CreateAudioDto:
            return CreateAudioDto(
                workspace_id=1,
                prompt="Extend into chorus at 100 BPM",
                model=GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
                reference_audio=AssetReferenceDto(
                    id=88, type="media_item", index=idx
                ),
            )

        ctx, asset_link, media_link = await _resolve_reference_audio(
            _dto(1), media_repo, asset_repo
        )
        assert ctx == {
            "uri": "gs://bucket/t1.mp3",
            "mime_type": "audio/mpeg",
            "prior_prompt": "Dreamy synthwave intro at 100 BPM",
            "lyrics": "[Verse]\nMidnight highway",
            "structure": {"bpm": 100},
            "iteration_steps": ["synthwave"],
        }
        assert asset_link is None
        assert media_link is not None
        assert (
            media_link.media_item_id,
            media_link.media_index,
            media_link.role,
        ) == (88, 1, AssetRoleEnum.AUDIO_REFERENCE)

        with pytest.raises(
            ValueError, match="Media item 88 index 5 is out of bounds"
        ):
            await _resolve_reference_audio(_dto(5), media_repo, asset_repo)

        media_repo.get_by_id.return_value.workspace_id = 42
        with pytest.raises(
            ValueError, match="Media item 88 was not found in this workspace"
        ):
            await _resolve_reference_audio(_dto(1), media_repo, asset_repo)

        media_repo.get_by_id.return_value.workspace_id = 1
        media_repo.get_by_id.return_value.mime_type = MimeTypeEnum.VIDEO_MP4
        with pytest.raises(
            ValueError, match="Media item 88 is not an audio item"
        ):
            await _resolve_reference_audio(_dto(1), media_repo, asset_repo)

    def test_worker_invokes_gemini_with_reference_audio_even_when_enhance_false(
        self, sample_user
    ):
        parent_media = MagicMock(
            id=70,
            workspace_id=1,
            mime_type=MimeTypeEnum.AUDIO_MPEG,
            gcs_uris=["gs://bucket/prev_0.mp3"],
            prompt="Acoustic folk verse at 98 BPM",
            audio_analysis={
                "tracks": [
                    {
                        "raw_text": "[Verse]\nMorning light",
                        "lyrics": "[Verse]\nMorning light",
                        "structure": {"bpm": 98},
                    }
                ]
            },
        )
        cover_asset = MagicMock(
            id=12,
            workspace_id=1,
            scope=AssetScopeEnum.PRIVATE,
            mime_type=MimeTypeEnum.IMAGE_PNG,
            gcs_uri="gs://bucket/cover.png",
        )
        enhanced = "Acoustic folk chorus at 98 BPM adding fiddle and harmonies."
        with _audio_worker_env(
            gcs_uris="gs://foo/iterated.mp3",
            media_item=parent_media,
            asset=cover_asset,
            enhance_return=enhanced,
        ) as env:
            env.omni_client.interactions.create.return_value = MagicMock(
                id="inter_iter",
                output_audio=MagicMock(
                    type="audio", data="SGVsbG8=", mime_type="audio/mpeg"
                ),
                steps=[],
                outputs=[],
            )
            user_prompt = "Add fiddle harmonies and lift into the chorus"
            dto = CreateAudioDto(
                workspace_id=1,
                prompt=user_prompt,
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                enhance_prompt=False,
                source_asset_ids=[12],
                reference_audio=AssetReferenceDto(
                    id=70, type="media_item", index=0
                ),
            )
            env.run(501, dto, sample_user)

            assert dto.prompt == user_prompt
            env.gemini.enhance_prompt_from_dto.assert_called_once()
            call_kwargs = env.gemini.enhance_prompt_from_dto.call_args.kwargs
            extra_parts = call_kwargs["extra_parts"]
            assert len(extra_parts) == 2
            assert extra_parts[0].file_data.file_uri == "gs://bucket/prev_0.mp3"
            assert extra_parts[0].file_data.mime_type == "audio/mpeg"
            assert extra_parts[1].file_data.file_uri == "gs://bucket/cover.png"
            assert call_kwargs["reference_audio_context"]["lyrics"] == (
                "[Verse]\nMorning light"
            )

            lyria_input = env.omni_client.interactions.create.call_args.kwargs[
                "input"
            ]
            assert lyria_input[0]["text"] == enhanced
            assert lyria_input[1]["uri"] == "gs://bucket/cover.png"

            updated = env.media_repo.update.call_args.args[1]
            assert updated["status"] == JobStatusEnum.COMPLETED
            assert updated["prompt"] == enhanced
            assert updated["source_assets"] == [
                {"asset_id": 12, "role": AssetRoleEnum.INPUT}
            ]
            assert updated["source_media_items"] == [
                {
                    "media_item_id": 70,
                    "media_index": 0,
                    "role": AssetRoleEnum.AUDIO_REFERENCE,
                }
            ]

    @patch("src.audios.audio_service.random.randint", return_value=1000)
    def test_lyria2_auto_mints_distinct_per_take_seeds_and_persists_musical_profiles(
        self, mock_randint, sample_user
    ):
        with _audio_worker_env(
            gcs_uris=["gs://foo/t0.wav", "gs://foo/t1.wav", "gs://foo/t2.wav"],
            metadata_return={
                "titles": ["Take 0", "Take 1", "Take 2"],
                "descriptions": ["Desc 0", "Desc 1", "Desc 2"],
                "musical_profiles": [
                    {"bpm": 120, "key_signature": "Bb Major"},
                    None,
                    {"bpm": 122, "key_signature": "G minor"},
                ],
            },
        ) as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Jazz solo on Rhodes",
                model=GenerationModelEnum.LYRIA_002,
                sample_count=3,
                seed=None,
            )
            env.run(601, dto, sample_user)

            mock_randint.assert_called_once()
            calls = env.ai_client.predict.call_args_list
            observed_seeds = {
                int(
                    c.kwargs["instances"][0]
                    .struct_value.fields["seed"]
                    .number_value
                )
                for c in calls
            }
            assert observed_seeds == {1000, 1001, 1002}
            for c in calls:
                assert (
                    "sample_count"
                    not in c.kwargs["parameters"].struct_value.fields
                )

            env.gemini.generate_media_metadata.assert_called_once_with(
                prompt=(
                    "Describe this generated audio based on prompt: "
                    "Jazz solo on Rhodes"
                ),
                media_uris=[
                    "gs://foo/t0.wav",
                    "gs://foo/t1.wav",
                    "gs://foo/t2.wav",
                ],
                model_name=GenerationModelEnum.GEMINI_3_5_FLASH,
                mime_type=None,
                include_audio_profile=True,
            )

            updated = env.media_repo.update.call_args.args[1]
            assert updated["seed"] == 1000
            assert updated["audio_analysis"] == {
                "tracks": [
                    {
                        "seed": 1000,
                        "musical_profile": {
                            "bpm": 120,
                            "key_signature": "Bb Major",
                        },
                    },
                    {"seed": 1001},
                    {
                        "seed": 1002,
                        "musical_profile": {
                            "bpm": 122,
                            "key_signature": "G minor",
                        },
                    },
                ],
                "iteration_steps": ["Jazz solo on Rhodes"],
            }

    @patch("src.audios.audio_service.random.randint")
    def test_lyria2_inherits_per_take_seed_musical_profile_and_caps_iteration_steps(
        self, mock_randint, sample_user
    ):
        prior_steps = [f"Step {i}" for i in range(1, 7)]
        parent_media = MagicMock(
            id=601,
            workspace_id=1,
            mime_type=MimeTypeEnum.AUDIO_WAV,
            gcs_uris=["gs://foo/t0.wav", "gs://foo/t1.wav", "gs://foo/t2.wav"],
            prompt="120 BPM Bb Major drumless Rhodes jazz solo",
            seed=1000,
            audio_analysis={
                "tracks": [
                    {"seed": 1000},
                    {"seed": 1001},
                    {
                        "seed": 1002,
                        "musical_profile": {
                            "bpm": 120,
                            "key_signature": "Bb Major",
                        },
                    },
                ],
                "iteration_steps": prior_steps,
            },
        )
        with _audio_worker_env(
            gcs_uris="gs://foo/step7.wav",
            media_item=parent_media,
            enhance_return=(
                "120 BPM Bb Major Rhodes jazz solo adding muted trumpet."
            ),
        ) as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Step 7: add muted trumpet",
                model=GenerationModelEnum.LYRIA_002,
                seed=None,
                reference_audio=AssetReferenceDto(
                    id=601, type="media_item", index=2
                ),
            )
            env.run(602, dto, sample_user)

            mock_randint.assert_not_called()
            predict_seed = int(
                env.ai_client.predict.call_args.kwargs["instances"][0]
                .struct_value.fields["seed"]
                .number_value
            )
            assert predict_seed == 1002

            ref_ctx = env.gemini.enhance_prompt_from_dto.call_args.kwargs[
                "reference_audio_context"
            ]
            assert ref_ctx["prior_seed"] == 1002
            assert ref_ctx["musical_profile"] == {
                "bpm": 120,
                "key_signature": "Bb Major",
            }
            assert ref_ctx["iteration_steps"] == prior_steps

            updated = env.media_repo.update.call_args.args[1]
            assert updated["seed"] == 1002
            steps = updated["audio_analysis"]["iteration_steps"]
            assert len(steps) == MAX_AUDIO_ITERATION_STEPS
            assert steps == [
                "Step 2",
                "Step 3",
                "Step 4",
                "Step 5",
                "Step 6",
                "Step 7: add muted trumpet",
            ]

    @pytest.mark.parametrize(
        ("item_id", "media_item", "enhance_return", "dto_kwargs"),
        [
            (
                611,
                MagicMock(
                    id=610,
                    workspace_id=1,
                    mime_type=MimeTypeEnum.AUDIO_MPEG,
                    gcs_uris=["gs://bucket/prior_song.mp3"],
                    original_prompt="90 BPM soulful R&B",
                    prompt="90 BPM soulful R&B",
                    seed=None,
                    audio_analysis=None,
                ),
                "90 BPM soulful R&B in F minor, explosive dynamic drop.",
                {
                    "prompt": "Make the drop hit harder",
                    "model": GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                    "reference_audio": AssetReferenceDto(
                        id=610, type="media_item", index=0
                    ),
                },
            ),
            (
                612,
                None,
                None,
                {
                    "prompt": (
                        "Soulful 90 BPM R&B ballad with female vocals\n\n"
                        "Lyrics:\n[Chorus]\nStay through the storm"
                    ),
                    "model": GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
                },
            ),
        ],
    )
    def test_process_lyria3_skips_simplified_retry_when_guarded(
        self, item_id, media_item, enhance_return, dto_kwargs, sample_user
    ):
        with _audio_worker_env(
            media_item=media_item, enhance_return=enhance_return
        ) as env:
            env.omni_client.interactions.create.side_effect = Exception(
                "400 {'code': 'content_blocked'}"
            )
            dto = CreateAudioDto(workspace_id=1, **dto_kwargs)
            env.run(item_id, dto, sample_user)

            env.omni_client.interactions.create.assert_called_once()
            env.gcs.store_to_gcs.assert_not_called()
            env.media_repo.update.assert_called_with(
                item_id,
                {
                    "status": JobStatusEnum.FAILED,
                    "error_message": LYRIA_3_CONTENT_BLOCKED_NO_RETRY_MESSAGE,
                },
            )

    def test_lyria_seed_bounds_and_take_wraparound(self, sample_user):
        for bad_seed in (-1, LYRIA_MAX_SEED + 1):
            with pytest.raises(ValidationError):
                CreateAudioDto(workspace_id=1, prompt="Synth", seed=bad_seed)

        assert _is_valid_int_seed(0) is True
        assert _is_valid_int_seed(LYRIA_MAX_SEED) is True
        assert _is_valid_int_seed(-1) is False
        assert _is_valid_int_seed(LYRIA_MAX_SEED + 1) is False
        assert _is_valid_int_seed(True) is False

        with _audio_worker_env(gcs_uris="gs://foo/wrap.wav") as env:
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Synth",
                model=GenerationModelEnum.LYRIA_002,
                sample_count=2,
                seed=LYRIA_MAX_SEED,
            )
            env.run(613, dto, sample_user)

            updated = env.media_repo.update.call_args.args[1]
            assert updated["status"] == JobStatusEnum.COMPLETED
            assert updated["seed"] == LYRIA_MAX_SEED
            assert [t["seed"] for t in updated["audio_analysis"]["tracks"]] == [
                LYRIA_MAX_SEED,
                0,
            ]

    @pytest.mark.parametrize(
        "bad_metadata_model",
        [
            "../../publishers/google/models/expensive-model",
            "arbitrary-unapproved-model",
            GenerationModelEnum.LYRIA_002,
            GenerationModelEnum.VEO_3_1_GENERATE_001,
            GenerationModelEnum.CHIRP_3,
        ],
    )
    def test_create_audio_dto_rejects_unallowed_metadata_generation_model(
        self, bad_metadata_model
    ):
        with pytest.raises(ValidationError):
            CreateAudioDto(
                workspace_id=1,
                prompt="Synthwave pulse",
                metadata_generation_model=bad_metadata_model,
            )

        for bad_ws in (0, -1):
            with pytest.raises(ValidationError):
                CreateAudioDto(workspace_id=bad_ws, prompt="Synthwave pulse")

        dto_none = CreateAudioDto(
            workspace_id=1,
            prompt="Synthwave pulse",
            metadata_generation_model=None,
        )
        assert dto_none.metadata_generation_model is None
        dto_pro = CreateAudioDto(
            workspace_id=1,
            prompt="Synthwave pulse",
            metadata_generation_model=GenerationModelEnum.GEMINI_3_1_PRO_PREVIEW,
        )
        assert (
            dto_pro.metadata_generation_model
            == GenerationModelEnum.GEMINI_3_1_PRO_PREVIEW
        )

    @pytest.mark.parametrize(
        ("raw_mime", "expected_ext", "expected_enum", "stored_uri"),
        [
            (
                "audio/wav",
                ".wav",
                MimeTypeEnum.AUDIO_WAV,
                "gs://foo/lyria3_take0.wav",
            ),
            (
                "audio/ogg",
                ".ogg",
                MimeTypeEnum.AUDIO_OGG,
                "gs://foo/lyria3_take0.ogg",
            ),
            (
                "audio/webm",
                ".webm",
                MimeTypeEnum.AUDIO_WEBM,
                "gs://foo/lyria3_take0.webm",
            ),
        ],
    )
    def test_process_lyria3_wav_output_persists_audio_wav_mime_and_metadata(
        self, raw_mime, expected_ext, expected_enum, stored_uri, sample_user
    ):
        with _audio_worker_env(
            gcs_uris=stored_uri,
            metadata_return={
                "titles": ["Crystal Keys"],
                "descriptions": ["Warm WAV take"],
                "musical_profiles": [{"bpm": 110, "key_signature": "C Major"}],
            },
        ) as env:
            env.omni_client.interactions.create.return_value = MagicMock(
                id="inter_wav",
                output_audio=MagicMock(
                    type="audio", mime_type=raw_mime, data="SGVsbG8="
                ),
                steps=[],
                outputs=[],
            )
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Crystal ambient keys",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                metadata_generation_model=GenerationModelEnum.GEMINI_2_5_FLASH,
            )
            env.run(620, dto, sample_user)

            store_kwargs = env.gcs.store_to_gcs.call_args.kwargs
            assert store_kwargs["file_name"].endswith(expected_ext)
            assert store_kwargs["mime_type"] == expected_enum.value

            env.gemini.generate_media_metadata.assert_called_once_with(
                prompt=(
                    "Describe this generated audio based on prompt: "
                    "Crystal ambient keys"
                ),
                media_uris=[stored_uri],
                model_name="gemini-2.5-flash",
                mime_type=None,
                include_audio_profile=True,
            )

            updated = env.media_repo.update.call_args.args[1]
            assert updated["status"] == JobStatusEnum.COMPLETED
            assert updated["mime_type"] == expected_enum
            assert updated["titles"] == ["Crystal Keys"]
            assert updated["audio_analysis"] == {
                "tracks": [
                    {
                        "musical_profile": {
                            "bpm": 110,
                            "key_signature": "C Major",
                        }
                    }
                ],
                "iteration_steps": ["Crystal ambient keys"],
            }

    def test_process_lyria3_multi_sample_partial_content_blocked_preserves_initial_prompt_for_unretried_takes(
        self, sample_user
    ):
        ok_interaction = MagicMock(
            id="inter_ok",
            output_audio=MagicMock(
                type="audio", mime_type="audio/mpeg", data="SGVsbG8="
            ),
            steps=[],
            outputs=[],
        )
        retry_interaction = MagicMock(
            id="inter_retried",
            output_audio=MagicMock(
                type="audio", mime_type="audio/mpeg", data="SGVsbG8="
            ),
            steps=[],
            outputs=[],
        )
        blocked_err = Exception("400 {'code': 'content_blocked'}")

        call_count = 0

        def _create_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 4:
                raise blocked_err
            if call_count == 5:
                return retry_interaction
            return ok_interaction

        enhanced = (
            "Driving cinematic synthwave score with pulsing arpeggios, "
            "evoking a midnight coastal highway chase."
        )
        with _audio_worker_env(
            gcs_uris=[
                "gs://foo/t0.mp3",
                "gs://foo/t1.mp3",
                "gs://foo/t2.mp3",
                "gs://foo/t3.mp3",
            ],
            enhance_return=enhanced,
        ) as env:
            env.omni_client.interactions.create.side_effect = (
                _create_side_effect
            )
            dto = CreateAudioDto(
                workspace_id=1,
                prompt=(
                    "Driving synthwave score with pulsing arpeggios "
                    "evoking a midnight highway chase."
                ),
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
                sample_count=4,
                enhance_prompt=True,
            )
            env.run(630, dto, sample_user)

            updated = env.media_repo.update.call_args.args[1]
            assert updated["status"] == JobStatusEnum.COMPLETED
            assert len(updated["gcs_uris"]) == 4
            # Takes 0-2 succeeded with the enhanced prompt, so MediaItem.prompt
            # must NOT be overwritten by Take 3's simplified retry brief.
            assert updated["prompt"] == enhanced

    def test_process_lyria2_partial_take_failure_updates_seed_and_num_media(
        self, sample_user
    ):
        call_idx = 0

        def _predict_side_effect(**_kwargs):
            nonlocal call_idx
            current = call_idx
            call_idx += 1
            if current == 0:
                raise RuntimeError("transient take 0 failure")
            return MagicMock(predictions=[{"bytesBase64Encoded": "SGVsbG8="}])

        with _audio_worker_env(
            gcs_uris=[
                "gs://foo/take1.wav",
                "gs://foo/take2.wav",
                "gs://foo/take3.wav",
            ]
        ) as env:
            env.ai_client.predict.side_effect = _predict_side_effect
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Warm electric piano chords",
                model=GenerationModelEnum.LYRIA_002,
                sample_count=4,
                seed=500,
            )
            env.run(631, dto, sample_user)

            updated = env.media_repo.update.call_args.args[1]
            assert updated["status"] == JobStatusEnum.COMPLETED
            assert updated["num_media"] == 3
            assert len(updated["gcs_uris"]) == 3
            assert updated["seed"] in {501, 502, 503}

    @pytest.mark.anyio
    async def test_resolve_reference_rejects_soft_deleted_and_non_completed_media_items(
        self,
    ):
        import datetime as dt

        media_repo = AsyncMock()
        asset_repo = AsyncMock()
        dto = CreateAudioDto(
            workspace_id=1,
            prompt="Add strings",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            reference_audio=AssetReferenceDto(
                id=77, type="media_item", index=0
            ),
        )

        media_repo.get_by_id.return_value = SimpleNamespace(
            id=77,
            workspace_id=1,
            status=JobStatusEnum.COMPLETED,
            deleted_at=dt.datetime.now(dt.timezone.utc),
            mime_type=MimeTypeEnum.AUDIO_MPEG,
            gcs_uris=["gs://bucket/a.mp3"],
        )
        with pytest.raises(
            ValueError, match="Media item 77 was not found in this workspace"
        ):
            await _resolve_reference_audio(dto, media_repo, asset_repo)

        for non_completed in (
            JobStatusEnum.PROCESSING,
            JobStatusEnum.FAILED,
            JobStatusEnum.STOPPED,
        ):
            media_repo.get_by_id.return_value = SimpleNamespace(
                id=77,
                workspace_id=1,
                status=non_completed,
                deleted_at=None,
                mime_type=MimeTypeEnum.AUDIO_MPEG,
                gcs_uris=["gs://bucket/a.mp3"],
            )
            with pytest.raises(
                ValueError, match="Media item 77 is not completed"
            ):
                await _resolve_reference_audio(dto, media_repo, asset_repo)

        asset_dto = CreateAudioDto(
            workspace_id=1,
            prompt="Add strings",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            reference_audio=AssetReferenceDto(id=19, type="source_asset"),
        )
        asset_repo.get_by_id.return_value = SimpleNamespace(
            id=19,
            workspace_id=1,
            scope=AssetScopeEnum.PRIVATE,
            deleted_at=dt.datetime.now(dt.timezone.utc),
            mime_type=MimeTypeEnum.AUDIO_WAV,
            gcs_uri="gs://bucket/deleted.wav",
        )
        with pytest.raises(
            ValueError, match="Source asset 19 was not found in this workspace"
        ):
            await _resolve_reference_audio(asset_dto, media_repo, asset_repo)

    def test_process_audio_in_background_closes_event_loop_on_success_and_error(
        self, sample_user
    ):
        import asyncio as aio

        created_loops: list[aio.AbstractEventLoop] = []
        real_new_loop = aio.new_event_loop

        def _track_loop():
            lp = real_new_loop()
            created_loops.append(lp)
            return lp

        dto = CreateAudioDto(
            workspace_id=1,
            prompt="Synth lead",
            model=GenerationModelEnum.LYRIA_002,
            seed=10,
        )
        with patch(
            "src.audios.audio_service.asyncio.new_event_loop",
            side_effect=_track_loop,
        ):
            with _audio_worker_env(gcs_uris="gs://foo/ok.wav") as env:
                env.run(640, dto, sample_user)
                assert created_loops[-1].is_closed()

            with _audio_worker_env() as env:
                env.gcs.store_to_gcs.side_effect = RuntimeError(
                    "gs://secret-internal-bucket/path failed"
                )
                # Force outer/inner failure and ensure error_message is sanitized
                env.ai_client.predict.return_value = MagicMock(
                    predictions=[{"bytesBase64Encoded": "SGVsbG8="}]
                )
                env.run(641, dto, sample_user)
                assert created_loops[-1].is_closed()
                failed_payload = env.media_repo.update.call_args.args[1]
                assert failed_payload["status"] == JobStatusEnum.FAILED
                assert (
                    "secret-internal-bucket"
                    not in failed_payload["error_message"]
                )

    def test_process_audio_persists_only_audio_generation_error_messages(
        self, sample_user
    ):
        dto = CreateAudioDto(
            workspace_id=1,
            prompt="Ambient pads",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            enhance_prompt=True,
        )
        with _audio_worker_env() as env:
            env.gemini.enhance_prompt_from_dto.side_effect = ValueError(
                "validation failed for gs://secret-internal-bucket/path"
            )
            env.run(642, dto, sample_user)

            env.media_repo.update.assert_called_once_with(
                642,
                {
                    "status": JobStatusEnum.FAILED,
                    "error_message": (
                        "Audio generation failed due to an internal error."
                    ),
                },
            )

    def test_process_lyria3_wav_output_extracts_waveform_and_duration(
        self, sample_user
    ):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(struct.pack("<4000h", *([12000, -12000] * 2000)))
        wav_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        with _audio_worker_env(gcs_uris="gs://foo/lyria3_wave.wav") as env:
            env.omni_client.interactions.create.return_value = MagicMock(
                id="inter_wave",
                output_audio=MagicMock(
                    type="audio", mime_type="audio/wav", data=wav_b64
                ),
                steps=None,
                outputs=None,
                output_text="[Verse]\nElectric pulse\nBPM: 120",
            )
            dto = CreateAudioDto(
                workspace_id=1,
                prompt="Electric synth pulse",
                model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            )
            env.run(643, dto, sample_user)

            updated = env.media_repo.update.call_args.args[1]
            track = updated["audio_analysis"]["tracks"][0]
            assert len(track["waveform"]) == 120
            assert track["duration_seconds"] == pytest.approx(0.5, abs=0.05)
            assert track["lyrics"] == "[Verse]\nElectric pulse"
            assert track["structure"] == {"bpm": 120}


class TestAudioServiceRevisionLineage:
    """Behavioral tests for audio parent_media_item_id authorization and lineage."""

    @pytest.mark.anyio
    async def test_start_audio_job_authorizes_parent_and_inherits_stack_folder(
        self,
        audio_service,
        mock_media_repo,
        sample_create_lyria_dto,
        sample_user,
    ):
        from src.galleries.revision_lineage import RevisionLineage
        from src.workspaces.generation_workspace import GenerationContext

        captured: list[MediaItemModel] = []

        async def _create(item: MediaItemModel) -> MediaItemModel:
            captured.append(item)
            item.id = 810
            return item

        mock_media_repo.create.side_effect = _create
        mock_executor = MagicMock()
        dto = sample_create_lyria_dto.model_copy(
            update={"workspace_id": 10, "parent_media_item_id": 805}
        )

        with (
            patch(
                "src.audios.audio_service.ensure_can_reference_inputs",
                new=AsyncMock(return_value=set()),
            ) as ensure_refs,
            patch(
                "src.audios.audio_service.resolve_generation_context",
                new=AsyncMock(return_value=GenerationContext(10, 10, None)),
            ),
            patch(
                "src.audios.audio_service.resolve_revision_lineage",
                new=AsyncMock(
                    return_value=RevisionLineage(
                        revision_root_id=800,
                        revision_parent_id=805,
                        revision_number=2,
                        inherited_folder_id=33,
                    )
                ),
            ) as mock_lineage,
        ):
            res = await audio_service.start_audio_generation_job(
                request_dto=dto,
                user=sample_user,
                executor=mock_executor,
            )

        assert res.id == 810
        assert ensure_refs.await_args.kwargs["media_item_ids"] == [805]
        assert mock_lineage.await_args.kwargs["explicit_parent_id"] == 805
        assert mock_lineage.await_args.kwargs["source_media_items"] is None
        assert captured[0].revision_root_id == 800
        assert captured[0].revision_parent_id == 805
        assert captured[0].revision_number == 2
        assert captured[0].folder_id == 33

    @pytest.mark.anyio
    async def test_start_audio_job_falls_back_to_media_item_reference_audio_for_lineage(
        self,
        audio_service,
        mock_media_repo,
        sample_create_lyria_dto,
        sample_user,
    ):
        from src.galleries.revision_lineage import RevisionLineage
        from src.workspaces.generation_workspace import GenerationContext

        captured: list[MediaItemModel] = []

        async def _create(item: MediaItemModel) -> MediaItemModel:
            captured.append(item)
            item.id = 811
            return item

        mock_media_repo.create.side_effect = _create
        mock_executor = MagicMock()
        media_ref_dto = sample_create_lyria_dto.model_copy(
            update={
                "workspace_id": 10,
                "reference_audio": AssetReferenceDto(
                    id=805, type="media_item", index=1
                ),
            }
        )
        asset_ref_dto = sample_create_lyria_dto.model_copy(
            update={
                "workspace_id": 10,
                "reference_audio": AssetReferenceDto(
                    id=905, type="source_asset", index=0
                ),
            }
        )

        with (
            patch(
                "src.audios.audio_service.ensure_can_reference_inputs",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "src.audios.audio_service.resolve_generation_context",
                new=AsyncMock(return_value=GenerationContext(10, 10, None)),
            ),
            patch(
                "src.audios.audio_service.resolve_revision_lineage",
                new=AsyncMock(
                    side_effect=[
                        RevisionLineage(
                            revision_root_id=800,
                            revision_parent_id=805,
                            revision_number=2,
                            inherited_folder_id=33,
                        ),
                        RevisionLineage(None, None, 1, None),
                    ]
                ),
            ) as mock_lineage,
        ):
            await audio_service.start_audio_generation_job(
                request_dto=media_ref_dto,
                user=sample_user,
                executor=mock_executor,
            )
            media_call = mock_lineage.await_args_list[0].kwargs
            assert media_call["explicit_parent_id"] is None
            assert len(media_call["source_media_items"]) == 1
            assert media_call["source_media_items"][0].media_item_id == 805
            assert media_call["source_media_items"][0].media_index == 1
            assert (
                media_call["source_media_items"][0].role
                == AssetRoleEnum.AUDIO_REFERENCE
            )

            await audio_service.start_audio_generation_job(
                request_dto=asset_ref_dto,
                user=sample_user,
                executor=mock_executor,
            )
            asset_call = mock_lineage.await_args_list[1].kwargs
            assert asset_call["explicit_parent_id"] is None
            assert asset_call["source_media_items"] is None

        assert captured[0].revision_root_id == 800
        assert captured[0].revision_number == 2
        assert captured[1].revision_root_id is None
        assert captured[1].revision_number == 1

    @pytest.mark.anyio
    async def test_start_audio_job_does_not_link_lyria3_reference_images_into_stack(
        self,
        audio_service,
        mock_media_repo,
        sample_user,
    ):
        from src.galleries.revision_lineage import RevisionLineage
        from src.workspaces.generation_workspace import GenerationContext

        async def _create(item: MediaItemModel) -> MediaItemModel:
            item.id = 812
            return item

        mock_media_repo.create.side_effect = _create
        mock_executor = MagicMock()
        dto = CreateAudioDto(
            workspace_id=10,
            prompt="Moody synth score inspired by image",
            model=GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=701, media_index=0, role=AssetRoleEnum.INPUT
                )
            ],
        )

        with (
            patch(
                "src.audios.audio_service.ensure_can_reference_inputs",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "src.audios.audio_service.resolve_generation_context",
                new=AsyncMock(return_value=GenerationContext(10, 10, None)),
            ),
            patch(
                "src.audios.audio_service.resolve_revision_lineage",
                new=AsyncMock(
                    return_value=RevisionLineage(None, None, 1, None)
                ),
            ) as mock_lineage,
        ):
            await audio_service.start_audio_generation_job(
                request_dto=dto,
                user=sample_user,
                executor=mock_executor,
            )

        assert mock_lineage.await_args.kwargs["explicit_parent_id"] is None
        assert mock_lineage.await_args.kwargs["source_media_items"] is None
