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
    LYRIA_3_CONTENT_BLOCKED_MESSAGE,
    AudioService,
    _build_lyria3_prompt,
    _extract_lyria3_audio,
    _is_lyria3_content_blocked,
    _process_audio_in_background,
    _simplify_lyria3_prompt,
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
