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
