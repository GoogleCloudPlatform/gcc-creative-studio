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
import random
import re
import sys
import time
import wave
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
from src.audios.dto.create_audio_dto import (
    CHIRP_TTS_MODELS,
    CreateAudioDto,
    GEMINI_TTS_MODELS,
    LYRIA_2_MODELS,
    LYRIA_3_MODELS,
    LYRIA_MAX_SEED,
    LYRIA_MUSIC_MODELS,
)
from src.audios.lyria3_text import (
    _extract_lyria3_text,
    _get_attr_or_key,
    normalize_audio_analysis,
)
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.genai_model_setup import GenAIModelSetup
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    SourceAssetLink,
    SourceMediaItemLink,
)
from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.folders.output_folder import resolve_output_folder_id
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.repository.media_item_repository import MediaRepository
from src.brand_guidelines.repository.brand_guideline_repository import (
    BrandGuidelineRepository,
)
from src.multimodal.gemini_service import GeminiService, PromptTargetEnum
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.source_assets.schema.source_asset_model import AssetScopeEnum
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)


def _build_lyria3_prompt(
    request_dto: CreateAudioDto,
    prompt_override: str | None = None,
) -> str:
    """Builds the text input for a Lyria 3 interaction.

    Lyria 3 has no dedicated ``negative_prompt`` parameter, so a user-provided
    negative prompt is folded into the text as explicit guidance.
    """
    base_prompt = (
        prompt_override if prompt_override is not None else request_dto.prompt
    )
    prompt = (base_prompt or "").strip()
    negative = (request_dto.negative_prompt or "").strip()
    if negative:
        prompt = f"{prompt}\n\nAvoid: {negative}"
    return prompt


def _mime_value(mime_obj: Any) -> str:
    return mime_obj.value if hasattr(mime_obj, "value") else str(mime_obj or "")


def _first_non_empty(*values: Any) -> str:
    for val in values:
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


async def _resolve_workspace_source_asset(
    source_asset_repo: SourceAssetRepository,
    asset_id: int,
    workspace_id: int,
    kind: str,
) -> tuple[str, str]:
    asset = await source_asset_repo.get_by_id(asset_id)
    if not asset or (
        asset.workspace_id != workspace_id
        and asset.scope != AssetScopeEnum.SYSTEM
    ):
        raise ValueError(
            f"Source asset {asset_id} was not found in this workspace."
        )
    mime_val = _mime_value(asset.mime_type)
    if not asset.gcs_uri or not mime_val.startswith(f"{kind}/"):
        raise ValueError(
            f"Source asset {asset_id} is not a valid {kind} asset."
        )
    return asset.gcs_uri, mime_val


async def _resolve_workspace_media_item(
    media_repo: MediaRepository,
    media_item_id: int,
    media_index: int,
    workspace_id: int,
    kind: str,
) -> tuple[Any, str, str]:
    item = await media_repo.get_by_id(media_item_id)
    if not item or item.workspace_id != workspace_id:
        raise ValueError(
            f"Media item {media_item_id} was not found in this workspace."
        )
    if not item.gcs_uris or not (0 <= media_index < len(item.gcs_uris)):
        raise ValueError(
            f"Media item {media_item_id} index {media_index} is out of bounds."
        )
    mime_val = _mime_value(item.mime_type)
    if not mime_val.startswith(f"{kind}/"):
        raise ValueError(f"Media item {media_item_id} is not an {kind} item.")
    return item, item.gcs_uris[media_index], mime_val


async def _resolve_lyria3_reference_images(
    request_dto: CreateAudioDto,
    media_repo: MediaRepository,
    source_asset_repo: SourceAssetRepository,
) -> tuple[
    list[dict[str, str]],
    list[SourceAssetLink],
    list[SourceMediaItemLink],
]:
    """Validates and resolves uploaded/gallery reference images for Lyria 3."""
    image_inputs: list[dict[str, str]] = []
    source_assets: list[SourceAssetLink] = []
    source_media_items: list[SourceMediaItemLink] = []

    for asset_id in request_dto.source_asset_ids or []:
        gcs_uri, mime_val = await _resolve_workspace_source_asset(
            source_asset_repo, asset_id, request_dto.workspace_id, "image"
        )
        source_assets.append(
            SourceAssetLink(asset_id=asset_id, role=AssetRoleEnum.INPUT)
        )
        image_inputs.append(
            {"type": "image", "mime_type": mime_val, "uri": gcs_uri}
        )

    for gen_input in request_dto.source_media_items or []:
        _, gcs_uri, mime_val = await _resolve_workspace_media_item(
            media_repo,
            gen_input.media_item_id,
            gen_input.media_index,
            request_dto.workspace_id,
            "image",
        )
        source_media_items.append(
            SourceMediaItemLink(
                media_item_id=gen_input.media_item_id,
                media_index=gen_input.media_index,
                role=AssetRoleEnum.INPUT,
            )
        )
        image_inputs.append(
            {"type": "image", "mime_type": mime_val, "uri": gcs_uri}
        )

    return image_inputs, source_assets, source_media_items


