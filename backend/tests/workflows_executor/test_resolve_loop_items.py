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
    MAX_LOOP_LINKED_RAW_VALUES,
    GenerateTextRequest,
    GenerateVideoRequest,
    ImageStepRequest,
    ResolveLoopItemsRequest,
)
from src.workflows_executor.step_errors import StepError
from src.workflows_executor.workflows_executor_service import (
    FOLDER_NOT_FOUND_DETAIL,
    LINKED_ITEMS_NOT_ACCESSIBLE_DETAIL,
    LINKED_ITEMS_REQUIRED_DETAIL,
    LINKED_ITEMS_UNSUPPORTED_DETAIL,
    LOOP_EMPTY_DETAILS,
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


def _assert_invalid_input(exc_info, detail: str) -> None:
    error = exc_info.value
    assert error.status_code == 422
    assert error.error_category is ErrorCategory.INVALID_INPUT
    assert error.detail == detail


@pytest.mark.anyio
async def test_folder_mode_empty_folder_is_422(service, deps):
    deps.gallery_repository.list_folder_loop_items.return_value = ([], 0)
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _request(), guard)

    _assert_invalid_input(exc_info, LOOP_EMPTY_DETAILS["folder"])
    guard.record_failure.assert_awaited_once()
    guard.complete.assert_not_awaited()


@pytest.mark.anyio
async def test_folder_mode_all_items_filtered_is_422(service, deps):
    """Type / external-URL filtering happens in SQL: nothing matches."""
    deps.gallery_repository.list_folder_loop_items.return_value = ([], 0)
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _request(item_type="audio"), guard)

    _assert_invalid_input(exc_info, LOOP_EMPTY_DETAILS["folder"])
    deps.gallery_repository.list_folder_loop_items.assert_awaited_once_with(
        workspace_id=1,
        folder_id=42,
        mime_type_prefix="audio",
        limit=MAX_LOOP_ITEMS,
    )
    guard.complete.assert_not_awaited()


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
@pytest.mark.parametrize(
    "items_text",
    [None, "", "   ", " , ,, "],
    ids=["null", "empty", "blank", "separators-only"],
)
async def test_text_mode_empty_text_is_422(service, deps, items_text):
    guard = _guard()
    request = _request(mode="text_input", folder_id=None)
    request["inputs"] = {"items_text": items_text}

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, request, guard)

    _assert_invalid_input(exc_info, LOOP_EMPTY_DETAILS["text_input"])
    guard.record_failure.assert_awaited_once()
    guard.complete.assert_not_awaited()


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


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["folder", "text_input", "linked_items"])
async def test_cached_empty_snapshot_is_returned(service, deps, mode):
    """Snapshots stored before empty loops started failing still resume."""
    cached = {
        "items": [],
        "total_iterations": 0,
        "total_found": 0,
        "truncated": False,
    }
    guard = _guard(cached=cached)

    outputs = await _resolve(service, deps, _request(mode=mode), guard)

    assert outputs == cached
    guard.record_failure.assert_not_awaited()
    guard.complete.assert_not_awaited()


# --- Linked Items mode -------------------------------------------------


def _linked_request(linked_items, *, item_type="image", with_inputs=True):
    request = _request(mode="linked_items", folder_id=None, item_type=item_type)
    if with_inputs:
        request["inputs"] = {"linked_items": linked_items}
    return request


def _found(*pairs):
    return set(pairs)


