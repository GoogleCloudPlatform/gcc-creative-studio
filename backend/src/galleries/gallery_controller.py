# Copyright 2025 Google LLC
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

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.auth_guard import RoleChecker, get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.galleries.dto.bulk_copy_dto import BulkCopyDto
from src.galleries.dto.bulk_delete_dto import BulkDeleteDto
from src.galleries.dto.bulk_download_dto import BulkDownloadDto
from src.galleries.dto.bulk_move_dto import BulkMoveDto
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.unified_gallery_response import (
    UnifiedGalleryItemResponse,
)
from src.galleries.gallery_service import GalleryService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth

router = APIRouter(
    prefix="/api/gallery",
    tags=["Creative Studio Media Gallery"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[
                    UserRoleEnum.ADMIN,
                    UserRoleEnum.USER,
                ],
            ),
        ),
    ],
)


@router.post(
    "/search",
    response_model=PaginationResponseDto[UnifiedGalleryItemResponse],
)
async def search_gallery_items(
    search_dto: GallerySearchDto,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Performs a paginated search for media items within a specific workspace.

    Provide filters in the request body to paginate through the gallery.
    to paginate through results.
    """
    # Enforce workspace_id for non-admins
    is_admin = current_user.roles and UserRoleEnum.ADMIN in current_user.roles
    if not is_admin:
        if not search_dto.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required for non-admin users.",
            )
        await workspace_auth.authorize(
            workspace_id=search_dto.workspace_id,
            user=current_user,
        )
    # For admins, only authorize if workspace_id is provided
    elif search_dto.workspace_id is not None:
        await workspace_auth.authorize(
            workspace_id=search_dto.workspace_id,
            user=current_user,
        )

    return await service.get_paginated_gallery(
        search_dto=search_dto,
        current_user=current_user,
    )


@router.get("/item/{item_id}", response_model=MediaItemResponse)
async def get_single_gallery_item(
    item_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
):
    """Get a single media item by its ID."""
    # The service now requires the user to perform authorization checks.
    item = await service.get_media_by_id(
        item_id=item_id, current_user=current_user
    )
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media item not found",
        )
    return item


@router.post("/bulk-delete")
async def bulk_delete_items(
    bulk_delete_dto: BulkDeleteDto,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
):
    """Bulk delete media items and source assets."""
    return await service.bulk_delete(
        bulk_delete_dto=bulk_delete_dto,
        current_user=current_user,
    )


@router.post("/items/{item_id}/restore")
async def restore_gallery_item(
    item_id: int,
    item_type: str,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
):
    """Restore a soft-deleted item by its ID and item_type."""
    return await service.restore_item(
        item_id=item_id,
        item_type=item_type,
        current_user=current_user,
    )


@router.post("/bulk-download")
async def bulk_download_items(
    bulk_download_dto: BulkDownloadDto,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
):
    """Bulk download media items and source assets as a ZIP file."""
    return await service.bulk_download(
        bulk_download_dto=bulk_download_dto,
        current_user=current_user,
    )


@router.post("/bulk-copy")
async def bulk_copy_items(
    bulk_copy_dto: BulkCopyDto,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
):
    """Bulk copy media items, source assets, and folders to another workspace."""
    return await service.bulk_copy(
        bulk_copy_dto=bulk_copy_dto,
        current_user=current_user,
    )


@router.post("/bulk-move")
async def bulk_move_items(
    bulk_move_dto: BulkMoveDto,
    current_user: UserModel = Depends(get_current_user),
    service: GalleryService = Depends(),
):
    """Bulk move media items, source assets, and folders to another workspace."""
    return await service.bulk_move(
        bulk_move_dto=bulk_move_dto,
        current_user=current_user,
    )
