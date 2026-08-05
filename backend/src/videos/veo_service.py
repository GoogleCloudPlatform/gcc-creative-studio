# Copyright 2024 Google LLC
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


import asyncio
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, HTTPException
from google.cloud.logging import Client as LoggerClient
from google.cloud.logging.handlers import CloudLoggingHandler
from google.genai import Client, types
import base64

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    GenerationModelEnum,
    MimeTypeEnum,
    ReferenceImageTypeEnum,
)
from src.common.media_utils import concatenate_videos, generate_thumbnail
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
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.repository.media_item_repository import MediaRepository
from src.multimodal.gemini_service import GeminiService, PromptTargetEnum
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.users.user_model import UserModel
from src.videos.dto.concatenate_videos_dto import ConcatenateVideosDto
from src.videos.dto.create_veo_dto import OMNI_MODELS, CreateVeoDto

logger = logging.getLogger(__name__)

VIDEO_RESOLUTION_MAP = {
    "1K": "720p",
    "2K": "1080p",
    "4K": "4k",
}

# --- GEMINI OMNI (INTERACTIONS API) HELPERS ---

# Task modes accepted by generation_config.video_config.task. Without one the
# model infers intent from the prompt and media ordering, which is how a
# reference image ends up being treated as a final frame.
OMNI_TASK_TEXT_TO_VIDEO = "text_to_video"
OMNI_TASK_IMAGE_TO_VIDEO = "image_to_video"
OMNI_TASK_REFERENCE_TO_VIDEO = "reference_to_video"
OMNI_TASK_EDIT = "edit"

# Generation can run well over a minute. Without a ceiling a stalled request
# holds one of the shared executor's threads for the life of the process.
OMNI_REQUEST_TIMEOUT_SECONDS = 600.0


def resolve_omni_task(
    *,
    is_edit: bool,
    has_references: bool,
    has_start_image: bool,
) -> str:
    """Picks the explicit Omni task mode for a request.

    Order matters: an edit stays an edit even when references are attached, and
    references outrank a start image because reference-to-video is the more
    specific intent.

    The caller omits the task entirely when replaying a prior conversation's
    steps, following Google's Vertex sample — the replayed steps already carry
    the intent. A stateless edit does send it.
    """
    if is_edit:
        return OMNI_TASK_EDIT
    if has_references:
        return OMNI_TASK_REFERENCE_TO_VIDEO
    if has_start_image:
        return OMNI_TASK_IMAGE_TO_VIDEO
    return OMNI_TASK_TEXT_TO_VIDEO


def build_omni_response_format(
    *,
    aspect_ratio: str | None,
    duration_seconds: int | None,
    gcs_output_directory: str,
) -> dict:
    """Builds the response_format block for an Omni interaction.

    Aspect ratio and duration are both omitted for edits, which inherit the
    dimensions and length of the clip being modified. Sending either is
    rejected: "Aspect ratio cannot be set in response format for edit task."
    """
    response_format: dict = {
        "type": "video",
        # Inline base64 is capped around 4MB, which an 8s 720p clip routinely
        # exceeds. URI delivery also lets Vertex write straight to the bucket.
        "delivery": "uri",
        "gcs_uri": gcs_output_directory,
    }
    if aspect_ratio is not None:
        response_format["aspect_ratio"] = aspect_ratio
    if duration_seconds is not None:
        response_format["duration"] = f"{duration_seconds}s"
    return response_format


def serialize_omni_steps(steps) -> list[dict] | None:
    """Converts interaction steps to JSON for storage, for later replay.

    Vertex has no server-side conversation state for this model, so a follow-up
    turn works by resending the previous turn's steps. They therefore have to be
    kept.

    Returns None when any step carries inline media, which only happens if the
    response came back as base64 rather than a URI. Persisting a whole video
    into a JSONB column is not worth it, and a partial copy would replay a turn
    with the video missing.
    """
    if not steps:
        return None

    serialized: list[dict] = []
    for step in steps:
        if hasattr(step, "model_dump"):
            entry = step.model_dump(mode="json", exclude_none=True)
        elif isinstance(step, dict):
            entry = step
        else:
            return None

        for content in entry.get("content") or []:
            if isinstance(content, dict) and content.get("data"):
                return None

        serialized.append(entry)

    return serialized or None


def extract_omni_interaction_entry(
    raw_data: dict | None,
    media_index: int,
) -> dict | None:
    """Reads the stored interaction record for one clip of a parent item.

    A job can produce several clips, each from its own interaction, so an edit
    has to continue the conversation belonging to the clip the user selected.
    """
    if not raw_data:
        return None

    interactions = raw_data.get("interactions")
    if not isinstance(interactions, list) or not interactions:
        return None

    if not 0 <= media_index < len(interactions):
        media_index = 0

    entry = interactions[media_index]
    return entry if isinstance(entry, dict) else None


def build_omni_followup_input(
    previous_steps: list[dict],
    prompt: str,
) -> list[dict]:
    """Builds the input for a follow-up turn.

    The documented Vertex pattern is to resend the previous interaction's steps
    with a new user turn appended. Note this differs from the Gemini API path,
    which uses `previous_interaction_id` — Vertex rejects that parameter for
    this model.
    """
    return [
        *previous_steps,
        {
            "type": "user_input",
            "content": [{"type": "text", "text": prompt}],
        },
    ]


def gcs_uri_to_blob_path(gcs_uri: str) -> str:
    """Strips the ``gs://<bucket>/`` prefix from a URI.

    GcsService.download_from_gcs takes a bucket-relative blob path. Matching on
    the configured bucket name alone silently leaves the full URI in place when
    the model writes somewhere slightly different, and the download then fails
    with only a log line to show for it.
    """
    if not gcs_uri.startswith("gs://"):
        return gcs_uri
    without_scheme = gcs_uri[len("gs://") :]
    _, separator, blob_path = without_scheme.partition("/")
    return blob_path if separator else ""


def is_retryable_omni_error(error: Exception) -> bool:
    """Whether an Interactions API failure is worth retrying.

    Client errors such as a malformed request or a content block will fail
    identically on every attempt, so retrying them only delays the error the
    caller needs to see.
    """
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if isinstance(status, int) and 400 <= status < 500:
        # 408 Request Timeout and 429 Too Many Requests are transient.
        return status in (408, 429)
    return True


