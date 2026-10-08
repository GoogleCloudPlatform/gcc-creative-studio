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

"""Tests of ``WorkflowsExecutorService.resolve_loop_items`` and the
resolved ``step_inputs`` checkpointed by every executor step."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.common.schema.media_item_model import AssetRoleEnum
from src.galleries.repository.unified_gallery_repository import (
    LOOP_SOURCE_ASSET,
)
from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.schema.workflow_model import ImageInputs
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateTextRequest,
    GenerateVideoRequest,
    ImageStepRequest,
    ResolveLoopItemsRequest,
)
from src.workflows_executor.step_errors import StepError
from src.workflows_executor.workflows_executor_service import (
    FOLDER_NOT_FOUND_DETAIL,
    MAX_LOOP_ITEMS,
    WorkflowsExecutorService,
    _loop_item,
)

# Folder loop items of both kinds, as produced for each iteration.
MEDIA_LOOP_ITEM = _loop_item("media_item", 101)
ASSET_LOOP_ITEM = _loop_item(LOOP_SOURCE_ASSET, 7)
# (loop item, expected media item ids, expected source asset ids)
LOOP_ITEM_CASES = [
    pytest.param(MEDIA_LOOP_ITEM, [101], [], id="media-item"),
    pytest.param(ASSET_LOOP_ITEM, [], [7], id="source-asset"),
]


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch("src.workflows_executor.workflows_executor_service.RestClient"),
        patch(
            "src.workflows_executor.workflows_executor_service."
            "GenAIModelSetup.init"
        ),
    ):
        yield WorkflowsExecutorService()


@pytest.fixture(name="deps")
def fixture_deps():
    folder_repository = MagicMock()
    folder_repository.get_folder_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=42, name="Product Photos", workspace_id=1
        )
    )
    gallery_repository = MagicMock()
    gallery_repository.list_folder_loop_items = AsyncMock(
        return_value=(
            [
                ("media_item", 101),
                ("source_asset", 7),
                ("media_item", 103),
            ],
            3,
        )
    )
    workspace_auth = MagicMock()
    workspace_auth.authorize = AsyncMock(return_value=None)
    return SimpleNamespace(
        user=SimpleNamespace(id=7),
        folder_repository=folder_repository,
        gallery_repository=gallery_repository,
        workspace_auth=workspace_auth,
    )


def _guard(cached=None):
    guard = MagicMock()
    guard.begin = AsyncMock(return_value=cached)
    guard.complete = AsyncMock()
    guard.record_failure = AsyncMock()
    guard.state_key = "loop_1"
    guard.run_id = "run-1"
    return guard


def _request(**config):
    body = {
        "run_id": "run-1",
        "step_id": "loop_1",
        "execution_id": "exec-1",
        "workspace_id": 1,
        "config": {"mode": "folder", "folder_id": 42, **config},
    }
    return body


async def _resolve(service, deps, request, guard=None):
    return await service.resolve_loop_items(
        ResolveLoopItemsRequest.model_validate(request),
        user=deps.user,
        folder_repository=deps.folder_repository,
        gallery_repository=deps.gallery_repository,
        workspace_auth=deps.workspace_auth,
        guard=guard,
    )


@pytest.mark.anyio
async def test_folder_mode_lists_scalar_items_and_checkpoints_inputs(
    service, deps
):
    guard = _guard()

    outputs = await _resolve(service, deps, _request(), guard)

    assert outputs == {
        "items": [
            101,
            {"sourceAssetId": 7, "previewUrl": ""},
            103,
        ],
        "total_iterations": 3,
        "total_found": 3,
        "truncated": False,
    }
    deps.workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=1, user=deps.user
    )
    deps.gallery_repository.list_folder_loop_items.assert_awaited_once_with(
        workspace_id=1,
        folder_id=42,
        mime_type_prefix="image",
        limit=MAX_LOOP_ITEMS,
    )
    guard.begin.assert_awaited_once_with(job_step=False)
    guard.complete.assert_awaited_once_with(
        outputs,
        step_inputs={
            "mode": "folder",
            "folder_id": 42,
            "folder_name": "Product Photos",
            "item_type": "image",
        },
    )


@pytest.mark.anyio
async def test_folder_mode_truncates_and_logs_warning(service, deps, caplog):
    deps.gallery_repository.list_folder_loop_items.return_value = (
        [("media_item", n) for n in range(1, MAX_LOOP_ITEMS + 1)],
        250,
    )

    with caplog.at_level(logging.WARNING):
        outputs = await _resolve(service, deps, _request(item_type="video"))

    assert len(outputs["items"]) == MAX_LOOP_ITEMS
    assert outputs["items"][0] == 1
    assert outputs["total_iterations"] == MAX_LOOP_ITEMS
    assert outputs["total_found"] == 250
    assert outputs["truncated"] is True
    assert "warning" not in outputs
    assert "found 250 items" in caplog.text


@pytest.mark.anyio
async def test_folder_mode_empty_folder_is_zero_iterations(service, deps):
    deps.gallery_repository.list_folder_loop_items.return_value = ([], 0)

    outputs = await _resolve(service, deps, _request())

    assert outputs == {
        "items": [],
        "total_iterations": 0,
        "total_found": 0,
        "truncated": False,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "folder",
    [None, SimpleNamespace(id=42, name="Other", workspace_id=2)],
    ids=["deleted", "other-workspace"],
)
async def test_folder_not_found_or_foreign_is_422(service, deps, folder):
    deps.folder_repository.get_folder_by_id.return_value = folder
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _request(), guard)

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_category is ErrorCategory.INVALID_INPUT
    assert exc_info.value.detail == FOLDER_NOT_FOUND_DETAIL
    guard.record_failure.assert_awaited_once()
    guard.complete.assert_not_awaited()
    deps.gallery_repository.list_folder_loop_items.assert_not_awaited()


@pytest.mark.anyio
async def test_workspace_auth_failure_uses_same_message(service, deps):
    deps.workspace_auth.authorize.side_effect = HTTPException(403, "nope")

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _request())

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == FOLDER_NOT_FOUND_DETAIL
    deps.folder_repository.get_folder_by_id.assert_not_awaited()


@pytest.mark.anyio
async def test_folder_mode_requires_folder_id(service, deps):
    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _request(folder_id=None))

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_category is ErrorCategory.INVALID_INPUT


@pytest.mark.anyio
async def test_text_mode_splits_trims_and_drops_empty(service, deps):
    guard = _guard()
    request = _request(mode="text_input", folder_id=None)
    request["inputs"] = {"items_text": " cat, dog ,, bird ,"}

    outputs = await _resolve(service, deps, request, guard)

    assert outputs == {
        "items": ["cat", "dog", "bird"],
        "total_iterations": 3,
        "total_found": 3,
        "truncated": False,
    }
    guard.complete.assert_awaited_once_with(
        outputs,
        step_inputs={"mode": "text_input", "items_text": " cat, dog ,, bird ,"},
    )
    deps.folder_repository.get_folder_by_id.assert_not_awaited()


@pytest.mark.anyio
async def test_text_mode_truncates_keeping_order(service, deps):
    request = _request(mode="text_input")
    request["inputs"] = {"items_text": ",".join(f"i{n}" for n in range(250))}

    outputs = await _resolve(service, deps, request)

    assert outputs["items"] == [f"i{n}" for n in range(MAX_LOOP_ITEMS)]
    assert outputs["total_found"] == 250
    assert outputs["truncated"] is True


@pytest.mark.anyio
async def test_text_mode_empty_text_is_zero_iterations(service, deps):
    outputs = await _resolve(service, deps, _request(mode="text_input"))

    assert outputs["items"] == []
    assert outputs["total_iterations"] == 0


@pytest.mark.anyio
async def test_cached_snapshot_is_returned_without_queries(service, deps):
    cached = {
        "items": [1],
        "total_iterations": 1,
        "total_found": 1,
        "truncated": False,
    }
    guard = _guard(cached=cached)

    outputs = await _resolve(service, deps, _request(), guard)

    assert outputs == cached
    deps.folder_repository.get_folder_by_id.assert_not_awaited()
    guard.complete.assert_not_awaited()


def test_request_rejects_oversized_text_and_bad_iteration():
    request = _request(mode="text_input")
    request["inputs"] = {"items_text": "x" * 100_001}
    with pytest.raises(ValidationError):
        ResolveLoopItemsRequest.model_validate(request)
    with pytest.raises(ValidationError):
        ResolveLoopItemsRequest.model_validate(
            {**_request(), "step_id": "loop#1"}
        )
    with pytest.raises(ValidationError):
        ResolveLoopItemsRequest.model_validate(
            {**_request(), "config": {"mode": "folder", "item_type": "pdf"}}
        )


def test_text_step_inputs_interpolates_prompt():
    request = GenerateTextRequest.model_validate(
        {
            "inputs": {"prompt": "a <animal> in <place>", "animal": "cat"},
            "config": {"model": "gemini-3-flash-preview", "temperature": 0.5},
        }
    )

    step_inputs = WorkflowsExecutorService._text_step_inputs(request)

    assert step_inputs["animal"] == "cat"
    assert step_inputs["prompt"].startswith("a cat in")
    assert "<animal>" not in step_inputs["prompt"]


def test_image_step_inputs_filters_by_mode():
    request = ImageStepRequest.model_validate(
        {
            "workspace_id": 1,
            "inputs": {"prompt": "eagle", "input_image": [5]},
            "config": {"mode": "upscale_image"},
        }
    )

    step_inputs = WorkflowsExecutorService._image_step_inputs(request)

    assert "prompt" not in step_inputs
    assert step_inputs["input_image"] == [5]


def _image_request(mode: str, **inputs) -> ImageStepRequest:
    return ImageStepRequest.model_validate(
        {
            "workspace_id": 1,
            "inputs": inputs,
            "config": {"mode": mode},
            "iteration": 0,
        }
    )


def _video_request(**inputs) -> GenerateVideoRequest:
    return GenerateVideoRequest.model_validate(
        {
            "workspace_id": 1,
            "inputs": {"prompt": "x", **inputs},
            "config": {"model": "veo"},
            "iteration": 0,
        }
    )


def _media_item_ids(media_items: list[dict]) -> list[int]:
    return [media_item["media_item_id"] for media_item in media_items]


@pytest.mark.parametrize(
    "loop_item, expected_media_ids, expected_asset_ids", LOOP_ITEM_CASES
)
def test_loop_item_in_multi_input_list_is_valid_image_input(
    service, loop_item, expected_media_ids, expected_asset_ids
):
    """A multi-input port stores its links as a list of references, so the
    resolved input is a list holding the loop item."""
    request = _image_request(
        "generate_image", prompt="x", input_images=[loop_item]
    )

    media_items, asset_ids = service._normalize_asset_inputs(
        request.inputs.input_images
    )

    assert _media_item_ids(media_items) == expected_media_ids
    assert asset_ids == expected_asset_ids


@pytest.mark.parametrize(
    "loop_item, expected_media_ids, expected_asset_ids", LOOP_ITEM_CASES
)
def test_loop_item_wired_directly_is_valid_image_input(
    service, loop_item, expected_media_ids, expected_asset_ids
):
    request = _image_request(
        "generate_image", prompt="x", input_images=loop_item
    )

    media_items, asset_ids = service._normalize_asset_inputs(
        request.inputs.input_images
    )

    assert _media_item_ids(media_items) == expected_media_ids
    assert asset_ids == expected_asset_ids


@pytest.mark.parametrize("loop_item", [MEDIA_LOOP_ITEM, ASSET_LOOP_ITEM])
def test_nested_media_lists_stay_rejected(loop_item):
    """Step inputs accept a single level of media list only."""
    with pytest.raises(ValidationError):
        ImageInputs(input_images=[[loop_item]])


@pytest.mark.parametrize(
    "loop_item, expected_media_ids, expected_asset_ids", LOOP_ITEM_CASES
)
def test_loop_item_feeds_upscale_input_image(
    service, loop_item, expected_media_ids, expected_asset_ids
):
    request = _image_request("upscale_image", input_image=loop_item)

    media_items, asset_ids = service._normalize_asset_inputs(
        request.inputs.input_image
    )

    assert _media_item_ids(media_items) == expected_media_ids
    assert asset_ids == expected_asset_ids


@pytest.mark.parametrize(
    "loop_item, expected_link",
    [
        pytest.param(
            MEDIA_LOOP_ITEM,
            {"source_media_item": {"media_item_id": 101, "media_index": 0}},
            id="media-item",
        ),
        pytest.param(
            ASSET_LOOP_ITEM, {"source_asset_id": 7}, id="source-asset"
        ),
    ],
)
def test_loop_item_feeds_vto_model_image(service, loop_item, expected_link):
    request = _image_request("virtual_try_on", model_image=loop_item)

    link = service._map_to_vto_input_link(request.inputs.model_image)

    assert link == expected_link


@pytest.mark.parametrize(
    "loop_item, expected_media_ids, expected_asset_ids", LOOP_ITEM_CASES
)
def test_loop_item_feeds_video_frames(
    service, loop_item, expected_media_ids, expected_asset_ids
):
    request = _video_request(start_frame=loop_item, end_frame=loop_item)

    for frame, role in (
        (request.inputs.start_frame, AssetRoleEnum.START_FRAME),
        (request.inputs.end_frame, AssetRoleEnum.END_FRAME),
    ):
        media_items, asset_ids = service._normalize_asset_inputs(
            frame, default_role=role
        )
        assert _media_item_ids(media_items) == expected_media_ids
        assert all(item["role"] == role.value for item in media_items)
        assert asset_ids == expected_asset_ids


@pytest.mark.parametrize(
    "loop_item, expected_reference",
    [
        pytest.param(
            MEDIA_LOOP_ITEM,
            {"id": 101, "type": "media_item", "index": 0},
            id="media-item",
        ),
        pytest.param(
            ASSET_LOOP_ITEM,
            {"id": 7, "type": "source_asset", "index": 0},
            id="source-asset",
        ),
    ],
)
def test_loop_item_feeds_video_reference_input(
    service, loop_item, expected_reference
):
    request = _video_request(input_video=loop_item)

    reference = service._map_to_asset_reference(request.inputs.input_video)

    assert reference == expected_reference