MAX_AUDIO_ITERATION_STEPS = 6


def _is_valid_int_seed(value: Any) -> bool:
    """Returns True when ``value`` is a non-negative 32-bit int seed (excluding ``bool``)."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= LYRIA_MAX_SEED
    )


async def _resolve_reference_audio(
    request_dto: CreateAudioDto,
    media_repo: MediaRepository,
    source_asset_repo: SourceAssetRepository,
) -> tuple[
    dict[str, Any],
    SourceAssetLink | None,
    SourceMediaItemLink | None,
]:
    """Validates and resolves an uploaded or gallery reference audio for Lyria."""
    ref = request_dto.reference_audio
    if ref is None:
        raise ValueError("reference_audio is required.")

    if ref.type == "source_asset":
        gcs_uri, mime_val = await _resolve_workspace_source_asset(
            source_asset_repo, ref.id, request_dto.workspace_id, "audio"
        )
        if mime_val == MimeTypeEnum.AUDIO_MP3.value:
            mime_val = MimeTypeEnum.AUDIO_MPEG.value
        return (
            {"uri": gcs_uri, "mime_type": mime_val},
            SourceAssetLink(
                asset_id=ref.id, role=AssetRoleEnum.AUDIO_REFERENCE
            ),
            None,
        )

    if ref.type == "media_item":
        media_index = ref.index if ref.index is not None else 0
        parent_item, gcs_uri, mime_val = await _resolve_workspace_media_item(
            media_repo, ref.id, media_index, request_dto.workspace_id, "audio"
        )
        if (
            gcs_uri.lower().endswith(".mp3")
            or mime_val == MimeTypeEnum.AUDIO_MP3.value
        ):
            mime_val = MimeTypeEnum.AUDIO_MPEG.value

        context: dict[str, Any] = {"uri": gcs_uri, "mime_type": mime_val}
        raw_prompt = getattr(parent_item, "prompt", None)
        raw_orig_prompt = getattr(parent_item, "original_prompt", None)
        prior_prompt = _first_non_empty(raw_prompt, raw_orig_prompt)
        if prior_prompt:
            context["prior_prompt"] = prior_prompt

        normalized = normalize_audio_analysis(
            getattr(parent_item, "audio_analysis", None)
        )
        track_seed: int | None = None
        prior_steps: list[str] = []
        if isinstance(normalized, dict):
            raw_steps = normalized.get("iteration_steps")
            if isinstance(raw_steps, list):
                prior_steps = [
                    s.strip()
                    for s in raw_steps
                    if isinstance(s, str) and s.strip()
                ]
            tracks = normalized.get("tracks")
            if isinstance(tracks, list) and 0 <= media_index < len(tracks):
                track = tracks[media_index]
                if isinstance(track, dict):
                    for key in ("lyrics", "structure"):
                        if track.get(key):
                            context[key] = track[key]
                    profile = track.get("musical_profile")
                    if isinstance(profile, dict) and profile:
                        context["musical_profile"] = profile
                    if (
                        track.get("raw_text")
                        and not track.get("lyrics")
                        and not track.get("structure")
                    ):
                        context["raw_text"] = track["raw_text"]
                    if _is_valid_int_seed(track.get("seed")):
                        track_seed = track["seed"]

        if not prior_steps:
            seed_step = _first_non_empty(raw_orig_prompt, raw_prompt)
            if seed_step:
                prior_steps = [seed_step]
        if prior_steps:
            context["iteration_steps"] = prior_steps[
                -MAX_AUDIO_ITERATION_STEPS:
            ]

        parent_seed = getattr(parent_item, "seed", None)
        if track_seed is not None:
            context["prior_seed"] = track_seed
        elif _is_valid_int_seed(parent_seed):
            context["prior_seed"] = parent_seed

        return (
            context,
            None,
            SourceMediaItemLink(
                media_item_id=ref.id,
                media_index=media_index,
                role=AssetRoleEnum.AUDIO_REFERENCE,
            ),
        )

    raise ValueError(
        "reference_audio.type must be 'source_asset' or 'media_item'."
    )


def _build_audio_analysis(
    num_tracks: int,
    track_analyses: list[dict[str, Any] | None],
    *,
    is_music: bool,
    musical_profiles: list[dict[str, Any] | None] | None = None,
    reference_audio_context: dict[str, Any] | None = None,
    user_prompt: str | None = None,
) -> dict[str, Any] | None:
    """Builds ``audio_analysis`` for music (profiles + steps) or TTS takes."""
    tracks: list[dict[str, Any] | None] = [
        (
            dict(track_analyses[i])
            if i < len(track_analyses) and isinstance(track_analyses[i], dict)
            else None
        )
        for i in range(num_tracks)
    ]
    if not is_music:
        return (
            {"tracks": tracks} if any(t is not None for t in tracks) else None
        )

    if isinstance(musical_profiles, list):
        for idx, profile in enumerate(musical_profiles[:num_tracks]):
            if isinstance(profile, dict) and profile:
                tracks[idx] = {
                    **(tracks[idx] or {}),
                    "musical_profile": profile,
                }

    raw_prior = (reference_audio_context or {}).get("iteration_steps")
    prior_steps = (
        [s.strip() for s in raw_prior if isinstance(s, str) and s.strip()]
        if isinstance(raw_prior, list)
        else []
    )
    current_step = (user_prompt or "").strip()
    steps = ([*prior_steps, current_step] if current_step else prior_steps)[
        -MAX_AUDIO_ITERATION_STEPS:
    ]

    analysis: dict[str, Any] = {}
    if any(t is not None for t in tracks):
        analysis["tracks"] = tracks
    if steps:
        analysis["iteration_steps"] = steps
    return analysis or None


# Vertex returns HTTP 400 with ``code: content_blocked`` when Lyria 3's policy
# filter refuses a prompt. The refusal depends on the wording, so the retry
# rewords rather than repeats (see ``_simplify_lyria3_prompt``).
LYRIA_3_CONTENT_BLOCKED_CODE = "content_blocked"
LYRIA_3_CONTENT_BLOCKED_MESSAGE = (
    "content_blocked: Lyria 3 refused the prompt on policy grounds, even "
    "after retrying with a simplified brief. Please reword the prompt and "
    "try again."
)
LYRIA_3_CONTENT_BLOCKED_NO_RETRY_MESSAGE = (
    "content_blocked: Lyria 3 refused the prompt on policy grounds. Please "
    "reword the prompt and try again."
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
# Negated vocal phrases (e.g. Ads-X's "no vocals, no singing, no spoken word,
# no lyrics") must not be mistaken for vocal intent.
_LYRIA_3_NEGATED_VOCALS_RE = re.compile(
    r"\b(?:(?:no|without|zero|free\s+of)\s+|non[-\s]?)"
    r"(?:any\s+|lead\s+|backing\s+)*"
    r"(?:vocals?|sing(?:er|ing)?|sung|spoken\s+word|lyrics?|voices?|rap(?:per|ping)?|choir|falsetto)"
    r"(?:\s*(?:,|or|and|nor)\s*(?:(?:no|without)\s+|non[-\s]?)?(?:any\s+|lead\s+|backing\s+)*(?:vocals?|sing(?:er|ing)?|sung|spoken\s+word|lyrics?|voices?|rap(?:per|ping)?|choir|falsetto))*",
    re.IGNORECASE,
)
_LYRIA_3_VOCAL_INTENT_RE = re.compile(
    r"\b(?:vocals?|sing(?:er|ing)?|sung|lyrics?|soprano|alto|tenor|baritone|falsetto|choir|rap(?:per|ping)?)\b"
    r"|\[\s*(?:verse|chorus|pre-chorus|bridge|hook)\b"
    r"|^\s*(?:verse|chorus)\s*\d*\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _has_lyria3_vocal_intent(prompt: str) -> bool:
    """True when ``prompt`` asks for vocals or structured lyrics (not negated)."""
    cleaned = _LYRIA_3_NEGATED_VOCALS_RE.sub(" ", prompt or "")
    return bool(_LYRIA_3_VOCAL_INTENT_RE.search(cleaned))


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

                        permanent_gcs_uris: list[str] = []
                        uid_short = str(user_id)[:4]
                        output_mime_type = MimeTypeEnum.AUDIO_WAV
                        effective_prompt: str | None = None
                        music_prompt = request_dto.prompt
                        lyria3_image_inputs: list[dict[str, str]] = []
                        source_assets: list[SourceAssetLink] = []
                        source_media_items: list[SourceMediaItemLink] = []
                        track_analyses: list[dict[str, Any] | None] = []
                        persisted_seed: int | None = None
                        reference_audio_context: dict[str, Any] | None = None
                        source_asset_repo: SourceAssetRepository | None = None
                        is_music_model = (
                            request_dto.model in AudioService.MUSIC_MODELS
                        )

                        if (
                            request_dto.model in AudioService.LYRIA_3_MODELS
                            and (
                                request_dto.source_asset_ids
                                or request_dto.source_media_items
                            )
                        ):
                            source_asset_repo = SourceAssetRepository(db)
                            (
                                lyria3_image_inputs,
                                source_assets,
                                source_media_items,
                            ) = await _resolve_lyria3_reference_images(
                                request_dto=request_dto,
                                media_repo=media_repo,
                                source_asset_repo=source_asset_repo,
                            )

                        if (
                            is_music_model
                            and request_dto.reference_audio is not None
                        ):
                            source_asset_repo = (
                                source_asset_repo or SourceAssetRepository(db)
                            )
                            (
                                reference_audio_context,
                                ref_audio_asset_link,
                                ref_audio_media_link,
                            ) = await _resolve_reference_audio(
                                request_dto=request_dto,
                                media_repo=media_repo,
                                source_asset_repo=source_asset_repo,
                            )
                            if ref_audio_asset_link is not None:
                                source_assets.append(ref_audio_asset_link)
                            if ref_audio_media_link is not None:
                                source_media_items.append(ref_audio_media_link)

                        if is_music_model and (
                            request_dto.enhance_prompt
                            or reference_audio_context is not None
                        ):
                            part_items = [
                                *(
                                    [reference_audio_context]
                                    if reference_audio_context is not None
                                    else []
                                ),
                                *lyria3_image_inputs,
                            ]
                            extra_parts = [
                                types.Part.from_uri(
                                    file_uri=item["uri"],
                                    mime_type=item["mime_type"],
                                )
                                for item in part_items
                            ]
                            enhance_kwargs: dict[str, Any] = {
                                "dto": request_dto,
                                "target_type": PromptTargetEnum.AUDIO,
                                "extra_parts": extra_parts or None,
                            }
                            if reference_audio_context is not None:
                                enhance_kwargs["reference_audio_context"] = (
                                    reference_audio_context
                                )
                            rewritten = (
                                await gemini_service.enhance_prompt_from_dto(
                                    **enhance_kwargs
                                )
                            )
                            if rewritten and rewritten.strip():
                                music_prompt = rewritten.strip()
                                effective_prompt = music_prompt

                        async def _store_and_analyze_take(
                            *,
                            folder: str,
                            file_name: str,
                            mime_type: MimeTypeEnum | str,
                            audio_bytes: bytes,
                            base_meta: dict[str, Any] | None = None,
                        ) -> tuple[str, dict[str, Any] | None] | None:
                            gcs_uri = gcs_service.store_to_gcs(
                                folder=folder,
                                file_name=file_name,
                                mime_type=mime_type,
                                contents=audio_bytes,
                                decode=False,
                            )
                            if not gcs_uri:
                                return None
                            meta: dict[str, Any] = (
                                dict(base_meta)
                                if isinstance(base_meta, dict)
                                else {}
                            )
                            return gcs_uri, (meta or None)

                        async def _gather_valid_takes(
                            gen_fn: Any,
                        ) -> tuple[list[str], list[dict[str, Any] | None]]:
                            results = await asyncio.gather(
                                *(
                                    gen_fn(i)
                                    for i in range(request_dto.sample_count)
                                )
                            )
                            valid = [r for r in results if r is not None]
                            return [u for u, _ in valid], [a for _, a in valid]

                        if request_dto.model in AudioService.GEMINI_MODELS:
                            client = GenAIModelSetup.init()

                            async def generate_gemini(
                                index: int,
                            ) -> tuple[str, dict[str, Any] | None] | None:
                                try:
                                    voice_name = (
                                        request_dto.voice_name.value
                                        if request_dto.voice_name
                                        else VoiceEnum.PUCK.value
                                    )
                                    response = client.models.generate_content(
                                        model=request_dto.model.value,
                                        contents=[
                                            "Please read the following text: \n"
                                            + request_dto.prompt
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
                                    parts = (
                                        response.candidates[0].content.parts
                                        if response.candidates
                                        and response.candidates[0].content
                                        else None
                                    )
                                    if not parts:
                                        return None
                                    inline_data = getattr(
                                        parts[0], "inline_data", None
                                    )
                                    pcm_bytes = _decode_audio_payload(
                                        getattr(inline_data, "data", None)
                                    )
                                    if not pcm_bytes:
                                        return None
                                    wav_buffer = io.BytesIO()
                                    with wave.open(wav_buffer, "wb") as wav_f:
                                        wav_f.setnchannels(1)
                                        wav_f.setsampwidth(2)
                                        wav_f.setframerate(24000)
                                        wav_f.writeframes(pcm_bytes)
                                    return await _store_and_analyze_take(
                                        folder="gemini_audio",
                                        file_name=(
                                            f"gemini_audio_{request_dto.model.value}"
                                            f"_{media_item_id}_{uid_short}_{index}.wav"
                                        ),
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        audio_bytes=wav_buffer.getvalue(),
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Gemini generation error: {e}"
                                    )
                                    return None

                            (
                                permanent_gcs_uris,
                                track_analyses,
                            ) = await _gather_valid_takes(generate_gemini)

                        elif request_dto.model in AudioService.TTS_MODELS:
                            tts_client = texttospeech.TextToSpeechClient()

                            async def generate_tts(
                                index: int,
                            ) -> tuple[str, dict[str, Any] | None] | None:
                                try:
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
                                        voice_name = (
                                            f"{language_code}-Chirp3-HD-"
                                            f"{voice_name}"
                                        )
                                    response = await asyncio.to_thread(
                                        tts_client.synthesize_speech,
                                        input=texttospeech.SynthesisInput(
                                            text=request_dto.prompt
                                        ),
                                        voice=texttospeech.VoiceSelectionParams(
                                            language_code=language_code,
                                            name=voice_name,
                                        ),
                                        audio_config=texttospeech.AudioConfig(
                                            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                                            speaking_rate=1.0,
                                            volume_gain_db=0.0,
                                        ),
                                    )
                                    return await _store_and_analyze_take(
                                        folder="tts_audio",
                                        file_name=(
                                            f"tts_{request_dto.model.value}"
                                            f"_{media_item_id}_{uid_short}_{index}.wav"
                                        ),
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        audio_bytes=response.audio_content,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"TTS generation error: {e}"
                                    )
                                    return None

                            (
                                permanent_gcs_uris,
                                track_analyses,
                            ) = await _gather_valid_takes(generate_tts)

                        elif request_dto.model in AudioService.LYRIA_3_MODELS:
                            lyria_client = GenAIModelSetup.get_omni_client()
                            lyria3_initial_prompt = _build_lyria3_prompt(
                                request_dto, prompt_override=music_prompt
                            )
                            lyria3_state: dict[str, Any] = {
                                "prompt": lyria3_initial_prompt,
                                "blocked": False,
                                "retried": False,
                            }
                            can_simplify_retry = (
                                reference_audio_context is None
                                and not _has_lyria3_vocal_intent(
                                    request_dto.prompt or ""
                                )
                                and not _has_lyria3_vocal_intent(
                                    music_prompt or ""
                                )
                            )
                            simplified_head = (
                                _simplify_lyria3_prompt(
                                    request_dto.prompt or ""
                                )
                                if can_simplify_retry
                                else ""
                            )
                            lyria3_retry_prompt = (
                                _build_lyria3_prompt(
                                    request_dto, prompt_override=simplified_head
                                )
                                if simplified_head
                                else ""
                            )

                            async def run_lyria3(
                                prompt: str, *, include_images: bool = True
                            ) -> Any:
                                inputs: list[dict[str, str]] = [
                                    {"type": "text", "text": prompt},
                                    *(
                                        lyria3_image_inputs
                                        if include_images
                                        else []
                                    ),
                                ]
                                return await asyncio.to_thread(
                                    lyria_client.interactions.create,
                                    model=request_dto.model.value,
                                    input=inputs,
                                    timeout=AudioService.LYRIA_3_TIMEOUT_SECONDS,
                                )

                            async def generate_lyria3(
                                index: int,
                            ) -> tuple[str, dict[str, Any] | None] | None:
                                prompt = lyria3_state["prompt"]
                                try:
                                    try:
                                        interaction = await run_lyria3(prompt)
                                    except Exception as first_error:
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
                                        lyria3_state["retried"] = True
                                        interaction = await run_lyria3(
                                            lyria3_retry_prompt,
                                            include_images=False,
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
                                    ext = (
                                        "wav"
                                        if mime_type == "audio/wav"
                                        else "mp3"
                                    )
                                    return await _store_and_analyze_take(
                                        folder="lyria_audio",
                                        file_name=(
                                            f"lyria3_music_{media_item_id}"
                                            f"_{uid_short}_{index}.{ext}"
                                        ),
                                        mime_type=mime_type,
                                        audio_bytes=audio_bytes,
                                        base_meta=_extract_lyria3_text(
                                            interaction
                                        ),
                                    )
                                except Exception as e:
                                    if _is_lyria3_content_blocked(e):
                                        lyria3_state["blocked"] = True
                                    worker_logger.error(
                                        f"Lyria 3 generation error: {e}"
                                    )
                                    return None

                            (
                                permanent_gcs_uris,
                                track_analyses,
                            ) = await _gather_valid_takes(generate_lyria3)
                            output_mime_type = MimeTypeEnum.AUDIO_MPEG
                            if (
                                not permanent_gcs_uris
                                and lyria3_state["blocked"]
                            ):
                                raise ValueError(
                                    LYRIA_3_CONTENT_BLOCKED_MESSAGE
                                    if lyria3_state["retried"]
                                    else LYRIA_3_CONTENT_BLOCKED_NO_RETRY_MESSAGE
                                )
                            if lyria3_state["prompt"] != lyria3_initial_prompt:
                                effective_prompt = lyria3_state["prompt"]

                        elif request_dto.model in AudioService.LYRIA_2_MODELS:
                            ai_client = aiplatform.gapic.PredictionServiceClient(
                                client_options={
                                    "api_endpoint": "us-central1-aiplatform.googleapis.com"
                                }
                            )
                            prior_seed = (reference_audio_context or {}).get(
                                "prior_seed"
                            )
                            if _is_valid_int_seed(request_dto.seed):
                                assert request_dto.seed is not None
                                lyria2_base_seed = request_dto.seed
                            elif _is_valid_int_seed(prior_seed):
                                lyria2_base_seed = prior_seed
                            else:
                                lyria2_base_seed = random.randint(
                                    0, LYRIA_MAX_SEED - 4
                                )
                            parameters_value = json_format.ParseDict(
                                {}, struct_pb2.Value()
                            )
                            endpoint = (
                                f"projects/{cfg.PROJECT_ID}/locations/global/"
                                f"publishers/google/models/{request_dto.model.value}"
                            )

                            async def generate_music(
                                index: int,
                            ) -> tuple[str, dict[str, Any] | None] | None:
                                try:
                                    # Vertex rejects `seed` with `sample_count`.
                                    take_seed = (lyria2_base_seed + index) % (
                                        LYRIA_MAX_SEED + 1
                                    )
                                    instance_dict: dict[str, Any] = {
                                        "prompt": music_prompt,
                                        "seed": take_seed,
                                    }
                                    if request_dto.negative_prompt:
                                        instance_dict["negative_prompt"] = (
                                            request_dto.negative_prompt
                                        )
                                    instance_value = json_format.ParseDict(
                                        instance_dict, struct_pb2.Value()
                                    )
                                    response = await asyncio.to_thread(
                                        ai_client.predict,
                                        endpoint=endpoint,
                                        instances=[instance_value],
                                        parameters=parameters_value,
                                    )
                                    if not response.predictions:
                                        return None
                                    pred = response.predictions[0]
                                    audio_b64 = pred.get(
                                        "bytesBase64Encoded"
                                    ) or pred.get("audioContent")
                                    if not audio_b64:
                                        return None
                                    return await _store_and_analyze_take(
                                        folder="lyria_audio",
                                        file_name=(
                                            f"lyria_music_{media_item_id}"
                                            f"_{uid_short}_{index}.wav"
                                        ),
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        audio_bytes=base64.b64decode(audio_b64),
                                        base_meta={"seed": take_seed},
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Lyria generation error: {e}"
                                    )
                                    return None

                            (
                                permanent_gcs_uris,
                                track_analyses,
                            ) = await _gather_valid_takes(generate_music)
                            if track_analyses and track_analyses[0]:
                                persisted_seed = track_analyses[0]["seed"]

                        else:
                            raise ValueError(
                                f"Model {request_dto.model} is not supported."
                            )

                        if not permanent_gcs_uris:
                            raise ValueError(
                                "Failed to generate any audio samples."
                            )

                        generation_time = time.monotonic() - start_time

                        update_data: dict[str, Any] = {
                            "status": JobStatusEnum.COMPLETED,
                            "gcs_uris": permanent_gcs_uris,
                            "generation_time": generation_time,
                        }
                        if output_mime_type != MimeTypeEnum.AUDIO_WAV:
                            update_data["mime_type"] = output_mime_type
                        if effective_prompt:
                            update_data["prompt"] = effective_prompt
                        if persisted_seed is not None:
                            update_data["seed"] = persisted_seed
                        if source_assets:
                            update_data["source_assets"] = [
                                item.model_dump() for item in source_assets
                            ]
                        if source_media_items:
                            update_data["source_media_items"] = [
                                item.model_dump() for item in source_media_items
                            ]

                        musical_profiles: list[dict[str, Any] | None] | None = (
                            None
                        )
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
                                        " on prompt: "
                                        f"{effective_prompt or request_dto.prompt}"
                                    ),
                                    media_uris=permanent_gcs_uris,
                                    model_name=request_dto.metadata_generation_model,
                                    mime_type=output_mime_type.value,
                                    include_audio_profile=is_music_model,
                                )
                                for key in ("titles", "descriptions"):
                                    if metadata.get(key):
                                        update_data[key] = metadata[key]
                                raw_profiles = metadata.get("musical_profiles")
                                if isinstance(raw_profiles, list):
                                    musical_profiles = raw_profiles
                            except Exception as e:
                                worker_logger.warning(
                                    f"Failed to generate metadata for media item {media_item_id}: {e}"
                                )

                        audio_analysis = _build_audio_analysis(
                            num_tracks=len(permanent_gcs_uris),
                            track_analyses=track_analyses,
                            is_music=is_music_model,
                            musical_profiles=musical_profiles,
                            reference_audio_context=reference_audio_context,
                            user_prompt=request_dto.prompt,
                        )
                        if audio_analysis:
                            update_data["audio_analysis"] = audio_analysis

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
    GEMINI_MODELS = GEMINI_TTS_MODELS
    TTS_MODELS = CHIRP_TTS_MODELS
    LYRIA_2_MODELS = LYRIA_2_MODELS
    LYRIA_3_MODELS = LYRIA_3_MODELS
    MUSIC_MODELS = LYRIA_MUSIC_MODELS
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

        is_music = request_dto.model in self.MUSIC_MODELS
        folder_id = await resolve_output_folder_id(
            self.media_repo.db,
            request_dto.workspace_id,
            user,
            request_dto.folder_id,
        )
        media_post_to_save = MediaItemModel(
            user_email=user.email,
            user_id=user.id,
            mime_type=MimeTypeEnum.AUDIO_WAV,
            model=request_dto.model,
            aspect_ratio=AspectRatioEnum.RATIO_16_9,
            workspace_id=request_dto.workspace_id,
            folder_id=folder_id,
            prompt=request_dto.prompt,
            original_prompt=request_dto.prompt,
            num_media=request_dto.sample_count,
            status=JobStatusEnum.PROCESSING,
            negative_prompt=request_dto.negative_prompt if is_music else None,
            voice_name=None if is_music else request_dto.voice_name,
            language_code=None if is_music else request_dto.language_code,
            seed=request_dto.seed if is_music else None,
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
