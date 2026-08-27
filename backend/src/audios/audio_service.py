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

                        elif request_dto.model in AudioService.MUSIC_MODELS:
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
                                    audio_b64 = response.predictions[0].get(
                                        "bytesBase64Encoded"
                                    )
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
    MUSIC_MODELS = {
        GenerationModelEnum.LYRIA_002,
        GenerationModelEnum.LYRIA_3_CLIP_PREVIEW,
        GenerationModelEnum.LYRIA_3_PRO_PREVIEW,
    }

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
