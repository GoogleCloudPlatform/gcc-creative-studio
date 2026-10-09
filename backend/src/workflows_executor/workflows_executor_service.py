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

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable, Iterable
from enum import Enum
from typing import Any

import httpx
from fastapi import HTTPException
from google.genai import types
from httpx import AsyncClient as RestClient

from src.common.base_dto import GenerationModelEnum
from src.common.retry import call_with_l1_retry, l1_async_retrying
from src.common.schema.genai_model_setup import GenAIModelSetup
from src.common.schema.media_item_model import AssetRoleEnum
from src.common.secret_redaction import install_secret_redaction
from src.config.config_service import config_service
from src.folders.repository.folder_repository import FolderRepository
from src.galleries.repository.unified_gallery_repository import (
    LOOP_MEDIA_ITEM,
    LOOP_SOURCE_ASSET,
    UnifiedGalleryRepository,
)
from src.users.user_model import UserModel
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.schema.workflow_model import (
    ReferenceMediaOrAsset,
)
from src.workflows.workflow_constants import (
    IMAGE_MODE_ALLOWED_INPUTS,
    ImageModeEnum,
)
from src.workflows.workflow_utils import interpolate_prompt_variables
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateAudioRequest,
    GenerateTextRequest,
    GenerateVideoRequest,
    ImageStepRequest,
    ResolveLoopItemsRequest,
)
from src.workflows_executor.idempotency import StepIdempotencyGuard
from src.workflows_executor.step_errors import (
    StepError,
    backend_error,
    invalid_input_error,
    job_failed_error,
    step_in_progress_error,
    to_step_error,
)
from src.workspaces.workspace_auth_guard import WorkspaceAuth

logging.basicConfig(level=logging.INFO)
# Defense in depth: redact bearer tokens even if a log line includes one.
logger = install_secret_redaction(logging.getLogger(__name__))

# Maximum number of iterations of a Loop step: larger folders / texts are
# truncated to their first MAX_LOOP_ITEMS items (with a warning log).
MAX_LOOP_ITEMS = 100
# Same message for missing, deleted and foreign folders (no enumeration).
FOLDER_NOT_FOUND_DETAIL = "Folder not found or deleted"
# A Loop step that resolves zero items fails, with one message per source.
LOOP_EMPTY_DETAILS: dict[str, str] = {
    "text_input": (
        "Loop resolved 0 items from the text input; at least 1 is required."
    ),
    "folder": (
        "Loop resolved 0 items from the Media Gallery folder; at least 1 is "
        "required."
    ),
    "linked_items": (
        "Loop resolved 0 items from the linked items; at least 1 is required."
    ),
}
LINKED_ITEMS_REQUIRED_DETAIL = "Add at least one item in Linked Items mode."
LINKED_ITEMS_UNSUPPORTED_DETAIL = "Linked Items received an unsupported value."
# Same message for missing, deleted, foreign and wrong-type linked items, and
# for a workspace the user cannot access (no enumeration, no ids).
LINKED_ITEMS_NOT_ACCESSIBLE_DETAIL = (
    "Some linked items are missing, deleted, not accessible or not of type "
    "{item_type}."
)
# Maximum list nesting of the raw linked values, the request list included.
MAX_LINKED_NESTING_DEPTH = 3

# One flattened linked item: ``(gallery item type, id, media index)``.
LinkedItem = tuple[str, int, int]


def _loop_item(item_type: str, item_id: int) -> int | dict[str, Any]:
    """Media input of one folder or linked ``Loop`` iteration.

    A single value, like the outputs of the media steps, so it can feed a
    single-media input directly or be one entry of a multi-media input
    list: a generated media item is its id (``42``); an uploaded source
    asset is a ``ReferenceMediaOrAsset``
    (``{"sourceAssetId": 7, "previewUrl": ""}``).
    """
    if item_type == LOOP_SOURCE_ASSET:
        return {"sourceAssetId": item_id, "previewUrl": ""}
    return item_id


def _require_items(mode: str, count: int) -> None:
    """Fails a ``Loop`` step whose source resolved zero items."""
    if count <= 0:
        raise StepError(
            422, ErrorCategory.INVALID_INPUT, LOOP_EMPTY_DETAILS[mode]
        )


def _unsupported_linked_value() -> StepError:
    return StepError(
        422, ErrorCategory.INVALID_INPUT, LINKED_ITEMS_UNSUPPORTED_DETAIL
    )


def _is_empty_linked_value(value: Any) -> bool:
    """Whether a linked value carries no item (skipped upstream output)."""
    return value is None or (
        isinstance(value, (str, dict, list)) and len(value) == 0
    )


