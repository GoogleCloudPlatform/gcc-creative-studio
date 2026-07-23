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
"""Tests for Gemini Service."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.images.dto.create_imagen_dto import CreateImagenDto
from src.multimodal.gemini_service import (
    GeminiService,
    PromptTargetEnum,
    ResponseMimeTypeEnum,
)


@pytest.fixture(name="gemini_service")
def fixture_gemini_service():
    with patch(
        "src.multimodal.gemini_service.GeminiModelSetup.init"
    ) as mock_init:
        mock_client = MagicMock()
        mock_init.return_value = mock_client
        service = GeminiService()
        service.client = mock_client
        return service


def test_generate_structured_prompt_json(gemini_service):
    mock_response = MagicMock()
    mock_response.text = '{"prompt": "enhanced prompt"}'
    # Return response when generate_content is called
    gemini_service.client.models.generate_content.return_value = mock_response

    res = gemini_service.generate_structured_prompt(
        original_prompt="test",
        target_type=PromptTargetEnum.IMAGE,
        prompt_template="enhance:",
    )

    assert res == '{"prompt": "enhanced prompt"}'
    gemini_service.client.models.generate_content.assert_called_once()


def test_generate_structured_prompt_text(gemini_service):
    mock_response = MagicMock()
    mock_response.text = "enhanced prompt"
    gemini_service.client.models.generate_content.return_value = mock_response

    res = gemini_service.generate_structured_prompt(
        original_prompt="test",
        target_type=PromptTargetEnum.IMAGE,
        prompt_template="enhance:",
        response_mime_type=ResponseMimeTypeEnum.TEXT,
    )

    assert res == "enhanced prompt"


def test_generate_random_or_rewrite_prompt(gemini_service):
    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.return_value = "random prompt"

        res = gemini_service.generate_random_or_rewrite_prompt(
            PromptTargetEnum.IMAGE
        )

        assert res == "random prompt"
        mock_gen.assert_called_once()


@pytest.mark.anyio
async def test_enhance_prompt_from_dto_success(gemini_service):
    dto = CreateImagenDto(
        prompt="test prompt",
        generation_model="gemini-3.1-flash-image",
        workspace_id=1,
    )

    # generate_structured_prompt is SYNC in the code (def, not async def)
    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.return_value = '{"prompt": "enhanced"}'

        # enhance_prompt_from_dto IS async!
        res = await gemini_service.enhance_prompt_from_dto(
            dto, PromptTargetEnum.IMAGE
        )

        assert res == '{"prompt": "enhanced"}'


def test_generate_text_success(gemini_service):
    mock_response = MagicMock()
    mock_response.text = "Plain text answer"
    gemini_service.client.models.generate_content.return_value = mock_response

    res = gemini_service.generate_text("Hello")

    assert res == "Plain text answer"


def test_extract_brand_info_from_pdf_success(gemini_service):
    mock_response = MagicMock()
    mock_response.text = '{"color_palette": ["#000"], "tone_of_voice_summary": "cool", "visual_style_summary": "sleek", "workspace_id": "123"}'
    gemini_service.client.models.generate_content.return_value = mock_response

    # extract_brand_info_from_pdf is sync
    res = gemini_service.extract_brand_info_from_pdf("gs://bucket/file.pdf")

    assert res["color_palette"] == ["#000"]


def test_aggregate_brand_info_success(gemini_service):
    partial = [
        {
            "color_palette": ["#000"],
            "tone_of_voice_summary": "cool",
            "visual_style_summary": "sleek",
            "workspace_id": "123",
            "name": "Brand X",
        },
    ]

    mock_response = MagicMock()
    mock_response.text = '{"color_palette": ["#000"], "tone_of_voice_summary": "cool", "visual_style_summary": "sleek", "workspace_id": "123"}'
    gemini_service.client.models.generate_content.return_value = mock_response

    # aggregate_brand_info is sync
    res = gemini_service.aggregate_brand_info(partial)

    assert res is not None
    assert res.color_palette == ["#000"]


@pytest.mark.anyio
async def test_enhance_prompt_from_dto_with_brand_guidelines(gemini_service):
    from src.images.dto.create_imagen_dto import CreateImagenDto

    dto = CreateImagenDto(
        prompt="test prompt",
        generation_model="gemini-3.1-flash-image",
        workspace_id=1,
        use_brand_guidelines=True,
    )

    gemini_service.brand_guideline_repo = AsyncMock()
    mock_data = MagicMock()
    mock_guideline = MagicMock()
    mock_guideline.visual_style_summary = "Visual summary"
    mock_guideline.tone_of_voice_summary = "Tone summary"
    mock_data.data = [mock_guideline]
    gemini_service.brand_guideline_repo.query.return_value = mock_data

    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.return_value = '{"prompt": "enhanced"}'

        res = await gemini_service.enhance_prompt_from_dto(
            dto, PromptTargetEnum.IMAGE
        )
        assert res == '{"prompt": "enhanced"}'
        gemini_service.brand_guideline_repo.query.assert_called_once()


def test_generate_text_failure(gemini_service):
    gemini_service.client.models.generate_content.side_effect = Exception(
        "API Error"
    )
    with pytest.raises(Exception):
        gemini_service.generate_text("Hello")


def test_extract_brand_info_from_pdf_failure(gemini_service):
    # Setting side_effect triggers the Exception catch block
    gemini_service.client.models.generate_content.side_effect = Exception(
        "API Error"
    )
    res = gemini_service.extract_brand_info_from_pdf("gs://bucket/file.pdf")
    assert res == {}


def test_aggregate_brand_info_empty(gemini_service):
    res = gemini_service.aggregate_brand_info([])
    assert res is None


def test_aggregate_brand_info_multiple_items(gemini_service):
    partial = [
        {"colorPalette": ["#FF0000"], "toneOfVoiceSummary": "cool"},
        {"colorPalette": ["#00FF00"], "visualStyleSummary": "sleek"},
    ]
    mock_response = MagicMock()
    mock_response.text = '{"color_palette": ["#FF0000", "#00FF00"], "tone_of_voice_summary": "combined cool", "visual_style_summary": "combined sleek", "name": "Brand X"}'
    gemini_service.client.models.generate_content.return_value = mock_response

    res = gemini_service.aggregate_brand_info(partial)
    assert res is not None
    assert "#FF0000" in res.color_palette
    assert "#00FF00" in res.color_palette


@pytest.mark.anyio
async def test_generate_multimodal_success(gemini_service):
    from src.multimodal.dto.multimodal_generation_request_dto import (
        MultimodalGenerationRequestDto,
    )

    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Describe the image.",
        media_item_ids=[1],
        source_asset_ids=[2],
        model="gemini-3.5-flash",
    )

    gemini_service.media_item_repo = AsyncMock()
    mock_media = MagicMock()
    mock_media.workspace_id = 1
    mock_media.gcs_uris = ["gs://bucket/media.png"]
    del mock_media.gcs_uri
    mock_media.mime_type = "image/png"
    gemini_service.media_item_repo.get_by_id.return_value = mock_media

    gemini_service.source_asset_repo = AsyncMock()
    mock_asset = MagicMock()
    mock_asset.workspace_id = 1
    mock_asset.gcs_uri = "gs://bucket/asset.png"
    mock_asset.mime_type = "image/png"
    gemini_service.source_asset_repo.get_by_id.return_value = mock_asset

    gemini_service.client.aio.models.generate_content = AsyncMock()
    mock_response = MagicMock()
    mock_response.text = "This is a great image."
    gemini_service.client.aio.models.generate_content.return_value = (
        mock_response
    )

    res = await gemini_service.generate_multimodal(request)

    assert res == "This is a great image."
    gemini_service.media_item_repo.get_by_id.assert_called_once_with(1)
    gemini_service.source_asset_repo.get_by_id.assert_called_once_with(2)
    gemini_service.client.aio.models.generate_content.assert_called_once()


@pytest.mark.anyio
async def test_generate_multimodal_failure(gemini_service):
    from src.multimodal.dto.multimodal_generation_request_dto import (
        MultimodalGenerationRequestDto,
    )

    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Describe the image.",
        model="gemini-3.5-flash",
    )

    gemini_service.client.aio.models.generate_content = AsyncMock()
    gemini_service.client.aio.models.generate_content.side_effect = Exception(
        "API Error"
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await gemini_service.generate_multimodal(request)
    assert exc_info.value.status_code == 500


@pytest.mark.anyio
async def test_generate_multimodal_workspace_mismatch_media_item(
    gemini_service,
):
    from src.multimodal.dto.multimodal_generation_request_dto import (
        MultimodalGenerationRequestDto,
    )

    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Describe the image.",
        media_item_ids=[1],
        model="gemini-3.5-flash",
    )

    gemini_service.media_item_repo = AsyncMock()
    mock_media = MagicMock()
    mock_media.workspace_id = 2  # Different workspace
    gemini_service.media_item_repo.get_by_id.return_value = mock_media

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await gemini_service.generate_multimodal(request)
    assert exc_info.value.status_code == 403
    assert (
        "Media item 1 does not belong to workspace 1" in exc_info.value.detail
    )


@pytest.mark.anyio
async def test_generate_multimodal_workspace_mismatch_source_asset(
    gemini_service,
):
    from src.multimodal.dto.multimodal_generation_request_dto import (
        MultimodalGenerationRequestDto,
    )

    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Describe the image.",
        source_asset_ids=[2],
        model="gemini-3.5-flash",
    )

    gemini_service.source_asset_repo = AsyncMock()
    mock_asset = MagicMock()
    mock_asset.workspace_id = 2  # Different workspace
    gemini_service.source_asset_repo.get_by_id.return_value = mock_asset

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await gemini_service.generate_multimodal(request)
    assert exc_info.value.status_code == 403
    assert "Asset 2 does not belong to workspace 1" in exc_info.value.detail


@pytest.mark.anyio
async def test_generate_multimodal_with_config(gemini_service):
    from src.multimodal.dto.multimodal_generation_request_dto import (
        MultimodalGenerationRequestDto,
    )

    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Describe the image.",
        model="gemini-3.5-flash",
        config={
            "temperature": 0.7,
            "max_output_tokens": 150,
            "system_instruction": "Be concise",
        },
    )

    gemini_service.client.aio.models.generate_content = AsyncMock()
    mock_response = MagicMock()
    mock_response.text = "Configured response"
    gemini_service.client.aio.models.generate_content.return_value = (
        mock_response
    )

    res = await gemini_service.generate_multimodal(request)

    assert res == "Configured response"
    gemini_service.client.aio.models.generate_content.assert_called_once()
    called_args, called_kwargs = (
        gemini_service.client.aio.models.generate_content.call_args
    )
    assert "config" in called_kwargs
    config_obj = called_kwargs["config"]
    assert config_obj.temperature == 0.7
    assert config_obj.max_output_tokens == 150
    assert config_obj.system_instruction == "Be concise"


# --- Additional adversarial and edge case tests ---

from src.multimodal.rewriters import (
    RANDOM_IMAGE_PROMPT_TEMPLATE,
    RANDOM_VIDEO_PROMPT_TEMPLATE,
    REWRITE_IMAGE_TEXT_PROMPT_TEMPLATE,
    REWRITE_VIDEO_TEXT_PROMPT_TEMPLATE,
)


@pytest.mark.anyio
async def test_enhance_prompt_from_dto_invalid_target_type(gemini_service):
    dto = CreateImagenDto(
        prompt="test prompt",
        generation_model="gemini-3.1-flash-image-preview",
        workspace_id=1,
    )
    with pytest.raises(ValueError) as exc_info:
        await gemini_service.enhance_prompt_from_dto(dto, "INVALID_TARGET")
    assert "Invalid target_type" in str(exc_info.value)


@pytest.mark.anyio
async def test_enhance_prompt_from_dto_gemini_i2i(gemini_service):
    dto = CreateImagenDto(
        prompt="change shirt to blue",
        generation_model="gemini-3.1-flash-image-preview",
        workspace_id=1,
        source_asset_ids=[123],
    )
    res = await gemini_service.enhance_prompt_from_dto(
        dto, PromptTargetEnum.IMAGE
    )
    assert "**Objective:** Perform a targeted edit" in res
    assert "change shirt to blue" in res


@pytest.mark.anyio
async def test_enhance_prompt_from_dto_no_brand_guidelines(gemini_service):
    dto = CreateImagenDto(
        prompt="test prompt",
        generation_model="gemini-3.1-flash-image-preview",
        workspace_id=1,
        use_brand_guidelines=True,
    )
    gemini_service.brand_guideline_repo = AsyncMock()
    mock_response = MagicMock()
    mock_response.data = []
    gemini_service.brand_guideline_repo.query.return_value = mock_response

    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.return_value = (
            '{"prompt": "enhanced without brand guidelines"}'
        )
        res = await gemini_service.enhance_prompt_from_dto(
            dto, PromptTargetEnum.IMAGE
        )
        assert res == '{"prompt": "enhanced without brand guidelines"}'
        assert dto.prompt == "test prompt"


def test_get_response_schema_video(gemini_service):
    schema = gemini_service._get_response_schema(PromptTargetEnum.VIDEO)
    assert schema is not None


def test_get_response_schema_invalid_target(gemini_service):
    with pytest.raises(ValueError) as exc_info:
        gemini_service._get_response_schema("INVALID_TARGET")
    assert "No response schema defined for target" in str(exc_info.value)


def test_generate_structured_prompt_invalid_mime_type(gemini_service):
    res = gemini_service.generate_structured_prompt(
        original_prompt="test",
        target_type=PromptTargetEnum.IMAGE,
        prompt_template="enhance:",
        response_mime_type=MagicMock(value="invalid/mime"),
    )
    assert res == ""


def test_generate_structured_prompt_failure(gemini_service):
    gemini_service.client.models.generate_content.side_effect = Exception(
        "API error"
    )
    with pytest.raises(Exception) as exc_info:
        gemini_service.generate_structured_prompt(
            original_prompt="test",
            target_type=PromptTargetEnum.IMAGE,
            prompt_template="enhance:",
        )
    assert "API error" in str(exc_info.value)


def test_generate_random_or_rewrite_prompt_with_original_prompt_image(
    gemini_service,
):
    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.return_value = "rewritten image prompt"
        res = gemini_service.generate_random_or_rewrite_prompt(
            PromptTargetEnum.IMAGE, original_prompt="rewrite this image prompt"
        )
        assert res == "rewritten image prompt"
        mock_gen.assert_called_once_with(
            original_prompt="rewrite this image prompt",
            target_type=PromptTargetEnum.IMAGE,
            prompt_template=REWRITE_IMAGE_TEXT_PROMPT_TEMPLATE,
            response_mime_type=ResponseMimeTypeEnum.TEXT,
        )


def test_generate_random_or_rewrite_prompt_with_original_prompt_video(
    gemini_service,
):
    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.return_value = "rewritten video prompt"
        res = gemini_service.generate_random_or_rewrite_prompt(
            PromptTargetEnum.VIDEO, original_prompt="rewrite this video prompt"
        )
        assert res == "rewritten video prompt"
        mock_gen.assert_called_once_with(
            original_prompt="rewrite this video prompt",
            target_type=PromptTargetEnum.VIDEO,
            prompt_template=REWRITE_VIDEO_TEXT_PROMPT_TEMPLATE,
            response_mime_type=ResponseMimeTypeEnum.TEXT,
        )


def test_generate_random_or_rewrite_prompt_failure(gemini_service):
    with patch.object(gemini_service, "generate_structured_prompt") as mock_gen:
        mock_gen.side_effect = Exception("Rewriter error")
        with pytest.raises(Exception) as exc_info:
            gemini_service.generate_random_or_rewrite_prompt(
                PromptTargetEnum.IMAGE
            )
        assert "Rewriter error" in str(exc_info.value)


def test_generate_title_and_summary_success(gemini_service):
    mock_response = MagicMock()
    mock_response.text = (
        '{"title": "Conversation Title", "summary": "Conversation Summary"}'
    )
    gemini_service.client.models.generate_content.return_value = mock_response

    res = gemini_service.generate_title_and_summary(
        "Hello conversation starter"
    )
    assert res == {
        "title": "Conversation Title",
        "summary": "Conversation Summary",
    }
    gemini_service.client.models.generate_content.assert_called_once()


def test_generate_title_and_summary_failure(gemini_service):
    gemini_service.client.models.generate_content.side_effect = Exception(
        "Gemini failure"
    )
    with pytest.raises(Exception) as exc_info:
        gemini_service.generate_title_and_summary("Hello conversation starter")
    assert "Gemini failure" in str(exc_info.value)


def test_generate_media_metadata_success_no_uri(gemini_service):
    mock_response = MagicMock()
    mock_response.text = '{"items": [{"title": "Media Title", "description": "Media Description"}]}'
    gemini_service.client.models.generate_content.return_value = mock_response

    res = gemini_service.generate_media_metadata(
        prompt="Describe this asset",
        media_uris=None,
        model_name="gemini-3.5-flash",
    )
    assert res == {
        "titles": ["Media Title"],
        "descriptions": ["Media Description"],
    }
    gemini_service.client.models.generate_content.assert_called_once()
    called_kwargs = gemini_service.client.models.generate_content.call_args[1]
    assert called_kwargs["contents"] == [
        "Describe this asset\nGenerate a title and description for EACH of the 0 media items provided, in exact sequential order."
    ]


def test_generate_media_metadata_success_with_uri(gemini_service):
    mock_response = MagicMock()
    mock_response.text = '{"items": [{"title": "Media Title with URI", "description": "Media Description with URI"}]}'
    gemini_service.client.models.generate_content.return_value = mock_response

    with patch(
        "src.multimodal.gemini_service.types.Part.from_uri"
    ) as mock_from_uri:
        mock_part = MagicMock()
        mock_from_uri.return_value = mock_part

        res = gemini_service.generate_media_metadata(
            prompt="Describe this asset",
            media_uris="gs://bucket/image.png",
            model_name="gemini-3.5-flash",
        )
        assert res == {
            "titles": ["Media Title with URI"],
            "descriptions": ["Media Description with URI"],
        }
        mock_from_uri.assert_called_once_with(
            file_uri="gs://bucket/image.png", mime_type="image/png"
        )
        called_kwargs = gemini_service.client.models.generate_content.call_args[
            1
        ]
        assert called_kwargs["contents"] == [
            mock_part,
            "Describe this asset\nGenerate a title and description for EACH of the 1 media items provided, in exact sequential order.",
        ]


def test_generate_media_metadata_uri_exception(gemini_service):
    mock_response = MagicMock()
    mock_response.text = '{"items": [{"title": "Media Title Fallback", "description": "Media Description Fallback"}]}'
    gemini_service.client.models.generate_content.return_value = mock_response

    with patch(
        "src.multimodal.gemini_service.types.Part.from_uri"
    ) as mock_from_uri:
        mock_from_uri.side_effect = Exception("Invalid GCS path")

        res = gemini_service.generate_media_metadata(
            prompt="Describe this asset",
            media_uris="invalid_uri",
            model_name="gemini-3.5-flash",
        )
        assert res == {
            "titles": ["Media Title Fallback"],
            "descriptions": ["Media Description Fallback"],
        }
        mock_from_uri.assert_called_once_with(
            file_uri="invalid_uri", mime_type="image/png"
        )
        called_kwargs = gemini_service.client.models.generate_content.call_args[
            1
        ]
        assert called_kwargs["contents"] == [
            "Describe this asset\nGenerate a title and description for EACH of the 1 media items provided, in exact sequential order."
        ]


def test_generate_media_metadata_gemini_failure(gemini_service):
    gemini_service.client.models.generate_content.side_effect = Exception(
        "API error"
    )
    with pytest.raises(Exception) as exc_info:
        gemini_service.generate_media_metadata(
            prompt="Describe this asset",
            media_uris=None,
            model_name="gemini-3.5-flash",
        )
    assert "API error" in str(exc_info.value)


def test_aggregate_brand_info_gemini_failure(gemini_service):
    partial = [
        {
            "colorPalette": ["#000"],
            "toneOfVoiceSummary": "cool",
            "name": "Brand X",
        },
        {
            "colorPalette": ["#FFF"],
            "visualStyleSummary": "sleek",
            "name": "Brand Y",
        },
    ]
    gemini_service.client.models.generate_content.side_effect = Exception(
        "Consolidation failed"
    )

    res = gemini_service.aggregate_brand_info(partial)
    assert res is None


@pytest.mark.anyio
async def test_generate_multimodal_http_exception_propagation(gemini_service):
    from src.multimodal.dto.multimodal_generation_request_dto import (
        MultimodalGenerationRequestDto,
    )
    from fastapi import HTTPException

    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Describe the image.",
        model="gemini-3.5-flash",
    )

    gemini_service.client.aio.models.generate_content = AsyncMock()
    gemini_service.client.aio.models.generate_content.side_effect = (
        HTTPException(status_code=400, detail="Propagated bad request")
    )

    with pytest.raises(HTTPException) as exc_info:
        await gemini_service.generate_multimodal(request)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Propagated bad request"
