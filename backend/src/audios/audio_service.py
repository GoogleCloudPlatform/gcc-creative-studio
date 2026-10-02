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
"""Service for audio generation and analysis."""

import asyncio
import base64
import io
import logging
import os
import re
import sys
import time
import wave
from collections.abc import MutableSequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import vertexai
from fastapi import Depends
from google.cloud import aiplatform
from google.cloud import texttospeech_v1beta1 as texttospeech
from google.cloud.logging import Client as LoggerClient
from google.cloud.logging.handlers import CloudLoggingHandler
from google.genai import types
from google.protobuf import json_format, struct_pb2

from src.audios.audio_constants import LanguageEnum, VoiceEnum
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.genai_model_setup import GenAIModelSetup
from src.common.schema.media_item_model import JobStatusEnum, MediaItemModel
from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.repository.media_item_repository import MediaRepository
from src.brand_guidelines.repository.brand_guideline_repository import (
    BrandGuidelineRepository,
)
from src.multimodal.gemini_service import GeminiService
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)


def _build_lyria3_prompt(request_dto: CreateAudioDto) -> str:
    """Builds the text input for a Lyria 3 interaction.

    Lyria 3 has no dedicated ``negative_prompt`` parameter, so a user-provided
    negative prompt is folded into the text as explicit guidance.
    """
    prompt = (request_dto.prompt or "").strip()
    negative = (request_dto.negative_prompt or "").strip()
    if negative:
        prompt = f"{prompt}\n\nAvoid: {negative}"
    return prompt


# Vertex returns HTTP 400 with ``code: content_blocked`` when Lyria 3's policy
# filter refuses a prompt. The refusal depends on the wording, so the retry
# rewords rather than repeats (see ``_simplify_lyria3_prompt``).
LYRIA_3_CONTENT_BLOCKED_CODE = "content_blocked"
LYRIA_3_CONTENT_BLOCKED_MESSAGE = (
    "content_blocked: Lyria 3 refused the prompt on policy grounds, even "
    "after retrying with a simplified brief. Please reword the prompt and "
    "try again."
)
# Words that introduce imagery/narrative rather than musical style; the
# simplified brief ends right before the first of them.
_LYRIA_3_IMAGERY_INTRODUCERS = re.compile(
    r"\b(?:featuring|with|that|which|evoking|evokes|layered|transitioning|"
    r"paired|accented|building|as if|like)\b",
    re.IGNORECASE,
)
_LYRIA_3_SIMPLIFIED_MAX_WORDS = 12
_LYRIA_3_SIMPLIFIED_SUFFIX = (
    "Instrumental background music for a commercial, clean and unobtrusive, "
    "no vocals."
)


def _is_lyria3_content_blocked(error: BaseException) -> bool:
    """True when ``error`` is a Lyria 3 policy refusal (``content_blocked``)."""
    code = getattr(error, "code", None)
    if isinstance(code, str) and code == LYRIA_3_CONTENT_BLOCKED_CODE:
        return True
    return LYRIA_3_CONTENT_BLOCKED_CODE in str(error)


def _simplify_lyria3_prompt(prompt: str) -> str:
    """Rewords a refused Lyria 3 prompt into a neutral style-only brief.

    Keeps the opening style phrase of the first sentence (cut before the
    first imagery introducer and capped at a few words) and appends a plain
    instrumental instruction. The imagery that usually draws the refusal is
    discarded; for a background bed it carries the least weight anyway.

    Returns an empty string when no usable phrase remains.
    """
    head = re.split(r"(?<=[.!?])\s+|\n", (prompt or "").strip(), maxsplit=1)[0]
    head = _LYRIA_3_IMAGERY_INTRODUCERS.split(head, maxsplit=1)[0]
    head = " ".join(head.split()[:_LYRIA_3_SIMPLIFIED_MAX_WORDS])
    head = head.strip(" ,;:-.!?")
    if not head:
        return ""
    return f"{head}. {_LYRIA_3_SIMPLIFIED_SUFFIX}"


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Reads ``name`` from a pydantic model / object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _decode_audio_payload(data: Any) -> bytes | None:
    if not data:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        return base64.b64decode(data)
    return None


