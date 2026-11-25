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
    mock_gemini_service.generate_multimodal.assert_called_once_with(
        request, current_user=mock_user
    )
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
    assert "Service error" not in exc_info.value.detail
    mock_workspace_auth.authorize.assert_called_once_with(
        workspace_id=1, user=mock_user
    )


def test_rewrite_prompt_endpoint_success(mock_gemini_service):
    request = RewritePromptRequestDto(
        user_prompt="jazz",
        target_type=PromptTargetEnum.AUDIO,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.return_value = (
        "rewritten audio prompt"
    )

    response = rewrite_prompt_endpoint(
        rewrite_request=request, gemini_service=mock_gemini_service
    )

    assert isinstance(response, RewrittenOrRandomPromptResponse)
    assert response.prompt == "rewritten audio prompt"
    mock_gemini_service.generate_random_or_rewrite_prompt.assert_called_once_with(
        PromptTargetEnum.AUDIO, "jazz"
    )


def test_random_prompt_endpoint_success(mock_gemini_service):
    request = RandomPromptRequestDto(
        target_type=PromptTargetEnum.VIDEO,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.return_value = (
        "random prompt"
    )

    response = random_prompt_endpoint(
        random_request=request, gemini_service=mock_gemini_service
    )

    assert isinstance(response, RewrittenOrRandomPromptResponse)
    assert response.prompt == "random prompt"
    mock_gemini_service.generate_random_or_rewrite_prompt.assert_called_once_with(
        PromptTargetEnum.VIDEO
    )


def test_generate_title_endpoint_success(mock_gemini_service):
    request = GenerateTitleRequestDto(
        text="test conversation text",
    )
    mock_gemini_service.generate_title_and_summary.return_value = {
        "title": "A Title",
        "summary": "A Summary",
    }

    response = generate_title_endpoint(
        request=request, gemini_service=mock_gemini_service
    )

    assert isinstance(response, GenerateTitleResponseDto)
    assert response.title == "A Title"
    assert response.summary == "A Summary"
    mock_gemini_service.generate_title_and_summary.assert_called_once_with(
        "test conversation text"
    )


# --- Additional exception handling and boundary tests ---


def test_rewrite_prompt_endpoint_failure(mock_gemini_service):
    request = RewritePromptRequestDto(
        user_prompt="test prompt",
        target_type=PromptTargetEnum.IMAGE,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.side_effect = (
        Exception("Rewriting failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        rewrite_prompt_endpoint(
            rewrite_request=request, gemini_service=mock_gemini_service
        )
    assert exc_info.value.status_code == 500
    assert (
        "An unexpected error occurred during prompt rewriting"
        in exc_info.value.detail
    )


def test_random_prompt_endpoint_failure(mock_gemini_service):
    request = RandomPromptRequestDto(
        target_type=PromptTargetEnum.VIDEO,
    )
    mock_gemini_service.generate_random_or_rewrite_prompt.side_effect = (
        Exception("Random generation failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        random_prompt_endpoint(
            random_request=request, gemini_service=mock_gemini_service
        )
    assert exc_info.value.status_code == 500
    assert "Failed to generate random prompt" in exc_info.value.detail


def test_generate_title_endpoint_failure(mock_gemini_service):
    request = GenerateTitleRequestDto(
        text="test conversation text",
    )
    mock_gemini_service.generate_title_and_summary.side_effect = Exception(
        "Title generation failed"
    )

    with pytest.raises(HTTPException) as exc_info:
        generate_title_endpoint(
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


def test_gemini_sync_endpoints_via_testclient_threadpool_and_di():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.auth.auth_guard import get_current_user
    from src.database import get_db
    from src.multimodal.gemini_controller import router
    from src.users.user_model import UserModel

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: UserModel(
        id=1, email="u@example.com", name="User", roles=["user"]
    )

    def _forbid_db():
        raise AssertionError(
            "Stateless Gemini endpoints must not open a DB session"
        )

    app.dependency_overrides[get_db] = _forbid_db

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        MagicMock(text="Enhanced jazz prompt"),
        MagicMock(text="Random video prompt"),
        MagicMock(text='{"title": "Short Title", "summary": "Short summary"}'),
    ]

    with patch(
        "src.multimodal.gemini_service.GeminiModelSetup.init",
        return_value=fake_client,
    ):
        client = TestClient(app)

        r1 = client.post(
            "/api/gemini/rewrite-prompt",
            json={"targetType": "audio", "userPrompt": "warm jazz"},
        )
        assert r1.status_code == 200
        assert r1.json() == {"prompt": "Enhanced jazz prompt"}

        r2 = client.post(
            "/api/gemini/random-prompt",
            json={"targetType": "video"},
        )
        assert r2.status_code == 200
        assert r2.json() == {"prompt": "Random video prompt"}

        r3 = client.post(
            "/api/gemini/generate-title",
            json={"text": "Hello world"},
        )
        assert r3.status_code == 200
        assert r3.json() == {
            "title": "Short Title",
            "summary": "Short summary",
        }


def test_rewrite_and_title_endpoints_reject_oversized_payloads_and_sanitize_500_errors():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.auth.auth_guard import get_current_user
    from src.multimodal.gemini_controller import router
    from src.users.user_model import UserModel

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: UserModel(
        id=1, email="u@example.com", name="User", roles=["user"]
    )

    failing_service = MagicMock(spec=GeminiService)
    failing_service.generate_random_or_rewrite_prompt.side_effect = (
        RuntimeError("gs://internal-secret-bucket/sdk-trace")
    )
    failing_service.generate_title_and_summary.side_effect = RuntimeError(
        "gs://internal-secret-bucket/title-trace"
    )
    app.dependency_overrides[GeminiService.create_stateless] = (
        lambda: failing_service
    )

    client = TestClient(app)

    too_long = "x" * 10001
    assert (
        client.post(
            "/api/gemini/rewrite-prompt",
            json={"targetType": "audio", "userPrompt": too_long},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/gemini/generate-title",
            json={"text": too_long},
        ).status_code
        == 422
    )

    err_rewrite = client.post(
        "/api/gemini/rewrite-prompt",
        json={"targetType": "audio", "userPrompt": "short prompt"},
    )
    assert err_rewrite.status_code == 500
    assert "internal-secret-bucket" not in err_rewrite.json()["detail"]

    err_title = client.post(
        "/api/gemini/generate-title",
        json={"text": "short text"},
    )
    assert err_title.status_code == 500
    assert "internal-secret-bucket" not in err_title.json()["detail"]


@pytest.mark.anyio
async def test_generate_multimodal_endpoint_service_403_propagation(
    mock_gemini_service,
):
    request = MultimodalGenerationRequestDto(
        workspace_id=1,
        prompt="Test prompt",
        media_item_ids=[99],
        model="gemini-3.5-flash",
    )
    mock_workspace_auth = AsyncMock()
    mock_user = MagicMock()
    mock_gemini_service.generate_multimodal.side_effect = HTTPException(
        status_code=403, detail="Cannot access foreign personal workspace"
    )

    with pytest.raises(HTTPException) as exc_info:
        await generate_multimodal_endpoint(
            request=request,
            gemini_service=mock_gemini_service,
            current_user=mock_user,
            workspace_auth=mock_workspace_auth,
        )
    assert exc_info.value.status_code == 403
    mock_gemini_service.generate_multimodal.assert_called_once_with(
        request, current_user=mock_user
    )