def _linked_id(value: Any) -> int | None:
    """Positive id from an ``int`` or a digit string; ``None`` otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, int) and value > 0:
        return value
    return None


def _linked_loop_item(value: Any) -> LinkedItem:
    """Parses one non-empty, non-list linked value.

    Accepts a media item id (``int`` or digit string), a
    ``ReferenceMediaOrAsset``-like dict with ``sourceMediaItem`` (its
    ``mediaIndex`` is kept) or with ``sourceAssetId``. Any ``previewUrl``
    is ignored.

    Raises:
        StepError: 422 ``INVALID_INPUT`` for any other value.
    """
    media_item_id = _linked_id(value)
    if media_item_id is not None:
        return (LOOP_MEDIA_ITEM, media_item_id, 0)
    if isinstance(value, dict):
        source_media_item = value.get("sourceMediaItem")
        if isinstance(source_media_item, dict):
            media_item_id = _linked_id(source_media_item.get("mediaItemId"))
            media_index = source_media_item.get("mediaIndex", 0)
            if (
                media_item_id is not None
                and isinstance(media_index, int)
                and not isinstance(media_index, bool)
                and media_index >= 0
            ):
                return (LOOP_MEDIA_ITEM, media_item_id, media_index)
        elif source_media_item is None:
            source_asset_id = _linked_id(value.get("sourceAssetId"))
            if source_asset_id is not None:
                return (LOOP_SOURCE_ASSET, source_asset_id, 0)
    raise _unsupported_linked_value()


def _flatten_linked_values(values: list[Any]) -> tuple[list[LinkedItem], int]:
    """Flattens the raw linked values, keeping their order.

    Nested lists are flattened recursively up to
    :data:`MAX_LINKED_NESTING_DEPTH` list levels (the request list
    included). ``None``, ``""``, ``{}`` and ``[]`` are skipped.

    Returns:
        ``(items, skipped_count)``.

    Raises:
        StepError: 422 ``INVALID_INPUT`` for an unsupported or too deeply
            nested value.
    """
    items: list[LinkedItem] = []
    skipped_count = 0

    def visit(value: Any, depth: int) -> None:
        nonlocal skipped_count
        if _is_empty_linked_value(value):
            skipped_count += 1
        elif isinstance(value, list):
            if depth >= MAX_LINKED_NESTING_DEPTH:
                raise _unsupported_linked_value()
            for entry in value:
                visit(entry, depth + 1)
        else:
            items.append(_linked_loop_item(value))

    for raw_value in values:
        visit(raw_value, 1)
    return items, skipped_count


def _linked_loop_value(item: LinkedItem) -> int | dict[str, Any]:
    """Iteration value of a linked item, in the existing loop item shapes.

    A media item with a non-zero ``mediaIndex`` stays a
    ``ReferenceMediaOrAsset`` so the index is not lost.
    """
    item_type, item_id, media_index = item
    if media_index > 0:
        return {
            "sourceMediaItem": {
                "mediaItemId": item_id,
                "mediaIndex": media_index,
                "role": AssetRoleEnum.INPUT.value,
            },
            "previewUrl": "",
        }
    return _loop_item(item_type, item_id)


# Below the 300 s Cloud Run request / YAML step timeout.
REST_CLIENT_TIMEOUT_SECONDS = 280.0
POLL_INITIAL_DELAY_SECONDS = 2
POLL_INTERVAL_SECONDS = 5
# Poll answers that only mean "cannot check right now": keep polling.
_TRANSIENT_POLL_STATUSES = frozenset({429, 502, 503, 504})
# Gemini finish reasons meaning the output was blocked by safety filters.
_SAFETY_FINISH_REASONS = frozenset(
    {
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
    },
)

StepOutputs = dict[str, Any]

# L1 retries of a create-job POST end within this budget, far below the
# 300 s step timeout (a slow connect timeout is never retried).
CREATE_JOB_L1_MAX_SECONDS = 30
# Create-job answers sent by the serving layer (Cloud Run / load balancer)
# without the app processing the request: the gen endpoints never answer
# 429 / 503 themselves (unhandled errors become 500).
_UNPROCESSED_STATUSES = frozenset({429, 503})
# Errors raised before the request reached the backend.
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class _UnprocessedAnswer(Exception):
    """A create-job answer meaning the request was never processed."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


def never_processed(error: BaseException) -> bool:
    """Whether a create-job request failed without reaching the backend app.

    Only those failures are retried in-process (L1): the request cannot
    have created a generation job. Read timeouts, dropped connections and
    500 / 502 / 504 answers may follow a created job and are left to the
    idempotency guard / L2.
    """
    return isinstance(error, (_UnprocessedAnswer, *_NOT_SENT_ERRORS))


def _may_have_created_job(status_code: int) -> bool:
    """Whether a non-200 create-job answer may follow a created job."""
    return status_code >= 500 and status_code not in _UNPROCESSED_STATUSES


def _job_id_of(response: httpx.Response) -> Any:
    """``id`` of a create-job answer; ``None`` if the body has none."""
    try:
        data = response.json()
    except ValueError:
        return None
    return data.get("id") if isinstance(data, dict) else None


def _enum_text(value: Any) -> str | None:
    """Upper-case value of a genai enum or string; ``None`` otherwise."""
    if isinstance(value, Enum):
        value = value.value
    return value.upper() if isinstance(value, str) else None


def _safety_block_reason(chunk: Any) -> str | None:
    """Block / finish reason if a streamed chunk was blocked for safety."""
    feedback = getattr(chunk, "prompt_feedback", None)
    block_reason = _enum_text(getattr(feedback, "block_reason", None))
    if block_reason and block_reason != "BLOCKED_REASON_UNSPECIFIED":
        return block_reason
    candidates = getattr(chunk, "candidates", None)
    if isinstance(candidates, (list, tuple)):
        for candidate in candidates:
            reason = _enum_text(getattr(candidate, "finish_reason", None))
            if reason in _SAFETY_FINISH_REASONS:
                return reason
    return None


