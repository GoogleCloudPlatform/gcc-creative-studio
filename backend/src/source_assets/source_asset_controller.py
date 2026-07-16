# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Controller for handling source asset API requests."""

import asyncio

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from src.auth.auth_guard import RoleChecker, get_current_user
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.source_assets.dto.finalize_upload_dto import (
    FinalizeSourceAssetUploadDto,
)
from src.source_assets.dto.generate_upload_url_dto import (
    GenerateSourceAssetUploadUrlDto,
    GenerateSourceAssetUploadUrlResponseDto,
)
from src.source_assets.dto.source_asset_response_dto import (
    SourceAssetResponseDto,
)
from src.source_assets.dto.source_asset_search_dto import SourceAssetSearchDto
from src.source_assets.dto.vto_assets_response_dto import VtoAssetsResponseDto
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
)
from src.source_assets.source_asset_service import SourceAssetService
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth

MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB

ALLOWED_MIME_TYPES = {
    MimeTypeEnum.IMAGE_PNG.value,
    MimeTypeEnum.IMAGE_JPEG.value,
    "image/jpg",
    MimeTypeEnum.IMAGE_WEBP.value,
    MimeTypeEnum.VIDEO_MP4.value,
    MimeTypeEnum.AUDIO_WAV.value,
    MimeTypeEnum.AUDIO_MPEG.value,
    MimeTypeEnum.AUDIO_MP3.value,
    MimeTypeEnum.AUDIO_OGG.value,
    MimeTypeEnum.AUDIO_WEBM.value,
}

router = APIRouter(
    prefix="/api/source_assets",
    tags=["User Assets"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(allowed_roles=[UserRoleEnum.USER, UserRoleEnum.ADMIN])
        ),
    ],
)


