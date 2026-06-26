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
from fastapi import HTTPException
from httpx import Response

from src.common.schema.media_item_model import AssetRoleEnum
from src.workflows.schema.workflow_model import ReferenceMediaOrAsset
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch(
            "src.workflows_executor.workflows_executor_service.RestClient",
        ) as mock_rest_client_class,
        patch(
            "src.workflows_executor.workflows_executor_service.GenAIModelSetup.init",
        ) as mock_genai_init,
    ):
        mock_rest_client = AsyncMock()
        mock_rest_client_class.return_value = mock_rest_client

        mock_genai_client = MagicMock()
        mock_genai_init.return_value = mock_genai_client

        service = WorkflowsExecutorService()
        # Attach the mocks to the service object to allow assertion later
        service.mock_rest_client = mock_rest_client
        service.mock_genai_client = mock_genai_client
        yield service


def test_normalize_asset_inputs_single_int(service):
    media_items, asset_ids = service._normalize_asset_inputs(123)
    assert len(media_items) == 1
    assert media_items[0]["media_item_id"] == 123
    assert media_items[0]["role"] == AssetRoleEnum.INPUT.value
    assert len(asset_ids) == 0


def test_normalize_asset_inputs_list_mixed(service):
    mock_ref = ReferenceMediaOrAsset(
        previewUrl="",
        sourceMediaItem={"mediaItemId": 456, "mediaIndex": 1, "role": "OUTPUT"},
        sourceAssetId=None,
    )
    mock_asset_ref = ReferenceMediaOrAsset(
        previewUrl="",
        sourceMediaItem=None,
        sourceAssetId=789,
    )

    inputs = [123, mock_ref, mock_asset_ref]
    media_items, asset_ids = service._normalize_asset_inputs(inputs)

    assert len(media_items) == 2
    assert media_items[0]["media_item_id"] == 123
    assert media_items[1]["media_item_id"] == 456
    assert media_items[1]["role"] == "OUTPUT"

    assert len(asset_ids) == 1
    assert asset_ids[0] == 789


@pytest.mark.anyio
async def test_poll_job_status_success(service):
    # Mock rest_client.get to return completed immediately
    mock_response = Response(200, json={"status": "completed"})
    service.mock_rest_client.get.return_value = mock_response

    # Patch asyncio.sleep to speed up tests
    with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
        result = await service._poll_job_status(123)
        assert result is True
        # Verify it was called once on target URL
        service.mock_rest_client.get.assert_called_once()


@pytest.mark.anyio
async def test_poll_job_status_timeout(service):
    # Mock rest_client.get to return running forever
    mock_response = Response(200, json={"status": "running"})
    service.mock_rest_client.get.return_value = mock_response

    # Speed up sleep to avoid 600s stall
    with (
        patch("asyncio.sleep", AsyncMock()),
        patch(
            "asyncio.get_event_loop",
        ) as mock_loop,
    ):
        mock_loop_instance = MagicMock()
        # Simulate time advancing 600s immediately to trigger timeout
        mock_loop_instance.time.side_effect = [0, 601]
        mock_loop.return_value = mock_loop_instance

        with pytest.raises(HTTPException) as exc:
            await service._poll_job_status(123)
        assert exc.value.status_code == 504


@pytest.mark.anyio
async def test_poll_job_status_failed(service):
    mock_response = Response(
        200,
        json={"status": "failed", "error_message": "Generation Error"},
    )
    service.mock_rest_client.get.return_value = mock_response

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await service._poll_job_status(123)
        assert exc.value.status_code == 500
        assert "Generation Error" in exc.value.detail


@pytest.mark.anyio
async def test_resolve_media_to_parts_success(service):
    # Mock responses for gallery and source asset
    mock_gallery_response = Response(
        200,
        json={"gcsUris": ["gs://bucket/gallery.png"], "mimeType": "image/png"},
    )
    mock_source_asset_response = Response(
        200,
        json={"gcsUri": "gs://bucket/asset.jpg", "mimeType": "image/jpeg"},
    )
    service.mock_rest_client.get.side_effect = [
        mock_gallery_response,
        mock_source_asset_response,
    ]

    # Reference item
    mock_ref = ReferenceMediaOrAsset(
        previewUrl="",
        sourceMediaItem=None,
        sourceAssetId=456,
    )

    inputs = [123, mock_ref]

    with patch(
        "src.workflows_executor.workflows_executor_service.types.Part.from_uri",
    ) as mock_from_uri:
        # Mock Part objects
        mock_part1 = MagicMock()
        mock_part2 = MagicMock()
        mock_from_uri.side_effect = [mock_part1, mock_part2]

        parts = await service._resolve_media_to_parts(inputs)

        assert len(parts) == 2
        # Verify from_uri was called with correct values
        mock_from_uri.assert_any_call(
            file_uri="gs://bucket/gallery.png",
            mime_type="image/png",
        )
        mock_from_uri.assert_any_call(
            file_uri="gs://bucket/asset.jpg",
            mime_type="image/jpeg",
        )