@pytest.mark.anyio
async def test_linked_mode_keeps_order_and_shapes(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=_found(
            ("media_item", 101),
            ("media_item", 102),
            ("media_item", 103),
            ("source_asset", 7),
        )
    )
    guard = _guard()
    linked_items = [
        101,
        {"sourceAssetId": 7, "previewUrl": "https://evil"},
        {
            "sourceMediaItem": {
                "mediaItemId": 103,
                "mediaIndex": 2,
                "role": "input",
            },
            "previewUrl": "",
        },
        "102",
        {"sourceMediaItem": {"mediaItemId": 102, "mediaIndex": 0}},
    ]

    outputs = await _resolve(
        service, deps, _linked_request(linked_items), guard
    )

    assert outputs == {
        "items": [
            101,
            {"sourceAssetId": 7, "previewUrl": ""},
            {
                "sourceMediaItem": {
                    "mediaItemId": 103,
                    "mediaIndex": 2,
                    "role": "input",
                },
                "previewUrl": "",
            },
            102,
            102,
        ],
        "total_iterations": 5,
        "total_found": 5,
        "truncated": False,
    }
    deps.workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=1, user=deps.user
    )
    filter_kwargs = (
        deps.gallery_repository.filter_linked_loop_items.await_args.kwargs
    )
    assert filter_kwargs["workspace_id"] == 1
    assert filter_kwargs["mime_type_prefix"] == "image"
    assert sorted(filter_kwargs["media_item_ids"]) == [101, 102, 103]
    assert filter_kwargs["source_asset_ids"] == [7]
    guard.complete.assert_awaited_once_with(
        outputs,
        step_inputs={
            "mode": "linked_items",
            "item_type": "image",
            "source_count": 5,
            "skipped_count": 0,
        },
    )
    deps.folder_repository.get_folder_by_id.assert_not_awaited()
    deps.gallery_repository.list_folder_loop_items.assert_not_awaited()


@pytest.mark.anyio
async def test_linked_mode_flattens_nested_and_skips_empty(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=_found(("media_item", 104), ("media_item", 105))
    )
    guard = _guard()

    outputs = await _resolve(
        service,
        deps,
        _linked_request(
            [None, [104, [105]], "", {}, [], [[]]], item_type="video"
        ),
        guard,
    )

    assert outputs["items"] == [104, 105]
    step_inputs = guard.complete.await_args.kwargs["step_inputs"]
    assert step_inputs == {
        "mode": "linked_items",
        "item_type": "video",
        "source_count": 6,
        "skipped_count": 5,
    }


@pytest.mark.anyio
async def test_linked_mode_keeps_duplicates(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=_found(("media_item", 101))
    )

    outputs = await _resolve(service, deps, _linked_request([101, 101]))

    assert outputs["items"] == [101, 101]
    assert outputs["total_iterations"] == 2
    filter_kwargs = (
        deps.gallery_repository.filter_linked_loop_items.await_args.kwargs
    )
    assert filter_kwargs["media_item_ids"] == [101]


# Media Gallery picks as sent by the YAML (ids only) and as stored by the
# editor (with previewUrl, role and empty keys).
GALLERY_PICKS = [
    {"sourceAssetId": 7},
    {
        "previewUrl": "https://signed",
        "sourceAssetId": None,
        "sourceMediaItem": {
            "mediaItemId": 103,
            "mediaIndex": 1,
            "role": "input",
            "extra": "ignored",
        },
    },
    {"sourceMediaItem": {"mediaItemId": 104}},
]
GALLERY_PICK_VALUES = [
    {"sourceAssetId": 7, "previewUrl": ""},
    {
        "sourceMediaItem": {
            "mediaItemId": 103,
            "mediaIndex": 1,
            "role": "input",
        },
        "previewUrl": "",
    },
    104,
]
GALLERY_PICK_FOUND = _found(
    ("source_asset", 7), ("media_item", 103), ("media_item", 104)
)


@pytest.mark.anyio
async def test_linked_mode_gallery_picks_only(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=GALLERY_PICK_FOUND
    )

    outputs = await _resolve(service, deps, _linked_request(GALLERY_PICKS))

    assert outputs["items"] == GALLERY_PICK_VALUES
    filter_kwargs = (
        deps.gallery_repository.filter_linked_loop_items.await_args.kwargs
    )
    assert sorted(filter_kwargs["media_item_ids"]) == [103, 104]
    assert filter_kwargs["source_asset_ids"] == [7]
    deps.workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=1, user=deps.user
    )