def _extract_lyria3_audio(interaction: Any) -> tuple[bytes | None, str]:
    """Extracts the generated audio from a Lyria 3 ``Interaction`` response.

    The google-genai SDK exposes the first audio item as ``output_audio``; as a
    fallback this walks ``steps[].content[]`` (normalised shape) and the raw
    ``outputs[]`` list (REST shape). Returns ``(audio_bytes, mime_type)``;
    ``audio_bytes`` is ``None`` when no audio item is present.
    """
    default_mime = MimeTypeEnum.AUDIO_MPEG.value

    candidates: list[Any] = []
    output_audio = _get_attr_or_key(interaction, "output_audio")
    if output_audio is not None:
        candidates.append(output_audio)

    for step in _get_attr_or_key(interaction, "steps") or []:
        for item in _get_attr_or_key(step, "content") or []:
            candidates.append(item)

    for item in _get_attr_or_key(interaction, "outputs") or []:
        candidates.append(item)

    for item in candidates:
        if _get_attr_or_key(item, "type") not in (None, "audio"):
            continue
        audio_bytes = _decode_audio_payload(_get_attr_or_key(item, "data"))
        if audio_bytes:
            mime_type = _get_attr_or_key(item, "mime_type") or default_mime
            if mime_type == MimeTypeEnum.AUDIO_MP3.value:
                mime_type = default_mime
            return audio_bytes, str(mime_type)

    return None, default_mime