@pytest.mark.anyio
async def test_generate_text_stream(service):
    # Create request mock DTO
    request = MagicMock()
    request.config.temperature = 0.7
    request.config.model = "gemini-1.5-pro"
    request.inputs.prompt = "Write a story"
    request.inputs.input_images = None
    request.inputs.input_videos = None

    # Mock chunk generators
    mock_chunk1 = MagicMock()
    mock_chunk1.text = "Hello "
    mock_chunk2 = MagicMock()
    mock_chunk2.text = "World!"

    # Mock stream method
    service.mock_genai_client.models.generate_content_stream.return_value = [
        mock_chunk1,
        mock_chunk2,
    ]

    result = await service.generate_text(request)

    assert result["generated_text"] == "Hello World!"
    # Verify client call
    service.mock_genai_client.models.generate_content_stream.assert_called_once()
    args, kwargs = (
        service.mock_genai_client.models.generate_content_stream.call_args
    )
    assert kwargs["model"] == "gemini-1.5-pro"
    # Prompt is wrapped as Part.from_text inside contents
    assert len(kwargs["contents"]) == 1


@pytest.mark.anyio
async def test_generate_image(service):
    request = MagicMock()
    request.workspace_id = 1
    request.inputs.prompt = "A cat"
    request.config.model = "gemini-3.1-flash-image"
    request.config.aspect_ratio = "1:1"
    request.config.brand_guidelines = False

    service.mock_rest_client.post.return_value = Response(200, json={"id": 999})

    with patch.object(
        service,
        "_poll_job_status",
        AsyncMock(return_value=True),
    ) as mock_poll:
        result = await service.generate_image(request)
        assert result["generated_image"] == 999
        service.mock_rest_client.post.assert_called_once()
        mock_poll.assert_called_once_with(999, None)


@pytest.mark.anyio
async def test_edit_image(service):
    request = MagicMock()
    request.workspace_id = 1
    request.inputs.prompt = "Add hat"
    request.inputs.input_images = [123]
    request.config.model = "gemini-3.1-flash-image"
    request.config.aspect_ratio = "1:1"
    request.config.brand_guidelines = False

    service.mock_rest_client.post.return_value = Response(200, json={"id": 888})

    with (
        patch.object(
            service,
            "_normalize_asset_inputs",
            return_value=([{"media_item_id": 123}], []),
        ),
        patch.object(
            service,
            "_poll_job_status",
            AsyncMock(return_value=True),
        ) as mock_poll,
    ):
        result = await service.edit_image(request)
        assert result["edited_image"] == 888
        service.mock_rest_client.post.assert_called_once()
        mock_poll.assert_called_once_with(888, None)


@pytest.mark.anyio
async def test_generate_video(service):
    request = MagicMock()
    request.workspace_id = 1
    request.inputs.prompt = "A running dog"
    request.inputs.input_images = [123]
    request.inputs.start_frame = None
    request.inputs.end_frame = None
    request.config.model = "veo-3.1-generate-001"
    request.config.brand_guidelines = False

    service.mock_rest_client.post.return_value = Response(200, json={"id": 777})

    with patch.object(
        service,
        "_poll_job_status",
        AsyncMock(return_value=True),
    ) as mock_poll:
        result = await service.generate_video(request)
        assert result["generated_video"] == 777
        service.mock_rest_client.post.assert_called_once()
        mock_poll.assert_called_once_with(777, None)


@pytest.mark.anyio
async def test_virtual_try_on(service):
    request = MagicMock()
    request.workspace_id = 1
    request.inputs.model_image = 123
    request.inputs.top_image = None
    request.inputs.bottom_image = None
    request.inputs.dress_image = None
    request.inputs.shoes_image = None

    service.mock_rest_client.post.return_value = Response(200, json={"id": 666})

    with patch.object(
        service,
        "_poll_job_status",
        AsyncMock(return_value=True),
    ) as mock_poll:
        result = await service.virtual_try_on(request)
        assert result["generated_image"] == 666
        service.mock_rest_client.post.assert_called_once()
        mock_poll.assert_called_once_with(666, None)


@pytest.mark.anyio
async def test_generate_audio(service):
    request = MagicMock()
    request.workspace_id = 1
    request.inputs.prompt = "Birds chirping"
    request.config.model = "audio-generator"
    request.config.voice_name = "narrator"
    request.config.language_code = "en"
    request.config.negative_prompt = None
    request.config.seed = None

    service.mock_rest_client.post.return_value = Response(200, json={"id": 555})

    with patch.object(
        service,
        "_poll_job_status",
        AsyncMock(return_value=True),
    ) as mock_poll:
        result = await service.generate_audio(request)
        assert result["generated_audio"] == 555
        service.mock_rest_client.post.assert_called_once()
        mock_poll.assert_called_once_with(555, None)