class WorkflowsExecutorService:
    def __init__(self):
        self.backend_url = config_service.BACKEND_URL
        self.rest_client = RestClient(timeout=REST_CLIENT_TIMEOUT_SECONDS)
        self.genai_client = GenAIModelSetup.init()

    def _normalize_asset_inputs(
        self,
        inputs,
        default_role: AssetRoleEnum = AssetRoleEnum.INPUT,
    ):
        """Normalizes mixed input types (int, list, ReferenceImage) into
        structured media items and asset IDs.
        """
        media_items = []
        asset_ids = []

        # Wrap single items in a list for uniform processing
        raw_list = (
            inputs
            if isinstance(inputs, list)
            else [inputs] if inputs is not None else []
        )

        # Helper to flatten nested lists
        def flatten(items):
            for x in items:
                if isinstance(x, list):
                    yield from flatten(x)
                else:
                    yield x

        for item in flatten(raw_list):
            if isinstance(item, int):
                media_items.append(
                    {
                        "media_item_id": item,
                        "media_index": 0,
                        "role": default_role.value,
                    },
                )
            elif isinstance(item, ReferenceMediaOrAsset):
                if item.sourceMediaItem:
                    media_items.append(
                        {
                            "media_item_id": item.sourceMediaItem.mediaItemId,
                            "media_index": item.sourceMediaItem.mediaIndex,
                            "role": item.sourceMediaItem.role
                            or default_role.value,
                        },
                    )
                elif item.sourceAssetId:
                    asset_ids.append(item.sourceAssetId)
        return media_items, asset_ids

    @staticmethod
    def _auth_headers(authorization: str | None) -> dict[str, str]:
        return {"Authorization": authorization} if authorization else {}

    async def _run_step(
        self,
        guard: StepIdempotencyGuard | None,
        work: Callable[[], Awaitable[StepOutputs]],
        *,
        job_step: bool = True,
        step_inputs: dict[str, Any] | None = None,
    ) -> StepOutputs:
        """Runs a step through its idempotency guard, if the call has one.

        Completed steps return their stored outputs; failures are recorded
        in ``step_states`` and re-raised as structured ``StepError``.
        ``step_inputs`` (the concrete, JSON-safe inputs of this call) is
        checkpointed alongside the outputs.
        """
        if guard is None:
            return await work()
        cached = await guard.begin(job_step=job_step)
        if cached is not None:
            logger.info(
                "Step %s of run %s already completed; reusing its outputs.",
                guard.state_key,
                guard.run_id,
            )
            return cached
        try:
            outputs = await work()
        except Exception as exc:
            error = to_step_error(exc)
            await guard.record_failure(error)
            if error is exc:
                raise
            raise error from exc
        await guard.complete(outputs, step_inputs=step_inputs)
        return outputs

    async def _submit_job(
        self,
        url: str,
        authorization: str | None,
        *,
        missing_id_detail: str,
        guard: StepIdempotencyGuard | None = None,
        json_body: dict[str, Any] | None = None,
        form_data: dict[str, str] | None = None,
    ) -> int:
        """Creates a gen job on a backend endpoint and polls it to the end.

        With a guard, an in-flight job recorded for the step is reused and
        a new job id is recorded before polling.

        The create request is retried in-process (L1) only when
        it provably never reached the backend app, so it cannot have
        created a job. Without a guard a retried call cannot find the job
        again: once a job may exist, errors say ``retry_safe: false`` and
        the YAML does not retry them.

        Returns:
            The gen job (gallery item) id.
        """
        headers = self._auth_headers(authorization)

        async def post_once() -> httpx.Response:
            if form_data is not None:
                response = await self.rest_client.post(
                    url, data=form_data, headers=headers
                )
            else:
                response = await self.rest_client.post(
                    url, json=json_body, headers=headers
                )
            if response.status_code in _UNPROCESSED_STATUSES:
                raise _UnprocessedAnswer(response)
            return response

        async def create_job() -> int:
            logger.info(
                "Call backend with url: %s, body: %s",
                url,
                json_body if form_data is None else form_data,
            )
            try:
                response = await call_with_l1_retry(
                    post_once,
                    retrying=l1_async_retrying(
                        predicate=never_processed,
                        max_total_seconds=CREATE_JOB_L1_MAX_SECONDS,
                    ),
                )
            except _UnprocessedAnswer as answer:
                response = answer.response
            if response.status_code != 200:
                logger.error(
                    "Backend error %s from %s: %s",
                    response.status_code,
                    url,
                    response.text,
                )
                error = backend_error(response.status_code, response.text)
                # Decided on the original status: backend_error may remap
                # a 500 (job may exist) to another category.
                if guard is None and _may_have_created_job(
                    response.status_code
                ):
                    error.retry_safe = False
                raise error
            job_id = _job_id_of(response)
            if not job_id:
                raise StepError(
                    500,
                    ErrorCategory.INTERNAL,
                    missing_id_detail,
                    retry_safe=guard is not None,
                )
            return job_id

        async def poll_job(job_id: int, single_check: bool = False) -> None:
            if single_check:
                await self._poll_job_status(
                    job_id, authorization, budget_seconds=0
                )
            else:
                await self._poll_job_status(job_id, authorization)

        if guard is not None:
            return await guard.run_job(create_job, poll_job)
        try:
            job_id = await create_job()
        except StepError:
            raise
        except Exception as exc:
            error = to_step_error(exc)
            if not never_processed(exc):
                error.retry_safe = False
            raise error from exc
        try:
            await poll_job(job_id)
        except Exception as exc:
            error = to_step_error(exc)
            # A failed job is over; any other error leaves it running.
            if not error.job_terminal:
                error.retry_safe = False
            if error is exc:
                raise
            raise error from exc
        return job_id

    async def _fetch_job_status(
        self, url: str, headers: dict[str, str], media_id: int
    ) -> dict[str, Any] | None:
        """One status check; ``None`` when the status is unknown for now."""
        try:
            response = await self.rest_client.get(url, headers=headers)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # If we can't check the status we are blind: keep polling
            # until the budget runs out.
            logger.warning(
                "Polling job %s failed (%s); retrying.",
                media_id,
                type(error).__name__,
            )
            return None
        if response.status_code in _TRANSIENT_POLL_STATUSES:
            logger.warning(
                "Polling job %s returned %s; retrying.",
                media_id,
                response.status_code,
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "Polling job %s failed with status %s.",
                media_id,
                response.status_code,
            )
            raise backend_error(
                response.status_code, response.text, "Polling error"
            )
        try:
            data = response.json()
        except ValueError:
            logger.warning("Polling job %s returned invalid JSON.", media_id)
            return None
        return data if isinstance(data, dict) else None

    async def _poll_job_status(
        self,
        media_id: int,
        authorization: str | None = None,
        *,
        budget_seconds: float | None = None,
    ):
        """Polls the gallery endpoint until the job is completed or failed.

        Polls for at most ``budget_seconds`` (default
        ``WORKFLOW_GEN_POLL_TIMEOUT_SECONDS``) so the request ends before
        the 300 s step timeout. A job still running then raises 504
        ``STEP_IN_PROGRESS``: the retried call resumes polling the same job.
        ``budget_seconds=0`` checks the job once, without waiting.
        """
        url = f"{self.backend_url}/api/gallery/item/{media_id}"
        headers = self._auth_headers(authorization)
        budget = (
            config_service.WORKFLOW_GEN_POLL_TIMEOUT_SECONDS
            if budget_seconds is None
            else budget_seconds
        )
        loop = asyncio.get_event_loop()
        start_time = loop.time()
        if budget > POLL_INITIAL_DELAY_SECONDS:
            await asyncio.sleep(POLL_INITIAL_DELAY_SECONDS)

        while True:
            data = await self._fetch_job_status(url, headers, media_id)
            status = data.get("status") if data else None
            if status == "completed":
                return True
            if status == "failed":
                error_message = (
                    data.get("error_message")
                    or data.get("errorMessage")
                    or "Unknown error"
                )
                raise job_failed_error(error_message)
            elapsed = loop.time() - start_time
            if elapsed + POLL_INTERVAL_SECONDS > budget:
                raise step_in_progress_error(
                    f"Generation job {media_id} is still running after "
                    f"{int(elapsed)}s; retry the step to keep polling it.",
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _resolve_media_to_parts(
        self,
        inputs,
        authorization: str | None = None,
    ) -> list[types.Part]:
        """Resolves mixed input types into a list of Gemini types.Part."""
        parts = []
        media_items, asset_ids = self._normalize_asset_inputs(inputs)

        headers = {"Authorization": authorization} if authorization else {}

        # Resolve Media Items
        for item in media_items:
            media_id = item["media_item_id"]
            index = item["media_index"]
            try:
                url = f"{self.backend_url}/api/gallery/item/{media_id}"
                response = await self.rest_client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    gcs_uris = data.get("gcsUris") or data.get("gcs_uris") or []
                    mime_type = (
                        data.get("mimeType")
                        or data.get("mime_type")
                        or "image/png"
                    )
                    if 0 <= index < len(gcs_uris):
                        uri = gcs_uris[index]
                        logger.info(
                            f"Adding part from URI: {uri}, mime_type: {mime_type}",
                        )
                        parts.append(
                            types.Part.from_uri(
                                file_uri=uri, mime_type=mime_type
                            ),
                        )
                    else:
                        logger.warning(
                            f"Index {index} out of range for gcs_uris: {gcs_uris}",
                        )
                else:
                    logger.warning(
                        f"Failed to fetch gallery item {media_id}: {response.text}",
                    )
            except Exception as e:
                logger.error(f"Error resolving media item {media_id}: {e}")

        # Resolve Source Assets
        for asset_id in asset_ids:
            logger.info("Resolving source asset %s", asset_id)
            try:
                url = f"{self.backend_url}/api/source_assets/{asset_id}"
                response = await self.rest_client.get(url, headers=headers)
                logger.info("Source asset status: %s", response.status_code)
                if response.status_code == 200:
                    data = response.json()
                    gcs_uri = data.get("gcsUri") or data.get("gcs_uri")
                    mime_type = (
                        data.get("mimeType")
                        or data.get("mime_type")
                        or "image/jpeg"
                    )
                    if gcs_uri:
                        logger.info("Adding part from URI: %s", gcs_uri)
                        parts.append(
                            types.Part.from_uri(
                                file_uri=gcs_uri, mime_type=mime_type
                            ),
                        )
            except Exception as e:
                logger.error(f"Error resolving source asset {asset_id}: {e}")
        logger.info("Resolved media parts: %s", parts)
        return parts

    async def generate_text(
        self,
        request: GenerateTextRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ):
        # No job id: only completed outputs are reused.
        return await self._run_step(
            guard,
            functools.partial(self._generate_text, request, authorization),
            job_step=False,
            step_inputs=self._text_step_inputs(request),
        )

    @staticmethod
    def _json_inputs(
        inputs: Any, allowed: Iterable[str] | None = None
    ) -> dict[str, Any]:
        """JSON-safe non-null inputs, optionally limited to ``allowed``."""
        data = inputs.model_dump(mode="json", exclude_none=True)
        if allowed is not None:
            allowed_set = set(allowed)
            data = {k: v for k, v in data.items() if k in allowed_set}
        return data

    @classmethod
    def _text_step_inputs(cls, request: GenerateTextRequest) -> dict[str, Any]:
        """Inputs of a text step with its prompt variables interpolated."""
        step_inputs = cls._json_inputs(request.inputs)
        prompt = step_inputs.get("prompt")
        if isinstance(prompt, str):
            step_inputs["prompt"] = interpolate_prompt_variables(
                prompt=prompt,
                variables=request.inputs.model_dump(),
                keep_unresolved=False,
            )
        return step_inputs

    @classmethod
    def _image_step_inputs(cls, request: ImageStepRequest) -> dict[str, Any]:
        """Inputs used by the configured image mode."""
        mode = request.config.mode or ImageModeEnum.GENERATE_IMAGE.value
        return cls._json_inputs(
            request.inputs, IMAGE_MODE_ALLOWED_INPUTS.get(mode, ["prompt"])
        )

    async def _generate_text(
        self,
        request: GenerateTextRequest,
        authorization: str | None = None,
    ) -> StepOutputs:
        generate_content_config = types.GenerateContentConfig(
            temperature=request.config.temperature,
            top_p=0.95,
            max_output_tokens=65535,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
            ],
        )

        contents = []

        logger.info("generate_text inputs: %s", request.inputs)
        # 1. Add Text Prompt
        if isinstance(request.inputs.prompt, str):
            prompt_text = request.inputs.prompt
            inputs_dict = request.inputs.model_dump()
            resolved_prompt = interpolate_prompt_variables(
                prompt=prompt_text,
                variables=inputs_dict,
                keep_unresolved=False,
            )
            contents.append(types.Part.from_text(text=resolved_prompt))

        # 2. Add Images
        if request.inputs.input_images:
            logger.info("Adding images")
            image_parts = await self._resolve_media_to_parts(
                request.inputs.input_images,
                authorization,
            )
            logger.info("Image parts: %s", image_parts)
            contents.extend(image_parts)

        # 3. Add Videos
        if request.inputs.input_videos:
            video_parts = await self._resolve_media_to_parts(
                request.inputs.input_videos,
                authorization,
            )
            contents.extend(video_parts)

        # L1 retry (quota / 503 / network only).
        text = await call_with_l1_retry(
            self._stream_text,
            request.config.model,
            contents,
            generate_content_config,
        )
        return {"generated_text": text}

    async def _stream_text(
        self,
        model: str,
        contents: list[Any],
        config: types.GenerateContentConfig,
    ) -> str:
        """One streamed Gemini call, retried as a whole by L1."""
        text = ""
        blocked_reason = None
        # Note: The original code used a stream but returned the full text at
        # the end. Keeping this behavior for now.
        for chunk in self.genai_client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            blocked_reason = blocked_reason or _safety_block_reason(chunk)
            if chunk.text:
                text += chunk.text
        if blocked_reason:
            raise StepError(
                422,
                ErrorCategory.SAFETY_BLOCK,
                "Text generation was blocked by safety filters "
                f"({blocked_reason}).",
            )
        return text

    async def _generate_image(
        self,
        workspace_id: int,
        prompt: str,
        model: str | None = None,
        aspect_ratio: str | None = None,
        brand_guidelines: bool = False,
        resolution: str | None = None,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> int:
        logger.info("Generate image execution")

        url = self.backend_url + "/api/images/generate-images"

        body = {
            "prompt": prompt,
            "workspace_id": workspace_id,
            "generation_model": model,
            "aspect_ratio": aspect_ratio,
            "use_brand_guidelines": brand_guidelines,
            "number_of_media": 1,
            "resolution": resolution,
        }

        # Creates the job and polls it for completion.
        return await self._submit_job(
            url,
            authorization,
            json_body=body,
            missing_id_detail="Couldn't create image",
            guard=guard,
        )

    async def _edit_image(
        self,
        workspace_id: int,
        prompt: str,
        input_images: Any,
        model: str | None = None,
        aspect_ratio: str | None = None,
        brand_guidelines: bool = False,
        resolution: str | None = None,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> int:
        logger.info("Edit image execution")

        url = self.backend_url + "/api/images/generate-images"

        media_items, asset_ids = self._normalize_asset_inputs(input_images)

        body = {
            "prompt": prompt,
            "workspace_id": workspace_id,
            "generation_model": model,
            "aspect_ratio": aspect_ratio,
            "use_brand_guidelines": brand_guidelines,
            "number_of_media": 1,
            "source_media_items": media_items,
            "source_asset_ids": asset_ids,
            "resolution": resolution,
        }

        # Creates the job and polls it for completion.
        return await self._submit_job(
            url,
            authorization,
            json_body=body,
            missing_id_detail="Couldn't edit image",
            guard=guard,
        )

    async def generate_video(
        self,
        request: GenerateVideoRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ):
        return await self._run_step(
            guard,
            functools.partial(
                self._generate_video, request, authorization, guard
            ),
            step_inputs=self._json_inputs(request.inputs),
        )

    async def _generate_video(
        self,
        request: GenerateVideoRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> StepOutputs:
        logger.info("Generate video execution")

        url = self.backend_url + "/api/videos/generate-videos"

        # 1. Process main reference images
        media_items, asset_ids = self._normalize_asset_inputs(
            request.inputs.input_images,
            default_role=AssetRoleEnum.IMAGE_REFERENCE_ASSET,
        )

        reference_images = []
        for aid in asset_ids:
            reference_images.append(
                {"asset_id": aid, "reference_type": "ASSET"}
            )

        # 2. Process Start Frame
        start_media, start_assets = self._normalize_asset_inputs(
            request.inputs.start_frame,
            default_role=AssetRoleEnum.START_FRAME,
        )
        media_items.extend(start_media)
        start_image_asset_id = start_assets[0] if start_assets else None

        # 3. Process End Frame
        end_media, end_assets = self._normalize_asset_inputs(
            request.inputs.end_frame,
            default_role=AssetRoleEnum.END_FRAME,
        )
        media_items.extend(end_media)
        end_image_asset_id = end_assets[0] if end_assets else None

        # 4. Process Reference Video & Audio (Only for models that support them)
        supports_audio_video_refs = request.config.model in (
            GenerationModelEnum.GEMINI_OMNI,
            GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        )

        reference_video = (
            self._map_to_asset_reference(request.inputs.input_video)
            if supports_audio_video_refs
            else None
        )
        reference_audio = (
            self._map_to_asset_reference(request.inputs.input_audio)
            if supports_audio_video_refs
            else None
        )

        body = {
            "prompt": request.inputs.prompt,
            "workspace_id": request.workspace_id,
            "generation_model": request.config.model,
            "aspect_ratio": request.config.aspect_ratio or "16:9",
            "resolution": request.config.resolution,
            "use_brand_guidelines": request.config.brand_guidelines,
            "reference_images": reference_images,
            "source_media_items": media_items,
            "start_image_asset_id": start_image_asset_id,
            "end_image_asset_id": end_image_asset_id,
            "reference_video": reference_video,
            "reference_audio": reference_audio,
            "number_of_media": 1,
            "duration_seconds": request.config.duration_seconds,
        }

        # Creates the job and polls it for completion.
        video_id = await self._submit_job(
            url,
            authorization,
            json_body=body,
            missing_id_detail="Couldn't create video",
            guard=guard,
        )

        return {"generated_video": video_id}

    def _map_to_asset_reference(
        self,
        input_data: Any,
    ) -> dict | None:
        if not input_data:
            return None

        # If input is a list, take the first element
        if isinstance(input_data, list):
            if len(input_data) == 0:
                return None
            input_data = input_data[0]

        # Handle ReferenceMediaOrAsset
        if isinstance(input_data, ReferenceMediaOrAsset):
            if input_data.sourceMediaItem:
                return {
                    "id": input_data.sourceMediaItem.mediaItemId,
                    "type": "media_item",
                    "index": input_data.sourceMediaItem.mediaIndex or 0,
                }
            if input_data.sourceAssetId:
                return {
                    "id": input_data.sourceAssetId,
                    "type": "source_asset",
                    "index": 0,
                }

        if isinstance(input_data, int):
            return {
                "id": input_data,
                "type": "media_item",
                "index": 0,
            }

        if isinstance(input_data, str) and input_data.isdigit():
            return {
                "id": int(input_data),
                "type": "media_item",
                "index": 0,
            }

        if isinstance(input_data, dict):
            if input_data.get("sourceMediaItem"):
                smi = input_data["sourceMediaItem"]
                return {
                    "id": smi.get("mediaItemId") or smi.get("media_item_id"),
                    "type": "media_item",
                    "index": smi.get("mediaIndex")
                    or smi.get("media_index")
                    or 0,
                }
            if input_data.get("sourceAssetId"):
                return {
                    "id": input_data["sourceAssetId"],
                    "type": "source_asset",
                    "index": 0,
                }
            if input_data.get("source_asset_id"):
                return {
                    "id": input_data["source_asset_id"],
                    "type": "source_asset",
                    "index": 0,
                }
            if "id" in input_data and "type" in input_data:
                return {
                    "id": input_data["id"],
                    "type": input_data["type"],
                    "index": input_data.get("index", 0),
                }

        return None

    def _map_to_vto_input_link(
        self,
        input_data: int | list | ReferenceMediaOrAsset,
    ) -> dict | None:
        if not input_data:
            return None

        # If input is a list, take the first element
        if isinstance(input_data, list):
            if len(input_data) == 0:
                return None
            input_data = input_data[0]

        # Handle ReferenceMediaOrAsset
        if isinstance(input_data, ReferenceMediaOrAsset):
            if input_data.sourceMediaItem:
                return {
                    "source_media_item": {
                        "media_item_id": input_data.sourceMediaItem.mediaItemId,
                        "media_index": input_data.sourceMediaItem.mediaIndex,
                    },
                }
            if input_data.sourceAssetId:
                return {"source_asset_id": input_data.sourceAssetId}

        if isinstance(input_data, int):
            return {
                "source_media_item": {
                    "media_item_id": input_data,
                    "media_index": 0,
                },
            }

        return None

    async def _virtual_try_on(
        self,
        workspace_id: int,
        model_image: Any,
        top_image: Any = None,
        bottom_image: Any = None,
        dress_image: Any = None,
        shoes_image: Any = None,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> int:
        logger.info("Virtual Try On execution")

        url = self.backend_url + "/api/images/generate-images-for-vto"

        person_image = self._map_to_vto_input_link(model_image)
        top_link = self._map_to_vto_input_link(top_image)
        bottom_link = self._map_to_vto_input_link(bottom_image)
        dress_link = self._map_to_vto_input_link(dress_image)
        shoes_link = self._map_to_vto_input_link(shoes_image)

        if not person_image:
            raise invalid_input_error(
                "Model image is required for Virtual Try-On"
            )

        body = {
            "workspace_id": workspace_id,
            "number_of_media": 1,
            "person_image": person_image,
            "top_image": top_link,
            "bottom_image": bottom_link,
            "dress_image": dress_link,
            "shoe_image": shoes_link,
        }

        # Creates the job and polls it for completion.
        return await self._submit_job(
            url,
            authorization,
            json_body=body,
            missing_id_detail="Couldn't create VTO image",
            guard=guard,
        )

    async def generate_audio(
        self,
        request: GenerateAudioRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ):
        return await self._run_step(
            guard,
            functools.partial(
                self._generate_audio, request, authorization, guard
            ),
            step_inputs=self._json_inputs(request.inputs),
        )

    async def _generate_audio(
        self,
        request: GenerateAudioRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> StepOutputs:
        logger.info("Generate audio execution")

        url = self.backend_url + "/api/audios/generate"

        body = {
            "workspace_id": request.workspace_id,
            "prompt": request.inputs.prompt,
            "model": request.config.model,
            "voice_name": request.config.voice_name,
            "language_code": request.config.language_code,
            "negative_prompt": request.config.negative_prompt,
            "seed": request.config.seed,
        }

        # Filter None values to let DTO defaults take over if needed
        body = {k: v for k, v in body.items() if v is not None}

        # Note: Audio generation is synchronous in the current controller/service implementation
        audio_id = await self._submit_job(
            url,
            authorization,
            json_body=body,
            missing_id_detail="Couldn't create audio",
            guard=guard,
        )

        return {"generated_audio": audio_id}

    async def _upscale_image(
        self,
        workspace_id: int,
        input_image: Any,
        upscale_factor: str | None = None,
        enhance_input_image: bool | None = None,
        image_preservation_factor: float | None = None,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> int:
        logger.info("Upscale image execution")
        media_items, asset_ids = self._normalize_asset_inputs(input_image)

        source_asset_id = asset_ids[0] if asset_ids else None
        media_item_id = media_items[0]["media_item_id"] if media_items else None

        if not source_asset_id and not media_item_id:
            raise invalid_input_error(
                "Input image is required for Image Upscaling"
            )

        url = self.backend_url + "/api/images/upload-upscale"

        data = {
            "workspaceId": str(workspace_id),
        }
        if source_asset_id:
            data["id"] = str(source_asset_id)
        if media_item_id:
            data["mediaItemId"] = str(media_item_id)
        if upscale_factor:
            data["upscaleFactor"] = upscale_factor
        if enhance_input_image is not None:
            data["enhance_input_image"] = str(enhance_input_image).lower()
        if image_preservation_factor is not None:
            data["image_preservation_factor"] = str(image_preservation_factor)

        # Creates the job and polls it for completion.
        return await self._submit_job(
            url,
            authorization,
            form_data=data,
            missing_id_detail="Couldn't create upscale job",
            guard=guard,
        )

    async def execute_image(
        self,
        request: ImageStepRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ):
        return await self._run_step(
            guard,
            functools.partial(
                self._execute_image, request, authorization, guard
            ),
            step_inputs=self._image_step_inputs(request),
        )

    async def _execute_image(
        self,
        request: ImageStepRequest,
        authorization: str | None = None,
        guard: StepIdempotencyGuard | None = None,
    ) -> StepOutputs:
        logger.info("Execute unified image step, mode: %s", request.config.mode)
        mode = request.config.mode or "generate_image"

        if mode == "generate_image":
            if not request.inputs.prompt:
                raise invalid_input_error(
                    "Prompt is required for Text to Image generation"
                )
            aspect_ratio = request.config.aspect_ratio or "1:1"
            if aspect_ratio == "auto":
                aspect_ratio = "1:1"
            image_id = await self._generate_image(
                workspace_id=request.workspace_id,
                prompt=request.inputs.prompt,
                model=request.config.model or "gemini-3.1-flash-image",
                aspect_ratio=aspect_ratio,
                brand_guidelines=request.config.brand_guidelines,
                resolution=request.config.resolution or "1K",
                authorization=authorization,
                guard=guard,
            )
            return {"generated_image": image_id}

        elif mode == "edit_image":
            if not request.inputs.prompt:
                raise invalid_input_error(
                    "Prompt is required for Image Editing"
                )
            if not request.inputs.input_images:
                raise invalid_input_error(
                    "Input images are required for Image Editing"
                )
            image_id = await self._edit_image(
                workspace_id=request.workspace_id,
                prompt=request.inputs.prompt,
                input_images=request.inputs.input_images,
                model=request.config.model or "gemini-2.5-flash-image",
                aspect_ratio=request.config.aspect_ratio or "1:1",
                brand_guidelines=request.config.brand_guidelines,
                resolution=request.config.resolution or "1K",
                authorization=authorization,
                guard=guard,
            )
            return {"generated_image": image_id}

        elif mode == "upscale_image":
            if not request.inputs.input_image:
                raise invalid_input_error(
                    "Input image is required for Image Upscaling"
                )
            image_id = await self._upscale_image(
                workspace_id=request.workspace_id,
                input_image=request.inputs.input_image,
                upscale_factor=request.config.upscale_factor or "x2",
                enhance_input_image=request.config.enhance_input_image,
                image_preservation_factor=request.config.image_preservation_factor,
                authorization=authorization,
                guard=guard,
            )
            return {"generated_image": image_id}

        elif mode == "virtual_try_on":
            if not request.inputs.model_image:
                raise invalid_input_error(
                    "Model image is required for Virtual Try-On"
                )
            image_id = await self._virtual_try_on(
                workspace_id=request.workspace_id,
                model_image=request.inputs.model_image,
                top_image=request.inputs.top_image,
                bottom_image=request.inputs.bottom_image,
                dress_image=request.inputs.dress_image,
                shoes_image=request.inputs.shoes_image,
                authorization=authorization,
                guard=guard,
            )
            return {"generated_image": image_id}

        else:
            raise invalid_input_error(f"Unsupported image mode: {mode}")

    # --- Loop -------------------------------------------------------------

    async def resolve_loop_items(
        self,
        request: ResolveLoopItemsRequest,
        *,
        user: UserModel,
        folder_repository: FolderRepository,
        gallery_repository: UnifiedGalleryRepository,
        workspace_auth: WorkspaceAuth,
        guard: StepIdempotencyGuard | None = None,
    ) -> StepOutputs:
        """Resolves the items a ``Loop`` step iterates over.

        Checkpointed under ``"<loop_step_id>"``: retries and resumes return
        the stored snapshot (items, folder name, truncation), so iterations
        stay deterministic even if the source changes mid-run. A stored
        snapshot is returned as is, even an empty one.

        Returns:
            ``{"items", "total_iterations", "total_found", "truncated"}``.
            At most :data:`MAX_LOOP_ITEMS` items are kept (the first ones).

        Raises:
            StepError: 422 ``INVALID_INPUT`` when the source resolves zero
                items (any mode, see :data:`LOOP_EMPTY_DETAILS`), when the
                folder is missing, deleted or outside the workspace (same
                message for all), or when the linked items are missing,
                unsupported, inaccessible or of another type.
        """
        # Filled by the work function before the guard checkpoints it.
        step_inputs: dict[str, Any] = {}

        async def work() -> StepOutputs:
            mode = request.config.mode
            if mode == "text_input":
                raw_text = request.inputs.items_text or ""
                step_inputs.update(mode="text_input", items_text=raw_text)
                tokens = [token.strip() for token in raw_text.split(",")]
                return self._loop_outputs(
                    request, [token for token in tokens if token]
                )
            if mode == "linked_items":
                items, skipped_count = await self._resolve_linked_items(
                    request, user, gallery_repository, workspace_auth
                )
                step_inputs.update(
                    mode="linked_items",
                    item_type=request.config.item_type,
                    source_count=len(request.inputs.linked_items or []),
                    skipped_count=skipped_count,
                )
                return self._loop_outputs(request, items)
            folder = await self._authorized_folder(
                request, user, folder_repository, workspace_auth
            )
            step_inputs.update(
                mode="folder",
                folder_id=folder.id,
                folder_name=folder.name,
                item_type=request.config.item_type,
            )
            rows, total_found = await gallery_repository.list_folder_loop_items(
                workspace_id=request.workspace_id,
                folder_id=folder.id,
                mime_type_prefix=request.config.item_type,
                limit=MAX_LOOP_ITEMS,
            )
            return self._loop_outputs(
                request,
                [_loop_item(item_type, item_id) for item_type, item_id in rows],
                total_found=total_found,
            )

        return await self._run_step(
            guard, work, job_step=False, step_inputs=step_inputs
        )

    @staticmethod
    async def _authorized_folder(
        request: ResolveLoopItemsRequest,
        user: UserModel,
        folder_repository: FolderRepository,
        workspace_auth: WorkspaceAuth,
    ) -> Any:
        """The configured folder if the user may read it in the workspace."""
        not_found = StepError(
            422, ErrorCategory.INVALID_INPUT, FOLDER_NOT_FOUND_DETAIL
        )
        if request.config.folder_id is None:
            raise StepError(
                422,
                ErrorCategory.INVALID_INPUT,
                "A Media Gallery folder is required in folder mode.",
            )
        await WorkflowsExecutorService._authorize_loop_workspace(
            request, user, workspace_auth, denied=not_found
        )
        folder = await folder_repository.get_folder_by_id(
            request.config.folder_id
        )
        if folder is None or folder.workspace_id != request.workspace_id:
            raise not_found
        return folder

    @staticmethod
    async def _authorize_loop_workspace(
        request: ResolveLoopItemsRequest,
        user: UserModel,
        workspace_auth: WorkspaceAuth,
        *,
        denied: StepError,
    ) -> None:
        """Raises ``denied`` if the user may not read the run's workspace."""
        try:
            await workspace_auth.authorize(
                workspace_id=request.workspace_id, user=user
            )
        except HTTPException as error:
            logger.warning(
                "User %s cannot access workspace %s of loop step %s: %s",
                user.id,
                request.workspace_id,
                request.step_id,
                error.status_code,
            )
            raise denied from error

    @staticmethod
    async def _resolve_linked_items(
        request: ResolveLoopItemsRequest,
        user: UserModel,
        gallery_repository: UnifiedGalleryRepository,
        workspace_auth: WorkspaceAuth,
    ) -> tuple[list[Any], int]:
        """Iteration values of a Linked Items ``Loop`` step, in link order.

        Flattens the upstream outputs resolved by the workflow engine and
        the Media Gallery picks, in insertion order (empty values are
        skipped). Both kinds are then validated the same way: the user must
        be able to read the workspace and every
        distinct linked id is an eligible gallery item of the workspace with
        the configured ``item_type``. Duplicates are kept.

        Returns:
            ``(values, skipped_count)``: the values use the folder loop item
            shapes (a media item with ``mediaIndex > 0`` stays a
            ``ReferenceMediaOrAsset``).

        Raises:
            StepError: 422 ``INVALID_INPUT`` when no item is linked, a value
                is unsupported, nothing resolves, or any item is not
                accessible (one generic message, without ids).
        """
        raw_values = request.inputs.linked_items
        if not raw_values:
            raise StepError(
                422, ErrorCategory.INVALID_INPUT, LINKED_ITEMS_REQUIRED_DETAIL
            )
        items, skipped_count = _flatten_linked_values(raw_values)
        # Fails before any authorization or query work when nothing resolved.
        _require_items("linked_items", len(items))
        item_type = request.config.item_type
        not_accessible = StepError(
            422,
            ErrorCategory.INVALID_INPUT,
            LINKED_ITEMS_NOT_ACCESSIBLE_DETAIL.format(item_type=item_type),
        )
        await WorkflowsExecutorService._authorize_loop_workspace(
            request, user, workspace_auth, denied=not_accessible
        )
        requested = {(kind, item_id) for kind, item_id, _ in items}
        found = await gallery_repository.filter_linked_loop_items(
            workspace_id=request.workspace_id,
            media_item_ids=[
                item_id
                for kind, item_id in requested
                if kind == LOOP_MEDIA_ITEM
            ],
            source_asset_ids=[
                item_id
                for kind, item_id in requested
                if kind == LOOP_SOURCE_ASSET
            ],
            mime_type_prefix=item_type,
        )
        missing_count = len(requested - found)
        if missing_count:
            logger.warning(
                "Loop step %s of run %s: %s of %s linked items are not "
                "accessible %s items of workspace %s.",
                request.step_id,
                request.run_id,
                missing_count,
                len(requested),
                item_type,
                request.workspace_id,
            )
            raise not_accessible
        return [_linked_loop_value(item) for item in items], skipped_count

    @staticmethod
    def _loop_outputs(
        request: ResolveLoopItemsRequest,
        items: list[Any],
        *,
        total_found: int | None = None,
    ) -> StepOutputs:
        """Loop snapshot keeping the first :data:`MAX_LOOP_ITEMS` items.

        Raises:
            StepError: 422 ``INVALID_INPUT`` when no item was found.
        """
        found = len(items) if total_found is None else max(total_found, 0)
        _require_items(request.config.mode, found)
        truncated = found > MAX_LOOP_ITEMS
        kept = items[:MAX_LOOP_ITEMS]
        if truncated:
            logger.warning(
                "Loop step %s of run %s found %s items; only the first %s "
                "will be processed (MAX_LOOP_ITEMS).",
                request.step_id,
                request.run_id,
                found,
                MAX_LOOP_ITEMS,
            )
        return {
            "items": kept,
            "total_iterations": len(kept),
            "total_found": found,
            "truncated": truncated,
        }