# --- STANDALONE WORKER FUNCTION ---
# This function will run in the background thread. It is defined outside the class.
def _process_video_in_background(
    media_item_id: int,
    request_dto: CreateVeoDto,
    user_email: str,
):  # type: ignore
    """This is the long-running worker task. It creates its own service instances
    because it runs in a separate thread.
    The long-running process that generates video, thumbnails, and updates the
    database record upon completion or failure.
    """
    from src.database import WorkerDatabase

    # In a new process, the logging configuration is reset. We must re-configure it
    # to see logs with a level of INFO or lower.
    # --- HYBRID LOGGING SETUP FOR THE WORKER PROCESS ---
    worker_logger = logging.getLogger(f"video_worker.{media_item_id}")
    worker_logger.setLevel(logging.INFO)

    try:
        # Clear any handlers that might be inherited from the parent process
        if worker_logger.hasHandlers():
            worker_logger.handlers.clear()

        if os.getenv("ENVIRONMENT") == "production":
            # In PRODUCTION, use the CloudLoggingHandler for structured JSON logs.
            log_client = LoggerClient()
            handler = CloudLoggingHandler(
                log_client,
                name=f"video_worker.{media_item_id}",
            )
            worker_logger.addHandler(handler)
        else:
            # In DEVELOPMENT, use a simple stream handler for readable console output.
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - [VIDEO_WORKER] - %(levelname)s - %(message)s",
            )
            handler.setFormatter(formatter)
            worker_logger.addHandler(handler)

        # Create a new event loop for this process
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _async_worker():
            async with WorkerDatabase() as db_factory:
                async with db_factory() as db:
                    # Create new instances of dependencies within this process
                    media_repo = MediaRepository(db)
                    source_asset_repo = SourceAssetRepository(db)
                    gemini_service = GeminiService(
                        brand_guideline_repo=None,
                    )  # BrandGuidelineRepo not strictly needed for prompt enhancement if not using guidelines, but let's check if GeminiService needs it.
                    # Actually GeminiService init: def __init__(self, brand_guideline_repo: BrandGuidelineRepository = Depends()):
                    # If we pass None, it might fail if it tries to use it.
                    # Let's instantiate BrandGuidelineRepository too if needed.
                    # Checking GeminiService usage: enhance_prompt_from_dto.
                    # It might use brand guidelines.
                    # Let's instantiate it to be safe.
                    from src.brand_guidelines.repository.brand_guideline_repository import (
                        BrandGuidelineRepository,
                    )

                    brand_guideline_repo = BrandGuidelineRepository(db)
                    gemini_service = GeminiService(
                        brand_guideline_repo=brand_guideline_repo,
                    )

                    gcs_service = GcsService()

                    try:
                        client = GenAIModelSetup.init()
                        cfg = config_service
                        gcs_output_directory = f"gs://{cfg.GENMEDIA_BUCKET}"

                        if request_dto.enhance_prompt:
                            rewritten_prompt = (
                                await gemini_service.enhance_prompt_from_dto(
                                    dto=request_dto,
                                    target_type=PromptTargetEnum.VIDEO,
                                )
                            )
                            # Update the prompt in the DTO for logging and future reference
                            request_dto.prompt = rewritten_prompt
                        else:
                            rewritten_prompt = request_dto.prompt

                        # --- Handle Source Assets for API Call ---
                        start_image_for_api: types.Image | None = None
                        end_image_for_api: types.Image | None = None
                        reference_images_for_api: list[
                            types.VideoGenerationReferenceImage
                        ] = []  # 1. Create a list for reference images

                        # --- Handle Video Extension ---
                        source_video_for_api: types.Video | None = None

                        # --- Handle Generated Inputs for Source Assets (start/end frames, source video, and references) ---
                        if request_dto.source_video_asset_id:
                            ref = request_dto.source_video_asset_id
                            if ref.type == "media_item":
                                parent_item = await media_repo.get_by_id(ref.id)
                                if parent_item and parent_item.gcs_uris:
                                    source_video_for_api = types.Video(
                                        uri=parent_item.gcs_uris[0],
                                        mime_type=parent_item.mime_type,
                                    )
                            else:
                                video_asset = await source_asset_repo.get_by_id(
                                    ref.id
                                )
                                if video_asset:
                                    source_video_for_api = types.Video(
                                        uri=video_asset.gcs_uri,
                                        mime_type=video_asset.mime_type,
                                    )
                                else:
                                    worker_logger.warning(
                                        f"Could not find source video asset: {ref.id}",
                                    )
                        if request_dto.start_image_asset_id:
                            ref = request_dto.start_image_asset_id
                            if ref.type == "media_item":
                                parent_item = await media_repo.get_by_id(ref.id)
                                if parent_item and parent_item.gcs_uris:
                                    start_image_for_api = types.Image(
                                        gcs_uri=parent_item.gcs_uris[0],
                                        mime_type=parent_item.mime_type,
                                    )
                            else:
                                start_asset = await source_asset_repo.get_by_id(
                                    ref.id
                                )
                                if start_asset:
                                    start_image_for_api = types.Image(
                                        gcs_uri=start_asset.gcs_uri,
                                        mime_type=start_asset.mime_type,
                                    )

                        if request_dto.end_image_asset_id:
                            ref = request_dto.end_image_asset_id
                            if ref.type == "media_item":
                                parent_item = await media_repo.get_by_id(ref.id)
                                if parent_item and parent_item.gcs_uris:
                                    end_image_for_api = types.Image(
                                        gcs_uri=parent_item.gcs_uris[0],
                                        mime_type=parent_item.mime_type,
                                    )
                            else:
                                end_asset = await source_asset_repo.get_by_id(
                                    ref.id
                                )
                                if end_asset:
                                    end_image_for_api = types.Image(
                                        gcs_uri=end_asset.gcs_uri,
                                        mime_type=end_asset.mime_type,
                                    )

                        if request_dto.reference_images:
                            worker_logger.info(
                                f"Loading {len(request_dto.reference_images)} reference images.",
                            )
                            for ref_dto in request_dto.reference_images:
                                asset = await source_asset_repo.get_by_id(
                                    ref_dto.asset_id,
                                )
                                if asset and asset.gcs_uri:
                                    image = types.Image(
                                        gcs_uri=asset.gcs_uri,
                                        mime_type=asset.mime_type,
                                    )

                                    # Map our DTO enum to the Google SDK's enum
                                    sdk_ref_type = None
                                    if (
                                        ref_dto.reference_type
                                        == ReferenceImageTypeEnum.ASSET
                                    ):
                                        sdk_ref_type = (
                                            types.VideoGenerationReferenceType.ASSET
                                        )
                                    elif (
                                        ref_dto.reference_type
                                        == ReferenceImageTypeEnum.STYLE
                                    ):
                                        sdk_ref_type = (
                                            types.VideoGenerationReferenceType.STYLE
                                        )

                                    if sdk_ref_type:
                                        reference_images_for_api.append(
                                            types.VideoGenerationReferenceImage(
                                                image=image,
                                                reference_type=sdk_ref_type,
                                            ),
                                        )

                        # --- Handle Generated Inputs for Media Items (start/end frames, source video, and references) ---
                        if request_dto.source_media_items:
                            for gen_input in request_dto.source_media_items:
                                parent_item = await media_repo.get_by_id(
                                    gen_input.media_item_id,
                                )
                                if (
                                    parent_item
                                    and parent_item.gcs_uris
                                    and 0
                                    <= gen_input.media_index
                                    < len(parent_item.gcs_uris)
                                ):
                                    gcs_uri = parent_item.gcs_uris[
                                        gen_input.media_index
                                    ]
                                    image_for_api = types.Image(
                                        gcs_uri=gcs_uri,
                                        mime_type=parent_item.mime_type,
                                    )

                                    if (
                                        gen_input.role
                                        == AssetRoleEnum.START_FRAME
                                    ):
                                        start_image_for_api = image_for_api
                                    elif (
                                        gen_input.role
                                        == AssetRoleEnum.END_FRAME
                                    ):
                                        end_image_for_api = image_for_api
                                    elif (
                                        gen_input.role
                                        == AssetRoleEnum.VIDEO_EXTENSION_SOURCE
                                    ):
                                        source_video_for_api = types.Video(
                                            uri=gcs_uri,
                                            mime_type=parent_item.mime_type,
                                        )
                                    elif (
                                        gen_input.role
                                        == AssetRoleEnum.IMAGE_REFERENCE_ASSET
                                    ):
                                        image_for_api = types.Image(
                                            gcs_uri=gcs_uri,
                                            mime_type=parent_item.mime_type,
                                        )
                                        reference_images_for_api.append(
                                            types.VideoGenerationReferenceImage(
                                                image=image_for_api,
                                                reference_type=types.VideoGenerationReferenceType.ASSET,
                                            ),
                                        )
                                    elif (
                                        gen_input.role
                                        == AssetRoleEnum.IMAGE_REFERENCE_STYLE
                                    ):
                                        image_for_api = types.Image(
                                            gcs_uri=gcs_uri,
                                            mime_type=parent_item.mime_type,
                                        )
                                        reference_images_for_api.append(
                                            types.VideoGenerationReferenceImage(
                                                image=image_for_api,
                                                reference_type=types.VideoGenerationReferenceType.STYLE,
                                            ),
                                        )
                                else:
                                    worker_logger.warning(
                                        f"Could not find or use generated_input: {gen_input.media_item_id} at index {gen_input.media_index}",
                                    )

                        # Validation to prevent conflicting inputs
                        if reference_images_for_api and (
                            start_image_for_api
                            or end_image_for_api
                            or source_video_for_api
                        ):
                            raise ValueError(
                                "Reference images cannot be used at the same time as a start/end image or a source video.",
                            )

                        all_generated_videos: list[types.GeneratedVideo] = []
                        permanent_thumbnail_gcs_uris = []
                        final_gcs_uris = []
                        raw_data_dict = None
                        model_name_for_api = request_dto.generation_model.value

                        start_time = time.monotonic()

                        if request_dto.generation_model in OMNI_MODELS:
                            worker_logger.info(
                                "Running Gemini Omni video generation via Interactions API..."
                            )
                            vertex_client = GenAIModelSetup.get_omni_client()

                            interaction_id = None
                            thought_signature = None

                            # Resolve the reference video URI and its real mime
                            # type. Audio references are rejected upstream by
                            # CreateVeoDto: Omni accepts an audio part and then
                            # ignores it, so there is nothing to resolve here.
                            ref_video_uri = None
                            ref_video_mime_type = None
                            if request_dto.reference_video:
                                ref = request_dto.reference_video
                                if ref.type == "media_item":
                                    parent_item = await media_repo.get_by_id(
                                        ref.id
                                    )
                                    if parent_item and parent_item.gcs_uris:
                                        index = ref.index or 0
                                        if not (
                                            0
                                            <= index
                                            < len(parent_item.gcs_uris)
                                        ):
                                            index = 0
                                        ref_video_uri = parent_item.gcs_uris[
                                            index
                                        ]
                                        ref_video_mime_type = (
                                            parent_item.mime_type
                                        )
                                else:
                                    video_asset = (
                                        await source_asset_repo.get_by_id(
                                            ref.id
                                        )
                                    )
                                    if video_asset:
                                        ref_video_uri = video_asset.gcs_uri
                                        ref_video_mime_type = (
                                            video_asset.mime_type
                                        )

                            # --- Continue from a previous clip, if asked ---
                            # Vertex holds no conversation state for this model,
                            # so there are two ways to build on an earlier clip:
                            #
                            #   1. Replay the prior interaction's steps with a
                            #      new user turn appended. Keeps the whole
                            #      conversation, so earlier instructions still
                            #      apply.
                            #   2. Send the clip itself as a video part with
                            #      task=edit. Stateless, but works for any clip
                            #      including ones generated before steps were
                            #      being stored.
                            #
                            # Prefer 1 when the steps are available and fall back
                            # to 2, so older library items stay editable.
                            previous_steps = None
                            edit_source_uri = None
                            edit_source_mime = None

                            # An explicitly chosen clip to edit. Works for
                            # uploaded footage as well as library items, and
                            # always starts a fresh conversation.
                            if request_dto.edit_source:
                                ref = request_dto.edit_source
                                if ref.type == "media_item":
                                    item = await media_repo.get_by_id(ref.id)
                                    if item and item.gcs_uris:
                                        index = ref.index or 0
                                        if not 0 <= index < len(item.gcs_uris):
                                            index = 0
                                        edit_source_uri = item.gcs_uris[index]
                                        edit_source_mime = item.mime_type
                                else:
                                    asset = await source_asset_repo.get_by_id(
                                        ref.id
                                    )
                                    if asset:
                                        edit_source_uri = asset.gcs_uri
                                        edit_source_mime = asset.mime_type

                                if not edit_source_uri:
                                    raise ValueError(
                                        f"Could not resolve a video to edit "
                                        f"from {ref.type} {ref.id}.",
                                    )

                            if (
                                not edit_source_uri
                                and request_dto.parent_media_item_id
                            ):
                                parent_media_item = await media_repo.get_by_id(
                                    request_dto.parent_media_item_id
                                )
                                entry = extract_omni_interaction_entry(
                                    (
                                        parent_media_item.raw_data
                                        if parent_media_item
                                        else None
                                    ),
                                    request_dto.parent_media_index,
                                )
                                previous_steps = (entry or {}).get(
                                    "steps"
                                ) or None

                                if not previous_steps and parent_media_item:
                                    uris = parent_media_item.gcs_uris or []
                                    index = request_dto.parent_media_index
                                    if not 0 <= index < len(uris):
                                        index = 0
                                    if uris:
                                        edit_source_uri = uris[index]
                                        edit_source_mime = (
                                            parent_media_item.mime_type
                                        )

                                if not previous_steps and not edit_source_uri:
                                    worker_logger.warning(
                                        "Parent MediaItem %s has neither stored "
                                        "steps nor a video at index %s; falling "
                                        "back to a fresh generation.",
                                        request_dto.parent_media_item_id,
                                        request_dto.parent_media_index,
                                    )

                            is_followup = bool(previous_steps)
                            is_edit = is_followup or bool(edit_source_uri)

                            omni_task = resolve_omni_task(
                                is_edit=is_edit,
                                has_references=bool(
                                    reference_images_for_api or ref_video_uri
                                ),
                                has_start_image=bool(start_image_for_api),
                            )

                            if is_followup:
                                worker_logger.info(
                                    "Continuing Gemini Omni conversation from "
                                    "%s replayed steps.",
                                    len(previous_steps),
                                )
                                omni_inputs = build_omni_followup_input(
                                    previous_steps,
                                    request_dto.prompt,
                                )
                            elif edit_source_uri:
                                worker_logger.info(
                                    "Editing %s statelessly (task=%s).",
                                    edit_source_uri,
                                    omni_task,
                                )
                                omni_inputs = [
                                    {
                                        "type": "video",
                                        "mime_type": edit_source_mime
                                        or MimeTypeEnum.VIDEO_MP4.value,
                                        "uri": edit_source_uri,
                                    },
                                    {
                                        "type": "text",
                                        "text": request_dto.prompt,
                                    },
                                ]
                            else:
                                worker_logger.info(
                                    "Starting Gemini Omni generation (task=%s)",
                                    omni_task,
                                )
                                # The task value is what distinguishes a start
                                # frame from a reference; the DTO already forbids
                                # combining the two, so ordering is unambiguous.
                                # The prompt is passed through verbatim. Users
                                # can bind specific images to roles with
                                # <FIRST_FRAME> and <IMAGE_REF_N> tags, which
                                # are honoured on Vertex (verified: tagged
                                # prompts produced the requested cross-pairing
                                # while an untagged control paired adjacently).
                                # Rewriting the prompt here would break them.
                                omni_inputs = [
                                    {
                                        "type": "text",
                                        "text": request_dto.prompt,
                                    }
                                ]

                                if start_image_for_api:
                                    omni_inputs.append(
                                        {
                                            "type": "image",
                                            "mime_type": start_image_for_api.mime_type,
                                            "uri": start_image_for_api.gcs_uri,
                                        }
                                    )

                                for ref_img in reference_images_for_api:
                                    omni_inputs.append(
                                        {
                                            "type": "image",
                                            "mime_type": ref_img.image.mime_type,
                                            "uri": ref_img.image.gcs_uri,
                                        }
                                    )

                                if ref_video_uri:
                                    omni_inputs.append(
                                        {
                                            "type": "video",
                                            "mime_type": ref_video_mime_type
                                            or MimeTypeEnum.VIDEO_MP4.value,
                                            "uri": ref_video_uri,
                                        }
                                    )

                            # An edit inherits both dimensions and length from
                            # the clip it modifies; the API rejects either.
                            omni_response_format = build_omni_response_format(
                                aspect_ratio=(
                                    None
                                    if is_edit
                                    else request_dto.aspect_ratio.value
                                ),
                                duration_seconds=(
                                    None
                                    if is_edit
                                    else request_dto.duration_seconds
                                ),
                                gcs_output_directory=gcs_output_directory,
                            )

                            final_gcs_uris = []
                            permanent_thumbnail_gcs_uris = []
                            interaction_details = []

                            num_outputs = max(1, request_dto.number_of_media)
                            worker_logger.info(
                                f"Queueing {num_outputs} Gemini Omni generation interactions."
                            )

                            async def generate_single_omni_output(i: int):
                                max_retries = 3
                                last_err = None
                                interaction = None
                                for attempt in range(max_retries):
                                    try:
                                        create_kwargs = {
                                            "model": model_name_for_api,
                                            "input": omni_inputs,
                                            "response_format": omni_response_format,
                                            # A hung call would otherwise pin a
                                            # worker thread indefinitely.
                                            "timeout": OMNI_REQUEST_TIMEOUT_SECONDS,
                                        }
                                        if not is_followup:
                                            # A replayed conversation omits the
                                            # task, matching Google's Vertex
                                            # sample: the steps already carry
                                            # the intent. A stateless edit does
                                            # send task=edit.
                                            create_kwargs[
                                                "generation_config"
                                            ] = {
                                                "video_config": {
                                                    "task": omni_task,
                                                },
                                            }

                                        interaction = await asyncio.to_thread(
                                            vertex_client.interactions.create,
                                            **create_kwargs,
                                        )
                                        break
                                    except Exception as e:
                                        last_err = e
                                        if not is_retryable_omni_error(e):
                                            worker_logger.error(
                                                "Gemini Omni interactions call failed with a "
                                                "non-retryable error: %s",
                                                e,
                                            )
                                            raise
                                        worker_logger.warning(
                                            f"Gemini Omni interactions API call attempt {attempt + 1} failed: {e}. Retrying..."
                                        )
                                        if attempt < max_retries - 1:
                                            await asyncio.sleep(2)

                                if interaction is None:
                                    raise last_err or Exception(
                                        "Failed to generate video after multiple attempts."
                                    )

                                interaction_id = interaction.id

                                # The SDK surfaces the first video content from
                                # the model_output step here. Fall back to a
                                # typed scan rather than assuming position:
                                # model_output can also carry text.
                                video_content = getattr(
                                    interaction, "output_video", None
                                )
                                if video_content is None:
                                    for step in interaction.steps or []:
                                        if (
                                            getattr(step, "type", None)
                                            != "model_output"
                                        ):
                                            continue
                                        for content in (
                                            getattr(step, "content", None) or []
                                        ):
                                            if (
                                                getattr(content, "type", None)
                                                == "video"
                                            ):
                                                video_content = content
                                                break
                                        if video_content is not None:
                                            break

                                if video_content is None:
                                    raise Exception(
                                        f"Interactions call {i + 1} succeeded but returned no video output."
                                    )

                                output_filename = (
                                    f"videos/{media_item_id}_{i}.mp4"
                                )
                                local_output_path = (
                                    f"thumbnails/{output_filename}"
                                )
                                os.makedirs(
                                    os.path.dirname(local_output_path),
                                    exist_ok=True,
                                )

                                content_uri = getattr(
                                    video_content, "uri", None
                                )
                                content_data = getattr(
                                    video_content, "data", None
                                )

                                if content_uri:
                                    # URI delivery: the model already wrote the
                                    # file to the bucket. Download only to build
                                    # the thumbnail.
                                    final_gcs_uri = content_uri
                                    await asyncio.to_thread(
                                        gcs_service.download_from_gcs,
                                        gcs_uri_path=gcs_uri_to_blob_path(
                                            content_uri
                                        ),
                                        destination_file_path=local_output_path,
                                    )
                                elif content_data:
                                    # Inline delivery: decode and upload it
                                    # ourselves.
                                    raw_video_bytes = base64.b64decode(
                                        content_data
                                    )
                                    with open(local_output_path, "wb") as f:
                                        f.write(raw_video_bytes)

                                    final_gcs_uri = await asyncio.to_thread(
                                        gcs_service.upload_file_to_gcs,
                                        local_path=local_output_path,
                                        destination_blob_name=output_filename,
                                        mime_type=MimeTypeEnum.VIDEO_MP4.value,
                                    )
                                else:
                                    raise Exception(
                                        f"Interactions call {i + 1} returned a video "
                                        "output with neither data nor uri.",
                                    )

                                # Generate local thumbnail
                                thumbnail_path = None
                                if os.path.exists(local_output_path):
                                    thumbnail_path = await asyncio.to_thread(
                                        generate_thumbnail,
                                        local_output_path,
                                    )
                                else:
                                    worker_logger.warning(
                                        "No local copy of %s available; skipping thumbnail.",
                                        final_gcs_uri,
                                    )
                                local_thumbnail_name = thumbnail_path or ""

                                # Upload thumbnail to GCS
                                thumbnail_gcs_blob = (
                                    f"thumbnails/{media_item_id}_{i}.png"
                                )
                                thumbnail_gcs_uri = ""
                                if thumbnail_path:
                                    thumbnail_gcs_uri = (
                                        await asyncio.to_thread(
                                            gcs_service.upload_file_to_gcs,
                                            local_path=thumbnail_path,
                                            destination_blob_name=thumbnail_gcs_blob,
                                            mime_type="image/png",
                                        )
                                        or ""
                                    )

                                # Clean up local temp files
                                for local_path in [
                                    local_output_path,
                                    local_thumbnail_name,
                                ]:
                                    if os.path.exists(local_path):
                                        try:
                                            os.remove(local_path)
                                        except Exception as e:
                                            worker_logger.warning(
                                                f"Failed to clean up {local_path}: {e}"
                                            )

                                return (
                                    final_gcs_uri,
                                    thumbnail_gcs_uri,
                                    interaction_id,
                                    serialize_omni_steps(interaction.steps),
                                )

                            tasks = [
                                generate_single_omni_output(i)
                                for i in range(num_outputs)
                            ]
                            parallel_results = await asyncio.gather(*tasks)

                            for (
                                final_gcs_uri,
                                thumbnail_gcs_uri,
                                interaction_id,
                                interaction_steps,
                            ) in parallel_results:
                                final_gcs_uris.append(final_gcs_uri)
                                permanent_thumbnail_gcs_uris.append(
                                    thumbnail_gcs_uri
                                )
                                # One record per clip, kept in output order so a
                                # later edit can continue the right conversation.
                                # The steps are what make that possible, since
                                # Vertex holds no state for us.
                                interaction_details.append(
                                    {
                                        "interaction_id": interaction_id,
                                        "steps": interaction_steps,
                                    },
                                )

                            raw_data_dict = {
                                "interactions": interaction_details
                            }

                        else:
                            # Map DTO resolution ("1K", "2K", "4K") to GenAI SDK supported resolutions ("720p", "1080p", "4k")
                            api_resolution = VIDEO_RESOLUTION_MAP.get(
                                request_dto.resolution, "720p"
                            )

                            # Run sync API call in thread
                            operation: types.GenerateVideosOperation = (
                                await asyncio.to_thread(
                                    client.models.generate_videos,
                                    model=request_dto.generation_model,
                                    prompt=request_dto.prompt,
                                    image=start_image_for_api,
                                    video=source_video_for_api,
                                    config=types.GenerateVideosConfig(
                                        number_of_videos=request_dto.number_of_media,
                                        output_gcs_uri=gcs_output_directory,
                                        aspect_ratio=request_dto.aspect_ratio,
                                        resolution=api_resolution,
                                        negative_prompt=request_dto.negative_prompt,
                                        generate_audio=request_dto.generate_audio,
                                        # TODO: Pass from dto the secs if extending video (4, 5, 6, 7)
                                        duration_seconds=(
                                            request_dto.duration_seconds
                                            if not source_video_for_api
                                            else 7
                                        ),
                                        last_frame=end_image_for_api,
                                        reference_images=(
                                            reference_images_for_api
                                            if reference_images_for_api
                                            else None
                                        ),
                                    ),
                                )
                            )

                            # Poll the operation status until the video is ready
                            while not operation.done:
                                worker_logger.info(
                                    "Waiting for video generation to complete, polling video generation status...",
                                    extra={
                                        "json_fields": {
                                            "media_id": media_item_id,
                                            "operation_name": operation.name,
                                        },
                                    },
                                )
                                await asyncio.sleep(10)
                                operation = await asyncio.to_thread(
                                    client.operations.get,
                                    operation,
                                )

                            if operation.error:
                                raise Exception(operation.error)

                            if (
                                not operation
                                or not operation.response
                                or not operation.response.generated_videos
                            ):
                                return

                            # Download the generated video and create thumbnail
                            thumbnail_path = ""

                            for (
                                generated_video
                            ) in operation.response.generated_videos:
                                if (
                                    generated_video.video
                                    and generated_video.video.uri
                                ):
                                    output_path = f"{generated_video.video.uri.replace(f'gs://{cfg.GENMEDIA_BUCKET}/', '')}"

                                    # Step 1: Download the Video from GCS
                                    local_output_path = (
                                        f"thumbnails/{output_path}"
                                    )
                                    downloaded_video_path = await asyncio.to_thread(
                                        gcs_service.download_from_gcs,
                                        gcs_uri_path=output_path,
                                        destination_file_path=local_output_path,
                                    )

                                    # Step 2: Generate Thumbnail from the first video frame
                                    thumbnail_path = await asyncio.to_thread(
                                        generate_thumbnail,
                                        downloaded_video_path or "",
                                    )

                                    # Step 3: Save the Thumbnail in GCS
                                    if thumbnail_path:
                                        # Get the parent directory of the thumbnail to clean it up later.
                                        temp_dir = os.path.dirname(
                                            thumbnail_path
                                        )
                                        try:
                                            thumbnail_gcs_uri = (
                                                await asyncio.to_thread(
                                                    gcs_service.upload_file_to_gcs,
                                                    local_path=thumbnail_path,
                                                    destination_blob_name=thumbnail_path.replace(
                                                        "thumbnails/",
                                                        "",
                                                    ),
                                                    mime_type="image/png",
                                                )
                                                or ""
                                            )

                                            permanent_thumbnail_gcs_uris.append(
                                                thumbnail_gcs_uri,
                                            )
                                        except Exception as e:
                                            print(
                                                f"Failed to upload {thumbnail_path}. Error: {e}",
                                            )
                                        finally:
                                            if os.path.exists(temp_dir):
                                                shutil.rmtree(temp_dir)

                            all_generated_videos.extend(
                                operation.response.generated_videos or [],
                            )

                            valid_generated_videos = [
                                img
                                for img in all_generated_videos
                                if img.video and img.video.uri
                            ]
                            final_gcs_uris = [
                                img.video.uri
                                for img in valid_generated_videos
                                if img.video and img.video.uri
                            ]

                        end_time = time.monotonic()
                        generation_time = end_time - start_time

                        # --- WHEN COMPLETE, UPDATE THE DOCUMENT IN FIRESTORE ---
                        update_data = {
                            "status": JobStatusEnum.COMPLETED,
                            "prompt": rewritten_prompt,
                            "gcs_uris": final_gcs_uris,  # The final GCS URLs
                            "thumbnail_uris": permanent_thumbnail_gcs_uris,
                            "generation_time": generation_time,
                            "num_media": len(final_gcs_uris),
                        }
                        if raw_data_dict is not None:
                            update_data["raw_data"] = raw_data_dict

                        await media_repo.update(media_item_id, update_data)
                        worker_logger.info(
                            "Successfully processed video job.",
                            extra={
                                "json_fields": {
                                    "media_id": media_item_id,
                                    "generation_time_seconds": generation_time,
                                    "videos_generated": len(final_gcs_uris),
                                },
                            },
                        )

                    except Exception as e:
                        worker_logger.error(
                            "Video generation task failed.",
                            extra={
                                "json_fields": {
                                    "media_id": media_item_id,
                                    "error": str(e),
                                },
                            },
                            exc_info=True,
                        )  # exc_info=True still adds the full traceback
                        # --- ON FAILURE, UPDATE THE DOCUMENT WITH AN ERROR STATUS ---
                        error_update_data = {
                            "status": JobStatusEnum.FAILED,
                            "error_message": str(e),
                        }
                        await media_repo.update(
                            media_item_id, error_update_data
                        )

        loop.run_until_complete(_async_worker())
        loop.close()

    except Exception as e:
        worker_logger.error(
            "Video generation task failed.",
            extra={"json_fields": {"media_id": media_item_id, "error": str(e)}},
            exc_info=True,
        )  # exc_info=True still adds the full traceback