@router.post(
    "/generate-upload-url",
    response_model=GenerateSourceAssetUploadUrlResponseDto,
    summary="Get a Signed URL for Direct Source Asset Upload",
)
async def generate_source_asset_upload_url(
    request_dto: GenerateSourceAssetUploadUrlDto,
    current_user: UserModel = Depends(get_current_user),
    service: SourceAssetService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Generates a secure, short-lived signed URL to upload a source asset directly to GCS.

    Uses same strategy as: backend/src/brand_guidelines/brand_guideline_controller.py
    """
    await workspace_auth.authorize(
        workspace_id=request_dto.workspace_id,
        user=current_user,
    )

    if request_dto.size > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File is too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
        )

    content_type = request_dto.content_type.split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format.",
        )

    return await service.generate_signed_upload_url(
        request_dto=request_dto,
        current_user=current_user,
    )


@router.post(
    "/finalize-upload",
    response_model=SourceAssetResponseDto,
    status_code=status.HTTP_201_CREATED,
    summary="Finalize Direct Source Asset Upload",
)
async def finalize_source_asset_upload(
    request_dto: FinalizeSourceAssetUploadDto,
    current_user: UserModel = Depends(get_current_user),
    service: SourceAssetService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Finalizes registration of a source asset in the database after direct GCS upload."""
    await workspace_auth.authorize(
        workspace_id=request_dto.workspace_id,
        user=current_user,
    )

    return await service.finalize_direct_upload(
        request_dto=request_dto,
        current_user=current_user,
    )


@router.post("/upload", response_model=SourceAssetResponseDto)
async def upload_source_asset(
    file: UploadFile = File(),
    workspace_id: int = Form(..., alias="workspaceId"),
    scope: AssetScopeEnum | None = Form(None),
    asset_type: AssetTypeEnum | None = Form(None, alias="assetType"),
    aspect_ratio: AspectRatioEnum | None = Form(None, alias="aspectRatio"),
    upscale_factor: str | None = Form(None, alias="upscaleFactor"),
    metadata_generation_model: GenerationModelEnum | str | None = Form(
        GenerationModelEnum.GEMINI_3_5_FLASH
    ),
    title: str | None = Form(None),
    description: str | None = Form(None),
    current_user: UserModel = Depends(get_current_user),
    service: SourceAssetService = Depends(SourceAssetService),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Uploads a new source asset. Handles de-duplication and upscaling.
    Accepts multipart/form-data.

    - **scope**: (Admin only) Set the asset's scope. Defaults to 'private'.
    - **workspace_id**: The ID of the workspace to upload the asset to.
    - **assetType**: Set the asset's type. Defaults to 'generic_image'.
    """
    # Use our centralized dependency to authorize the user for the workspace
    # before proceeding with the upload.
    await workspace_auth.authorize(
        workspace_id=workspace_id,
        user=current_user,
    )

    contents = await file.read()
    return await service.upload_asset(
        user=current_user,
        file_bytes=contents,
        filename=file.filename,
        mime_type=file.content_type,
        scope=scope,
        workspace_id=workspace_id,
        asset_type=asset_type,
        aspect_ratio=aspect_ratio,
        upscale_factor=upscale_factor,
        metadata_generation_model=metadata_generation_model,
        title=title,
        description=description,
    )


@router.post("/convert-to-png", response_class=Response)
async def convert_image_to_png(
    file: UploadFile = File(),
    # Keep auth dependencies to protect the endpoint
    current_user: UserModel = Depends(
        get_current_user
    ),  # pylint: disable=unused-argument
    service: SourceAssetService = Depends(),
):
    """Accepts any image file, converts it to PNG, and returns the binary data.
    Used for pre-processing unsupported formats before cropping on the frontend.
    """
    png_contents = await service.convert_to_png(file=file)
    return Response(content=png_contents, media_type="image/png")


@router.post(
    "/search", response_model=PaginationResponseDto[SourceAssetResponseDto]
)
async def list_source_assets(
    search_dto: SourceAssetSearchDto,
    current_user: UserModel = Depends(get_current_user),
    service: SourceAssetService = Depends(),
    user_repo: UserRepository = Depends(),
):
    """Performs a paginated search for user assets with role-based access control.
    - Regular users can only search their own assets.
    - Admins can search all assets, or filter by a specific user's email.
    """
    target_user_id: int | None = None

    is_admin = UserRoleEnum.ADMIN in current_user.roles

    if not is_admin:
        # For regular users, force the search to their own ID.
        target_user_id = current_user.id
        # Clear any admin-only filters that might have been sent
        search_dto.user_email = None
        search_dto.scope = None
        search_dto.asset_type = None
        search_dto.original_filename = None
    elif search_dto.user_email:
        # Admin is searching for a specific user. You'll need to find the user's ID.
        if search_dto.user_email == current_user.email:
            target_user_id = current_user.id
        else:
            target_user = await asyncio.to_thread(
                user_repo.get_by_email,
                search_dto.user_email,
            )
            if not target_user:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "User email not found."
                )
            target_user_id = target_user.id

    return await service.list_assets_for_user(
        search_dto=search_dto,
        target_user_id=target_user_id,
    )


@router.get("/vto-assets", response_model=VtoAssetsResponseDto)
async def get_vto_assets(
    current_user: UserModel = Depends(get_current_user),
    service: SourceAssetService = Depends(),
):
    """Retrieves all system-level VTO assets (models, clothing) categorized by type.
    This is a public endpoint for any authenticated user to populate selection UIs.
    """
    try:
        return await service.get_all_vto_assets(user=current_user)
    except Exception as e:
        # Re-raise as HTTPException to be caught by FastAPI's error handling
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while fetching VTO assets: {e}",
        ) from e


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN]))],
)
async def delete_source_asset(
    asset_id: int,
    service: SourceAssetService = Depends(),
):
    """Deletes a source asset by its ID. (Admin only)
    This will also remove the corresponding file from Google Cloud Storage.
    """
    success = await service.delete_asset(asset_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source asset not found.",
        )
    # On success, a 204 No Content response is automatically returned.


@router.get("/{asset_id}", response_model=SourceAssetResponseDto)
async def get_source_asset(
    asset_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: SourceAssetService = Depends(),
):
    """Retrieves a single source asset by its ID."""
    asset = await service.get_asset_by_id(asset_id, current_user)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source asset not found.",
        )
    return asset