@pytest.mark.anyio
async def test_linked_mode_mixes_upstream_values_and_picks(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=GALLERY_PICK_FOUND | _found(("media_item", 101))
    )
    guard = _guard()
    linked_items = [101, *GALLERY_PICKS, None]

    outputs = await _resolve(
        service, deps, _linked_request(linked_items), guard
    )

    assert outputs["items"] == [101, *GALLERY_PICK_VALUES]
    assert guard.complete.await_args.kwargs["step_inputs"] == {
        "mode": "linked_items",
        "item_type": "image",
        "source_count": 5,
        "skipped_count": 1,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "found",
    [
        GALLERY_PICK_FOUND - _found(("media_item", 103)),
        GALLERY_PICK_FOUND - _found(("source_asset", 7)),
    ],
    ids=["deleted-or-foreign-media-item", "wrong-type-or-foreign-asset"],
)
async def test_linked_mode_inaccessible_gallery_pick_is_422(
    service, deps, found
):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=found
    )
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _linked_request(GALLERY_PICKS), guard)

    _assert_invalid_input(
        exc_info, LINKED_ITEMS_NOT_ACCESSIBLE_DETAIL.format(item_type="image")
    )
    guard.complete.assert_not_awaited()


@pytest.mark.anyio
async def test_linked_mode_id_less_pick_is_422(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock()

    with pytest.raises(StepError) as exc_info:
        await _resolve(
            service, deps, _linked_request([101, {"sourceAssetId": None}])
        )

    _assert_invalid_input(exc_info, LINKED_ITEMS_UNSUPPORTED_DETAIL)
    deps.gallery_repository.filter_linked_loop_items.assert_not_awaited()


@pytest.mark.anyio
async def test_linked_mode_truncates_to_max_items(service, deps, caplog):
    total = MAX_LOOP_ITEMS + 20
    linked_items = list(range(1, total + 1))
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=_found(*(("media_item", n) for n in linked_items))
    )

    with caplog.at_level(logging.WARNING):
        outputs = await _resolve(service, deps, _linked_request(linked_items))

    assert outputs["items"] == linked_items[:MAX_LOOP_ITEMS]
    assert outputs["total_found"] == total
    assert outputs["truncated"] is True
    assert f"found {total} items" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "linked_items",
    [[None], ["", {}, []], [[], [[]]], [None, [None, [None]]]],
    ids=["null", "empty-values", "nested-empty-lists", "nested-nulls"],
)
async def test_linked_mode_zero_resolved_items_is_422(
    service, deps, linked_items
):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock()
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _linked_request(linked_items), guard)

    _assert_invalid_input(exc_info, LOOP_EMPTY_DETAILS["linked_items"])
    deps.workspace_auth.authorize.assert_not_awaited()
    deps.gallery_repository.filter_linked_loop_items.assert_not_awaited()
    guard.record_failure.assert_awaited_once()
    guard.complete.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "request_body",
    [
        _linked_request(None, with_inputs=False),
        _linked_request(None),
        _linked_request([]),
    ],
    ids=["inputs-missing", "null", "empty-list"],
)
async def test_linked_mode_without_links_is_422(service, deps, request_body):
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, request_body, guard)

    _assert_invalid_input(exc_info, LINKED_ITEMS_REQUIRED_DETAIL)
    deps.workspace_auth.authorize.assert_not_awaited()
    guard.complete.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "linked_value",
    [
        "hello",
        "  ",
        True,
        0,
        -3,
        1.5,
        {"foo": 1},
        {"sourceAssetId": "abc"},
        {"sourceMediaItem": {"mediaItemId": 5, "mediaIndex": -1}},
        {"sourceMediaItem": {"mediaItemId": 5, "mediaIndex": True}},
        {"sourceMediaItem": {"mediaItemId": None}},
        {"sourceMediaItem": "5", "sourceAssetId": 7},
        [[[1]]],
    ],
    ids=[
        "text",
        "blank-text",
        "bool",
        "zero",
        "negative",
        "float",
        "unknown-dict",
        "bad-asset-id",
        "negative-index",
        "bool-index",
        "missing-media-id",
        "bad-media-ref",
        "too-deep",
    ],
)
async def test_linked_mode_unsupported_value_is_422(
    service, deps, linked_value
):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _linked_request([101, linked_value]))

    _assert_invalid_input(exc_info, LINKED_ITEMS_UNSUPPORTED_DETAIL)
    deps.workspace_auth.authorize.assert_not_awaited()
    deps.gallery_repository.filter_linked_loop_items.assert_not_awaited()