def _process_video_concatenation_in_background(
    media_item_id: int,
    request_dto: ConcatenateVideosDto,
):
    """Background worker to concatenate multiple videos."""
    from src.database import WorkerDatabase

    worker_logger = logging.getLogger(f"video_concat_worker.{media_item_id}")
    worker_logger.setLevel(logging.INFO)
    temp_dir = f"temp/{media_item_id}"

    try:
        if worker_logger.hasHandlers():
            worker_logger.handlers.clear()

        if os.getenv("ENVIRONMENT") == "production":
            log_client = LoggerClient()
            handler = CloudLoggingHandler(
                log_client,
                name=f"video_concat_worker.{media_item_id}",
            )
            worker_logger.addHandler(handler)
        else:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - [CONCAT_WORKER] - %(levelname)s - %(message)s",
            )
            handler.setFormatter(formatter)
            worker_logger.addHandler(handler)

        # Create a new event loop for this process
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _async_worker():
            async with WorkerDatabase() as db_factory:
                async with db_factory() as db:
                    media_repo = MediaRepository(db)
                    gcs_service = GcsService()
                    source_asset_repo = SourceAssetRepository(db)
                    cfg = config_service

                    try:
                        start_time = time.monotonic()
                        local_video_paths = []

                        # 1. Download all source videos
                        for video_input in request_dto.inputs:
                            gcs_uri: str | None = None
                            if video_input.type == "media_item":
                                item = await media_repo.get_by_id(
                                    video_input.id
                                )
                                if not item or not item.gcs_uris:
                                    raise ValueError(
                                        f"MediaItem '{video_input.id}' not found or has no video.",
                                    )
                                gcs_uri = item.gcs_uris[0]
                            elif video_input.type == "source_asset":
                                asset = await source_asset_repo.get_by_id(
                                    video_input.id,
                                )
                                if not asset or not asset.gcs_uri:
                                    raise ValueError(
                                        f"SourceAsset '{video_input.id}' not found or has no video.",
                                    )
                                gcs_uri = asset.gcs_uri

                            # Basic validation that it's a video URI
                            if not gcs_uri or not gcs_uri.endswith(
                                (".mp4", ".mov", ".webm"),
                            ):
                                worker_logger.warning(
                                    f"Skipping non-video URI for {video_input.type} '{video_input.id}'",
                                )
                                continue

                            local_path = await asyncio.to_thread(
                                gcs_service.download_from_gcs,
                                gcs_uri_path=gcs_uri.replace(
                                    f"gs://{cfg.GENMEDIA_BUCKET}/",
                                    "",
                                ),
                                destination_file_path=f"{temp_dir}/{video_input.id}.mp4",
                            )
                            if not local_path:
                                raise Exception(
                                    f"Failed to download video: {gcs_uri}"
                                )
                            local_video_paths.append(local_path)

                        # 2. Concatenate them
                        final_video_path = f"{temp_dir}/final_concatenated.mp4"
                        concatenated_path = await asyncio.to_thread(
                            concatenate_videos,
                            video_paths=local_video_paths,
                            output_path=final_video_path,
                        )
                        if not concatenated_path:
                            raise Exception("ffmpeg concatenation failed.")

                        # 3. Upload the final video
                        final_gcs_uri = await asyncio.to_thread(
                            gcs_service.upload_file_to_gcs,
                            local_path=concatenated_path,
                            destination_blob_name=f"concatenated_videos/{media_item_id}.mp4",
                            mime_type="video/mp4",
                        )
                        if not final_gcs_uri:
                            raise Exception(
                                "Failed to upload final concatenated video.",
                            )

                        # 4. Generate and upload thumbnail
                        thumbnail_path = await asyncio.to_thread(
                            generate_thumbnail,
                            concatenated_path,
                        )
                        thumbnail_gcs_uri = None
                        if thumbnail_path:
                            thumbnail_gcs_uri = await asyncio.to_thread(
                                gcs_service.upload_file_to_gcs,
                                local_path=thumbnail_path,
                                destination_blob_name=f"concatenated_videos/{media_item_id}_thumb.png",
                                mime_type="image/png",
                            )

                        end_time = time.monotonic()

                        # 5. Update the placeholder MediaItem
                        update_data = {
                            "status": JobStatusEnum.COMPLETED,
                            "gcs_uris": [final_gcs_uri],
                            "thumbnail_uris": (
                                [thumbnail_gcs_uri] if thumbnail_gcs_uri else []
                            ),
                            "generation_time": end_time - start_time,
                            "num_media": 1,
                        }
                        await media_repo.update(media_item_id, update_data)
                        worker_logger.info(
                            f"Successfully concatenated videos for job {media_item_id}",
                        )

                    except Exception as e:
                        worker_logger.error(
                            f"Video concatenation task failed: {e}",
                            exc_info=True,
                        )
                        error_update_data = {
                            "status": JobStatusEnum.FAILED,
                            "error_message": str(e),
                        }
                        await media_repo.update(
                            media_item_id, error_update_data
                        )
                    finally:
                        if os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir)

        loop.run_until_complete(_async_worker())
        loop.close()

    except Exception as e:
        worker_logger.error(
            f"Video concatenation worker failed to initialize: {e}",
            exc_info=True,
        )