def _process_audio_in_background(
    media_item_id: int,
    request_dto: CreateAudioDto,
    user_email: str,
    user_id: int,
):
    from src.database import WorkerDatabase

    worker_logger = logging.getLogger(f"audio_worker.{media_item_id}")
    worker_logger.setLevel(logging.INFO)

    try:
        if worker_logger.hasHandlers():
            worker_logger.handlers.clear()

        if os.getenv("ENVIRONMENT") == "production":
            log_client = LoggerClient()
            handler = CloudLoggingHandler(
                log_client,
                name=f"audio_worker.{media_item_id}",
            )
            worker_logger.addHandler(handler)
        else:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - [AUDIO_WORKER] - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            worker_logger.addHandler(handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _async_worker():
            async with WorkerDatabase() as db_factory:
                async with db_factory() as db:
                    media_repo = MediaRepository(db)
                    brand_repo = BrandGuidelineRepository(db)
                    gemini_service = GeminiService(
                        brand_guideline_repo=brand_repo
                    )
                    gcs_service = GcsService()
                    cfg = config_service

                    try:
                        vertexai.init(
                            project=cfg.PROJECT_ID, location=cfg.LOCATION
                        )
                        start_time = time.monotonic()

                        permanent_gcs_uris = []
                        uid_short = str(user_id)[:4]
                        # Media items are created as WAV; Lyria 3 returns MP3.
                        output_mime_type = MimeTypeEnum.AUDIO_WAV
                        # Set when a reworded prompt (not the user's) rendered.
                        effective_prompt: str | None = None

                        if request_dto.model in AudioService.GEMINI_MODELS:
                            client = GenAIModelSetup.init()

                            async def generate_gemini(index: int) -> str | None:
                                try:
                                    voice_name = (
                                        request_dto.voice_name.value
                                        if request_dto.voice_name
                                        else VoiceEnum.PUCK.value
                                    )
                                    response = client.models.generate_content(
                                        model=request_dto.model.value,
                                        contents=[
                                            (
                                                "Please read the following text: \n"
                                                + request_dto.prompt
                                            )
                                        ],
                                        config=types.GenerateContentConfig(
                                            response_modalities=["AUDIO"],
                                            audio_timestamp=False,
                                            speech_config=types.SpeechConfig(
                                                voice_config=types.VoiceConfig(
                                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                                        voice_name=voice_name,
                                                    ),
                                                ),
                                            ),
                                        ),
                                    )
                                    if (
                                        not response.candidates
                                        or not response.candidates[0].content
                                        or not response.candidates[
                                            0
                                        ].content.parts
                                    ):
                                        return None
                                    part = response.candidates[0].content.parts[
                                        0
                                    ]
                                    pcm_bytes = None
                                    if (
                                        hasattr(part, "inline_data")
                                        and part.inline_data
                                    ):
                                        pcm_bytes = part.inline_data.data
                                        if isinstance(pcm_bytes, str):
                                            pcm_bytes = base64.b64decode(
                                                pcm_bytes
                                            )
                                    if not pcm_bytes:
                                        return None
                                    wav_buffer = io.BytesIO()
                                    with wave.open(
                                        wav_buffer, "wb"
                                    ) as wav_file:
                                        wav_file.setnchannels(1)
                                        wav_file.setsampwidth(2)
                                        wav_file.setframerate(24000)
                                        wav_file.writeframes(pcm_bytes)
                                    final_wav_bytes = wav_buffer.getvalue()
                                    file_name = f"gemini_audio_{request_dto.model.value}_{media_item_id}_{uid_short}_{index}.wav"
                                    return gcs_service.store_to_gcs(
                                        folder="gemini_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        contents=final_wav_bytes,
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Gemini generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_gemini(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        elif request_dto.model in AudioService.TTS_MODELS:
                            tts_client = texttospeech.TextToSpeechClient()

                            async def generate_tts(index: int) -> str | None:
                                try:
                                    synthesis_input = (
                                        texttospeech.SynthesisInput(
                                            text=request_dto.prompt
                                        )
                                    )
                                    voice_name = (
                                        request_dto.voice_name.value
                                        if request_dto.voice_name
                                        else VoiceEnum.PUCK.value
                                    )
                                    language_code = (
                                        request_dto.language_code.value
                                        if request_dto.language_code
                                        else LanguageEnum.EN_US.value
                                    )
                                    if (
                                        request_dto.model
                                        == GenerationModelEnum.CHIRP_3
                                    ):
                                        voice_name = f"{language_code}-Chirp3-HD-{voice_name}"
                                    voice_params = (
                                        texttospeech.VoiceSelectionParams(
                                            language_code=language_code,
                                            name=voice_name,
                                        )
                                    )
                                    audio_config = texttospeech.AudioConfig(
                                        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                                        speaking_rate=1.0,
                                        volume_gain_db=0.0,
                                    )
                                    response = await asyncio.to_thread(
                                        tts_client.synthesize_speech,
                                        input=synthesis_input,
                                        voice=voice_params,
                                        audio_config=audio_config,
                                    )
                                    file_name = f"tts_{request_dto.model.value}_{media_item_id}_{uid_short}_{index}.wav"
                                    return gcs_service.store_to_gcs(
                                        folder="tts_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        contents=response.audio_content,
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"TTS generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_tts(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        elif request_dto.model in AudioService.LYRIA_3_MODELS:
                            # Lyria 3 is only exposed through the Interactions
                            # API on the global endpoint (no :predict support).
                            lyria_client = GenAIModelSetup.get_omni_client()
                            lyria3_state: dict[str, Any] = {
                                "prompt": _build_lyria3_prompt(request_dto),
                                "blocked": False,
                            }
                            lyria3_retry_prompt = _simplify_lyria3_prompt(
                                request_dto.prompt or ""
                            )

                            async def run_lyria3(prompt: str) -> Any:
                                return await asyncio.to_thread(
                                    lyria_client.interactions.create,
                                    model=request_dto.model.value,
                                    input=[{"type": "text", "text": prompt}],
                                    timeout=AudioService.LYRIA_3_TIMEOUT_SECONDS,
                                )

                            async def generate_lyria3(index: int) -> str | None:
                                prompt = lyria3_state["prompt"]
                                try:
                                    try:
                                        interaction = await run_lyria3(prompt)
                                    except Exception as first_error:
                                        # The refusal depends on the wording,
                                        # so retry once with a reworded brief
                                        # (still Lyria 3) instead of repeating.
                                        if not (
                                            _is_lyria3_content_blocked(
                                                first_error
                                            )
                                            and lyria3_retry_prompt
                                            and lyria3_retry_prompt != prompt
                                        ):
                                            raise
                                        worker_logger.warning(
                                            "Lyria 3 refused the prompt on "
                                            "policy grounds (content_blocked). "
                                            "Retrying with a simplified brief: "
                                            "%r",
                                            lyria3_retry_prompt,
                                        )
                                        interaction = await run_lyria3(
                                            lyria3_retry_prompt
                                        )
                                        lyria3_state["prompt"] = (
                                            lyria3_retry_prompt
                                        )
                                    audio_bytes, mime_type = (
                                        _extract_lyria3_audio(interaction)
                                    )
                                    if not audio_bytes:
                                        worker_logger.error(
                                            "Lyria 3 interaction %s returned no audio output.",
                                            getattr(interaction, "id", None),
                                        )
                                        return None

                                    extension = (
                                        "wav"
                                        if mime_type == "audio/wav"
                                        else "mp3"
                                    )
                                    file_name = f"lyria3_music_{media_item_id}_{uid_short}_{index}.{extension}"
                                    return gcs_service.store_to_gcs(
                                        folder="lyria_audio",
                                        file_name=file_name,
                                        mime_type=mime_type,
                                        contents=audio_bytes,
                                        decode=False,
                                    )
                                except Exception as e:
                                    if _is_lyria3_content_blocked(e):
                                        lyria3_state["blocked"] = True
                                    worker_logger.error(
                                        f"Lyria 3 generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_lyria3(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]
                            output_mime_type = MimeTypeEnum.AUDIO_MPEG
                            if (
                                not permanent_gcs_uris
                                and lyria3_state["blocked"]
                            ):
                                raise ValueError(
                                    LYRIA_3_CONTENT_BLOCKED_MESSAGE
                                )
                            if lyria3_state["prompt"] != _build_lyria3_prompt(
                                request_dto
                            ):
                                # Record the brief that actually rendered;
                                # ``original_prompt`` keeps the user's text.
                                effective_prompt = lyria3_state["prompt"]

                        elif request_dto.model in AudioService.LYRIA_2_MODELS:
                            client_options = {
                                "api_endpoint": "us-central1-aiplatform.googleapis.com"
                            }
                            ai_client = (
                                aiplatform.gapic.PredictionServiceClient(
                                    client_options=client_options
                                )
                            )

                            async def generate_music(index: int) -> str | None:
                                try:
                                    parameters_dict = {"sample_count": 1}
                                    parameters_value = struct_pb2.Value()
                                    json_format.ParseDict(
                                        parameters_dict, parameters_value
                                    )

                                    instance_dict = {
                                        "prompt": request_dto.prompt
                                    }
                                    if request_dto.negative_prompt:
                                        instance_dict["negative_prompt"] = (
                                            request_dto.negative_prompt
                                        )
                                    if request_dto.seed:
                                        instance_dict["seed"] = request_dto.seed

                                    instance_value = struct_pb2.Value()
                                    json_format.ParseDict(
                                        instance_dict, instance_value
                                    )

                                    endpoint = f"projects/{cfg.PROJECT_ID}/locations/global/publishers/google/models/{request_dto.model.value}"
                                    response = await asyncio.to_thread(
                                        ai_client.predict,
                                        endpoint=endpoint,
                                        instances=[instance_value],
                                        parameters=parameters_value,
                                    )
                                    if not response.predictions:
                                        return None
                                    prediction = response.predictions[0]
                                    audio_b64 = prediction.get(
                                        "bytesBase64Encoded"
                                    ) or prediction.get("audioContent")
                                    if not audio_b64:
                                        return None

                                    file_name = f"lyria_music_{media_item_id}_{uid_short}_{index}.wav"
                                    return gcs_service.store_to_gcs(
                                        folder="lyria_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        contents=base64.b64decode(audio_b64),
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Lyria generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_music(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        else:
                            raise ValueError(
                                f"Model {request_dto.model} is not supported."
                            )

                        if not permanent_gcs_uris:
                            raise ValueError(
                                "Failed to generate any audio samples."
                            )

                        generation_time = time.monotonic() - start_time

                        update_data = {
                            "status": JobStatusEnum.COMPLETED,
                            "gcs_uris": permanent_gcs_uris,
                            "generation_time": generation_time,
                        }
                        if output_mime_type != MimeTypeEnum.AUDIO_WAV:
                            # Media item was created as WAV; fix it so the
                            # gallery/lightbox serve the right content type.
                            update_data["mime_type"] = output_mime_type
                        if effective_prompt:
                            update_data["prompt"] = effective_prompt
                        if (
                            getattr(
                                request_dto, "metadata_generation_model", None
                            )
                            and permanent_gcs_uris
                        ):
                            try:
                                metadata = await asyncio.to_thread(
                                    gemini_service.generate_media_metadata,
                                    prompt=(
                                        "Describe this generated audio based"
                                        f" on prompt: {request_dto.prompt}"
                                    ),
                                    media_uris=permanent_gcs_uris,
                                    model_name=request_dto.metadata_generation_model,
                                    mime_type="audio/mpeg",
                                )
                                titles = metadata.get("titles")
                                if titles:
                                    update_data["titles"] = titles
                                descriptions = metadata.get("descriptions")
                                if descriptions:
                                    update_data["descriptions"] = descriptions
                            except Exception as e:
                                worker_logger.warning(
                                    f"Failed to generate metadata for media item {media_item_id}: {e}"
                                )

                        await media_repo.update(media_item_id, update_data)
                        worker_logger.info(
                            f"Audio job {media_item_id} completed successfully."
                        )

                    except Exception as e:
                        worker_logger.error(
                            f"Audio processing failed: {e}", exc_info=True
                        )
                        await media_repo.update(
                            media_item_id,
                            {
                                "status": JobStatusEnum.FAILED,
                                "error_message": str(e),
                            },
                        )

        loop.run_until_complete(_async_worker())
    except Exception as outer_e:
        worker_logger.error(
            f"Fatal error in worker thread: {outer_e}", exc_info=True
        )


class AudioService:
    GEMINI_MODELS = {
        GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
        GenerationModelEnum.GEMINI_2_5_FLASH_LITE_PREVIEW_TTS,
        GenerationModelEnum.GEMINI_2_5_PRO_TTS,
        GenerationModelEnum.GEMINI_3_1_FLASH_TTS_PREVIEW,
    }
    TTS_MODELS = {
        GenerationModelEnum.CHIRP_3,
    }
    # Lyria 2 is served through the regional PredictionService (:predict).
    LYRIA_2_MODELS = {
        GenerationModelEnum.LYRIA_002,
    }
    # Lyria 3 is served only through the Interactions API on `global`.
    LYRIA_3_MODELS = {
        GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
    }
    MUSIC_MODELS = LYRIA_2_MODELS | LYRIA_3_MODELS
    # Lyria 3 Pro renders full songs (up to ~3 min); keep a generous ceiling.
    LYRIA_3_TIMEOUT_SECONDS = 600.0

    def __init__(
        self,
        media_repo: MediaRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
    ):
        self.iam_signer_credentials = iam_signer_credentials
        self.media_repo = media_repo

    async def start_audio_generation_job(
        self,
        request_dto: CreateAudioDto,
        user: UserModel,
        executor: ThreadPoolExecutor,
    ) -> MediaItemResponse:

        media_post_to_save = MediaItemModel(
            user_email=user.email,
            user_id=user.id,
            mime_type=MimeTypeEnum.AUDIO_WAV,
            model=request_dto.model,
            aspect_ratio=AspectRatioEnum.RATIO_16_9,
            workspace_id=request_dto.workspace_id,
            prompt=request_dto.prompt,
            original_prompt=request_dto.prompt,
            num_media=request_dto.sample_count,
            status=JobStatusEnum.PROCESSING,
            negative_prompt=request_dto.negative_prompt,
            voice_name=request_dto.voice_name,
            language_code=request_dto.language_code,
            seed=request_dto.seed,
            gcs_uris=[],
            comment=request_dto.file_name,
            titles=request_dto.titles,
            descriptions=request_dto.descriptions,
        )
        saved_item = await self.media_repo.create(media_post_to_save)

        executor.submit(
            _process_audio_in_background,
            saved_item.id,
            request_dto,
            user.email,
            user.id,
        )

        return MediaItemResponse(
            **saved_item.model_dump(),
            presigned_urls=[],
        )