@pytest.mark.anyio
async def test_linked_mode_accepts_max_nesting_depth(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=_found(("media_item", 1))
    )

    outputs = await _resolve(service, deps, _linked_request([[[1]]]))

    assert outputs["items"] == [1]


@pytest.mark.anyio
async def test_linked_mode_workspace_auth_failure_is_generic_422(service, deps):
    deps.workspace_auth.authorize.side_effect = HTTPException(403, "nope")
    deps.gallery_repository.filter_linked_loop_items = AsyncMock()
    guard = _guard()

    with pytest.raises(StepError) as exc_info:
        await _resolve(service, deps, _linked_request([101]), guard)

    _assert_invalid_input(
        exc_info, LINKED_ITEMS_NOT_ACCESSIBLE_DETAIL.format(item_type="image")
    )
    deps.gallery_repository.filter_linked_loop_items.assert_not_awaited()
    guard.complete.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "found",
    [
        _found(("media_item", 101)),
        _found(("media_item", 101), ("media_item", 7)),
        set(),
    ],
    ids=["one-missing", "asset-id-matched-as-media-item", "none-found"],
)
async def test_linked_mode_inaccessible_items_are_generic_422(
    service, deps, found, caplog
):
    """Missing, deleted, foreign or wrong-type items share one message."""
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=found
    )
    guard = _guard()
    request_body = _linked_request(
        [101, {"sourceAssetId": 987654, "previewUrl": ""}], item_type="audio"
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(StepError) as exc_info:
            await _resolve(service, deps, request_body, guard)

    detail = LINKED_ITEMS_NOT_ACCESSIBLE_DETAIL.format(item_type="audio")
    _assert_invalid_input(exc_info, detail)
    assert "987654" not in detail
    assert "987654" not in caplog.text
    guard.record_failure.assert_awaited_once()
    guard.complete.assert_not_awaited()


@pytest.mark.anyio
async def test_linked_mode_second_call_returns_checkpoint(service, deps):
    deps.gallery_repository.filter_linked_loop_items = AsyncMock(
        return_value=_found(("media_item", 101))
    )
    first_guard = _guard()
    request_body = _linked_request([101])

    first_outputs = await _resolve(service, deps, request_body, first_guard)
    second_guard = _guard(cached=first_outputs)
    second_outputs = await _resolve(service, deps, request_body, second_guard)

    assert second_outputs == first_outputs
    deps.gallery_repository.filter_linked_loop_items.assert_awaited_once()
    second_guard.complete.assert_not_awaited()


def test_request_bounds_linked_items():
    at_bound = _linked_request([1] * MAX_LOOP_LINKED_RAW_VALUES)
    request = ResolveLoopItemsRequest.model_validate(at_bound)
    assert len(request.inputs.linked_items) == MAX_LOOP_LINKED_RAW_VALUES
    with pytest.raises(ValidationError):
        ResolveLoopItemsRequest.model_validate(
            _linked_request([1] * (MAX_LOOP_LINKED_RAW_VALUES + 1))
        )


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
