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

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.common.base_dto import GenerationModelEnum
from src.common.schema.media_item_model import (
    MediaItemModel,
    MimeTypeEnum,
    JobStatusEnum,
)
from src.users.user_model import UserModel
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.audios.audio_service import (
    AudioService,
    _build_lyria3_prompt,
    _extract_lyria3_audio,
    _process_audio_in_background,
)
from src.audios.audio_constants import LanguageEnum, VoiceEnum


@pytest.fixture(name="mock_media_repo")
def fixture_mock_media_repo():
    repo = AsyncMock()
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
        mock_executor.submit.assert_called_once()


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

        mock_repo.update.assert_called_with(
            126,
            {
                "status": JobStatusEnum.COMPLETED,
                "gcs_uris": ["gs://foo/gemini.wav"],
                "generation_time": pytest.approx(0, abs=10.0),
            },
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
