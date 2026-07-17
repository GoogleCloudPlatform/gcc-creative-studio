# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may
# obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.auth_guard import RoleChecker, get_current_user
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
from src.multimodal.gemini_service import GeminiService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth

router = APIRouter(
    prefix="/api/gemini",
    tags=["Gemini APIs"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[
                    UserRoleEnum.ADMIN,
                    UserRoleEnum.USER,
                    UserRoleEnum.CREATOR,
                ],
            ),
        ),
    ],
)


@router.post(
    "/rewrite-prompt",
    response_model=RewrittenOrRandomPromptResponse,
    summary="Rewrite and enhance a prompt for image generation",
)
async def rewrite_prompt_endpoint(
    rewrite_request: RewritePromptRequestDto,
    gemini_service: GeminiService = Depends(),
):
    """Takes a set of image generation parameters and combines them into a single,
    high-quality, natural language prompt suitable for an image model.
    This uses a deterministic, rule-based approach.
    """
    try:
        rewritten_prompt = gemini_service.generate_random_or_rewrite_prompt(
            rewrite_request.target_type,
            rewrite_request.user_prompt,
        )
        return RewrittenOrRandomPromptResponse(prompt=rewritten_prompt)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during prompt rewriting: {e}",
        )


@router.post(
    "/random-prompt",
    response_model=RewrittenOrRandomPromptResponse,
    summary="Generate a random, creative prompt for image creation",
)
async def random_prompt_endpoint(
    random_request: RandomPromptRequestDto,
    gemini_service: GeminiService = Depends(),
):
    """Generates a completely new, random, and visually descriptive prompt using Gemini.
    Useful for sparking creativity or for a "surprise me" feature.
    """
    try:
        random_prompt = gemini_service.generate_random_or_rewrite_prompt(
            random_request.target_type,
        )
        return RewrittenOrRandomPromptResponse(prompt=random_prompt)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate random prompt from Gemini: {e}",
        )


@router.post(
    "/generate-title",
    response_model=GenerateTitleResponseDto,
    summary="Generate a short title and summary for a text message",
)
async def generate_title_endpoint(
    request: GenerateTitleRequestDto,
    gemini_service: GeminiService = Depends(),
):
    """Generates a short, concise title (max 5 words) and a longer summary for the provided text."""
    try:
        data = gemini_service.generate_title_and_summary(request.text)
        return GenerateTitleResponseDto(**data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate title and summary from Gemini: {e}",
        )


@router.post(
    "/multimodal-generation",
    response_model=MultimodalGenerationResponseDto,
    summary="Generate multimodal text response based on prompt and media",
)
async def generate_multimodal_endpoint(
    request: MultimodalGenerationRequestDto,
    gemini_service: GeminiService = Depends(),
    current_user: UserModel = Depends(get_current_user),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Combines a text prompt with media items and/or source assets to generate a text response."""
    try:
        await workspace_auth.authorize(
            workspace_id=request.workspace_id,
            user=current_user,
        )
        response_text = await gemini_service.generate_multimodal(request)
        return MultimodalGenerationResponseDto(text=response_text)
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate multimodal content: {e}",
        )
