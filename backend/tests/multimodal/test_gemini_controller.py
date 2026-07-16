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

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from src.multimodal.dto.gemini_prompt_enhancer_dto import (
    GenerateTitleRequestDto,
    GenerateTitleResponseDto,
    RandomPromptRequestDto,
    RewritePromptRequestDto,
    RewrittenOrRandomPromptResponse,
)
from src.multimodal.dto.multimodal_generation_request_dto import (
    MultimodalGenerationRequestDto,
    MultimodalGenerationResponseDto,
)
from src.multimodal.gemini_service import GeminiService, PromptTargetEnum
from src.multimodal.gemini_controller import (
    generate_multimodal_endpoint,
    rewrite_prompt_endpoint,
    random_prompt_endpoint,
    generate_title_endpoint,
)


@pytest.fixture
def mock_gemini_service():
    service = AsyncMock(spec=GeminiService)
    return service


@pytest.mark.anyio
async def test_generate_multimodal_endpoint_success(mock_gemini_service):
    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Test prompt",
        model="gemini-3.5-flash",
    )
    mock_gemini_service.generate_multimodal.return_value = (
        "Generated text response"
    )
    mock_workspace_auth = AsyncMock()
    mock_user = MagicMock()

    response = await generate_multimodal_endpoint(
        request=request,
        gemini_service=mock_gemini_service,
        current_user=mock_user,
        workspace_auth=mock_workspace_auth,
    )

    assert isinstance(response, MultimodalGenerationResponseDto)
    assert response.text == "Generated text response"
    mock_gemini_service.generate_multimodal.assert_called_once_with(request)
    mock_workspace_auth.authorize.assert_called_once_with(
        workspace_id=1, user=mock_user
    )


@pytest.mark.anyio
async def test_generate_multimodal_endpoint_failure(mock_gemini_service):
    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Test prompt",
    )
    mock_gemini_service.generate_multimodal.side_effect = Exception(
        "Service error"
    )
    mock_workspace_auth = AsyncMock()
    mock_user = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await generate_multimodal_endpoint(
            request=request,
            gemini_service=mock_gemini_service,
            current_user=mock_user,
            workspace_auth=mock_workspace_auth,
        )

    assert exc_info.value.status_code == 500
    assert "Failed to generate multimodal content" in exc_info.value.detail
    mock_workspace_auth.authorize.assert_called_once_with(
        workspace_id=1, user=mock_user
    )


@pytest.mark.anyio
async def test_rewrite_prompt_endpoint_success(mock_gemini_service):
    request = RewritePromptRequestDto(
        user_prompt="test prompt",
        target_type=PromptTargetEnum.IMAGE,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.return_value = (
        "rewritten prompt"
    )

    response = await rewrite_prompt_endpoint(
        rewrite_request=request, gemini_service=mock_gemini_service
    )

    assert isinstance(response, RewrittenOrRandomPromptResponse)
    assert response.prompt == "rewritten prompt"
    mock_gemini_service.generate_random_or_rewrite_prompt.assert_called_once_with(
        PromptTargetEnum.IMAGE, "test prompt"
    )


@pytest.mark.anyio
async def test_random_prompt_endpoint_success(mock_gemini_service):
    request = RandomPromptRequestDto(
        target_type=PromptTargetEnum.VIDEO,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.return_value = (
        "random prompt"
    )

    response = await random_prompt_endpoint(
        random_request=request, gemini_service=mock_gemini_service
    )

    assert isinstance(response, RewrittenOrRandomPromptResponse)
    assert response.prompt == "random prompt"
    mock_gemini_service.generate_random_or_rewrite_prompt.assert_called_once_with(
        PromptTargetEnum.VIDEO,
    )


@pytest.mark.anyio
async def test_generate_title_endpoint_success(mock_gemini_service):
    request = GenerateTitleRequestDto(
        text="test conversation text",
    )
    mock_gemini_service.generate_title_and_summary.return_value = {
        "title": "A Title",
        "summary": "A Summary",
    }

    response = await generate_title_endpoint(
        request=request, gemini_service=mock_gemini_service
    )

    assert isinstance(response, GenerateTitleResponseDto)
    assert response.title == "A Title"
    assert response.summary == "A Summary"
    mock_gemini_service.generate_title_and_summary.assert_called_once_with(
        "test conversation text"
    )


# --- Additional exception handling and boundary tests ---


@pytest.mark.anyio
async def test_rewrite_prompt_endpoint_failure(mock_gemini_service):
    request = RewritePromptRequestDto(
        user_prompt="test prompt",
        target_type=PromptTargetEnum.IMAGE,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.side_effect = (
        Exception("Rewriting failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        await rewrite_prompt_endpoint(
            rewrite_request=request, gemini_service=mock_gemini_service
        )
    assert exc_info.value.status_code == 500
    assert (
        "An unexpected error occurred during prompt rewriting"
        in exc_info.value.detail
    )


@pytest.mark.anyio
async def test_random_prompt_endpoint_failure(mock_gemini_service):
    request = RandomPromptRequestDto(
        target_type=PromptTargetEnum.VIDEO,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.side_effect = (
        Exception("Random generation failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        await random_prompt_endpoint(
            random_request=request, gemini_service=mock_gemini_service
        )
    assert exc_info.value.status_code == 500
    assert "Failed to generate random prompt" in exc_info.value.detail


@pytest.mark.anyio
async def test_generate_title_endpoint_failure(mock_gemini_service):
    request = GenerateTitleRequestDto(
        text="test conversation text",
    )
    mock_gemini_service.generate_title_and_summary.side_effect = Exception(
        "Title generation failed"
    )

    with pytest.raises(HTTPException) as exc_info:
        await generate_title_endpoint(
            request=request, gemini_service=mock_gemini_service
        )
    assert exc_info.value.status_code == 500
    assert "Failed to generate title and summary" in exc_info.value.detail


@pytest.mark.anyio
async def test_generate_multimodal_endpoint_http_exception_propagation(
    mock_gemini_service,
):
    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Test prompt",
        model="gemini-3.5-flash",
    )
    mock_workspace_auth = AsyncMock()
    mock_user = MagicMock()

    mock_workspace_auth.authorize.side_effect = HTTPException(
        status_code=403, detail="Workspace access denied"
    )

    with pytest.raises(HTTPException) as exc_info:
        await generate_multimodal_endpoint(
            request=request,
            gemini_service=mock_gemini_service,
            current_user=mock_user,
            workspace_auth=mock_workspace_auth,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace access denied"