class VeoService:
    def __init__(
        self,
        media_repo: MediaRepository = Depends(),
        source_asset_repo: SourceAssetRepository = Depends(),
        gemini_service: GeminiService = Depends(),
        gcs_service: GcsService = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
    ):
        """Initializes the service with its dependencies."""
        self.iam_signer_credentials = iam_signer_credentials
        self.media_repo = media_repo
        self.gemini_service = gemini_service
        self.gcs_service = gcs_service
        self.source_asset_repo = source_asset_repo

    async def start_video_generation_job(
        self,
        request_dto: CreateVeoDto,
        user: UserModel,
        executor: ThreadPoolExecutor,
    ) -> MediaItemResponse:
        """Immediately creates a placeholder MediaItem and starts the video generation
        in the background.

        Returns:
            The initial MediaItem with a 'processing' status and a pre-generated ID.

        """
        # 1. Prepare source asset links if they exist
        source_assets: list[SourceAssetLink] = []
        source_media_items: list[SourceMediaItemLink] = []

        if request_dto.start_image_asset_id:
            ref = request_dto.start_image_asset_id
            if ref.type == "media_item":
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=ref.id,
                        media_index=0,
                        role=AssetRoleEnum.START_FRAME,
                    )
                )
            else:
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref.id,
                        role=AssetRoleEnum.START_FRAME,
                    )
                )

        if request_dto.end_image_asset_id:
            ref = request_dto.end_image_asset_id
            if ref.type == "media_item":
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=ref.id,
                        media_index=0,
                        role=AssetRoleEnum.END_FRAME,
                    )
                )
            else:
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref.id,
                        role=AssetRoleEnum.END_FRAME,
                    )
                )

        if request_dto.source_video_asset_id:
            ref = request_dto.source_video_asset_id
            if ref.type == "media_item":
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=ref.id,
                        media_index=0,
                        role=AssetRoleEnum.VIDEO_EXTENSION_SOURCE,
                    )
                )
            else:
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref.id,
                        role=AssetRoleEnum.VIDEO_EXTENSION_SOURCE,
                    )
                )

        if request_dto.reference_images:
            for ref_image in request_dto.reference_images:
                role = (
                    AssetRoleEnum.IMAGE_REFERENCE_STYLE
                    if ref_image.reference_type == ReferenceImageTypeEnum.STYLE
                    else AssetRoleEnum.IMAGE_REFERENCE_ASSET
                )
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref_image.asset_id,
                        role=role,
                    ),
                )

        if request_dto.reference_video:
            ref = request_dto.reference_video
            if ref.type == "media_item":
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=ref.id,
                        media_index=ref.index or 0,
                        role=AssetRoleEnum.VIDEO_REFERENCE,
                    )
                )
            else:
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref.id,
                        role=AssetRoleEnum.VIDEO_REFERENCE,
                    )
                )

        if request_dto.reference_audio:
            ref = request_dto.reference_audio
            if ref.type == "media_item":
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=ref.id,
                        media_index=ref.index or 0,
                        role=AssetRoleEnum.AUDIO_REFERENCE,
                    )
                )
            else:
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref.id,
                        role=AssetRoleEnum.AUDIO_REFERENCE,
                    )
                )

        if request_dto.edit_source:
            ref = request_dto.edit_source
            if ref.type == "media_item":
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=ref.id,
                        media_index=ref.index or 0,
                        role=AssetRoleEnum.EDIT_SOURCE,
                    )
                )
            else:
                source_assets.append(
                    SourceAssetLink(
                        asset_id=ref.id,
                        role=AssetRoleEnum.EDIT_SOURCE,
                    )
                )

        # 1. Create a placeholder MediaItem (without ID, let DB generate it)
        placeholder_item = MediaItemModel(
            workspace_id=request_dto.workspace_id,
            user_email=user.email,
            user_id=user.id,
            mime_type=MimeTypeEnum.VIDEO_MP4,
            model=request_dto.generation_model,
            original_prompt=request_dto.prompt,
            status=JobStatusEnum.PROCESSING,
            # Populate other known request parameters
            aspect_ratio=request_dto.aspect_ratio,
            style=request_dto.style,
            lighting=request_dto.lighting,
            color_and_tone=request_dto.color_and_tone,
            composition=request_dto.composition,
            negative_prompt=request_dto.negative_prompt,
            duration_seconds=request_dto.duration_seconds,
            source_media_items=(request_dto.source_media_items or [])
            + source_media_items
            or None,
            source_assets=source_assets or None,
            gcs_uris=[],
            thumbnail_uris=[],
        )

        # 2. Save to DB to get the ID
        placeholder_item = await self.media_repo.create(placeholder_item)

        # 3. Submit background task
        executor.submit(
            _process_video_in_background,
            media_item_id=placeholder_item.id,
            request_dto=request_dto,
            user_email=user.email,
        )

        logger.info(
            "Video generation job successfully queued.",
            extra={
                "json_fields": {
                    "message": "Video generation job successfully queued.",
                    "media_id": placeholder_item.id,
                    "user_email": user.email,
                    "user_id": user.id,
                    "model": request_dto.generation_model,
                },
            },
        )

        # 5. Return the placeholder to the frontend
        return MediaItemResponse(
            **placeholder_item.model_dump(),
            presigned_urls=[],
            presigned_thumbnail_urls=[],
        )

    async def start_video_concatenation_job(
        self,
        request_dto: ConcatenateVideosDto,
        user: UserModel,
        executor: ThreadPoolExecutor,
    ) -> MediaItemResponse:
        """Creates a placeholder for a video concatenation job and starts it in the background."""
        source_media_items: list[SourceMediaItemLink] = []
        source_assets: list[SourceAssetLink] = []

        for video_input in request_dto.inputs:
            if video_input.type == "media_item":
                item = await self.media_repo.get_by_id(video_input.id)
                if not item or item.mime_type != MimeTypeEnum.VIDEO_MP4:
                    raise HTTPException(
                        status_code=400,
                        detail=f"MediaItem '{video_input.id}' not found or is not a video.",
                    )
                source_media_items.append(
                    SourceMediaItemLink(
                        media_item_id=video_input.id,
                        media_index=0,
                        role=AssetRoleEnum.CONCATENATION_SOURCE,
                    ),
                )
            elif video_input.type == "source_asset":
                asset = await self.source_asset_repo.get_by_id(video_input.id)
                if not asset or asset.mime_type != MimeTypeEnum.VIDEO_MP4:
                    raise HTTPException(
                        status_code=400,
                        detail=f"SourceAsset '{video_input.id}' not found or is not a video.",
                    )
                source_assets.append(
                    SourceAssetLink(
                        asset_id=video_input.id,
                        role=AssetRoleEnum.CONCATENATION_SOURCE,
                    ),
                )

        # 1. Create placeholder (let DB generate ID)
        placeholder_item = MediaItemModel(
            workspace_id=request_dto.workspace_id,
            user_email=user.email,
            user_id=user.id,
            mime_type=MimeTypeEnum.VIDEO_MP4,
            model=GenerationModelEnum.VEO_3_QUALITY,  # Or a specific concat model if exists
            original_prompt=request_dto.name,  # Use name as prompt
            status=JobStatusEnum.PROCESSING,
            source_media_items=source_media_items,
            source_assets=source_assets,
            gcs_uris=[],
            thumbnail_uris=[],
            aspect_ratio=request_dto.aspect_ratio,
            # We could store the input IDs in source_assets or raw_data for traceability
            raw_data={
                "concatenation_inputs": [
                    i.model_dump() for i in request_dto.inputs
                ],
            },
        )

        # 2. Save to DB
        placeholder_item = await self.media_repo.create(placeholder_item)

        # 3. Submit background task
        executor.submit(
            _process_video_concatenation_in_background,
            media_item_id=placeholder_item.id,
            request_dto=request_dto,
        )

        logger.info("Video concatenation job queued: %s", placeholder_item.id)

        return MediaItemResponse(
            **placeholder_item.model_dump(),
            presigned_urls=[],
            presigned_thumbnail_urls=[],
        )
