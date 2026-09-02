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

"""REST Controller for Folders."""

from fastapi import APIRouter, Depends, Query, status

from src.auth.auth_guard import RoleChecker, get_current_user
from src.folders.dto.folder_dto import (
    FolderBreadcrumbDto,
    FolderCreateDto,
    FolderResponseDto,
    FolderTreeNodeDto,
    FolderUpdateDto,
    MoveItemsDto,
)
from src.folders.folder_service import FolderService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth

router = APIRouter(
    prefix="/api/folders",
    tags=["Creative Studio Folders"],
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
    "",
    response_model=FolderResponseDto,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    dto: FolderCreateDto,
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> FolderResponseDto:
    """Create a new folder in a workspace."""
    await workspace_auth.authorize(
        workspace_id=dto.workspace_id,
        user=current_user,
    )
    return await service.create_folder(dto=dto, user=current_user)


@router.get(
    "",
    response_model=list[FolderResponseDto],
)
async def list_folders(
    workspace_id: int = Query(
        ..., description="Workspace ID to list folders for"
    ),
    parent_id: int | None = Query(
        None,
        description="Parent folder ID (omit or None for root level folders)",
    ),
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> list[FolderResponseDto]:
    """List direct child folders under a parent or root of a workspace."""
    await workspace_auth.authorize(
        workspace_id=workspace_id,
        user=current_user,
    )
    return await service.get_folders(
        workspace_id=workspace_id, parent_id=parent_id
    )


@router.get(
    "/tree",
    response_model=list[FolderTreeNodeDto],
)
async def get_folder_tree(
    workspace_id: int = Query(..., description="Workspace ID"),
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> list[FolderTreeNodeDto]:
    """Get full hierarchical folder tree for navigation and picker modals."""
    await workspace_auth.authorize(
        workspace_id=workspace_id,
        user=current_user,
    )
    return await service.get_folder_tree(workspace_id=workspace_id)


@router.get(
    "/{folder_id}/breadcrumbs",
    response_model=list[FolderBreadcrumbDto],
)
async def get_folder_breadcrumbs(
    folder_id: int,
    workspace_id: int | None = Query(
        None,
        description="Optional active workspace ID to validate folder membership",
    ),
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> list[FolderBreadcrumbDto]:
    """Get ancestor breadcrumbs from root to current folder."""
    if workspace_id is not None:
        await workspace_auth.authorize(
            workspace_id=workspace_id,
            user=current_user,
        )
    return await service.get_breadcrumbs(
        folder_id=folder_id, workspace_id=workspace_id
    )


@router.get(
    "/{folder_id}",
    response_model=FolderResponseDto,
)
async def get_folder(
    folder_id: int,
    workspace_id: int | None = Query(
        None,
        description="Optional active workspace ID to validate folder membership",
    ),
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> FolderResponseDto:
    """Get single folder details by ID."""
    if workspace_id is not None:
        await workspace_auth.authorize(
            workspace_id=workspace_id,
            user=current_user,
        )
    return await service.get_folder_by_id(
        folder_id=folder_id, workspace_id=workspace_id
    )


@router.patch(
    "/{folder_id}",
    response_model=FolderResponseDto,
)
async def update_folder(
    folder_id: int,
    dto: FolderUpdateDto,
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> FolderResponseDto:
    """Update folder properties or move folder to new parent."""
    folder = await service.get_folder_by_id(folder_id=folder_id)
    await workspace_auth.authorize(
        workspace_id=folder.workspace_id,
        user=current_user,
    )
    return await service.update_folder(
        folder_id=folder_id, dto=dto, user=current_user
    )


@router.delete(
    "/{folder_id}",
)
async def delete_folder(
    folder_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> dict[str, bool]:
    """Soft delete a folder and all its subfolders."""
    folder = await service.get_folder_by_id(folder_id=folder_id)
    await workspace_auth.authorize(
        workspace_id=folder.workspace_id,
        user=current_user,
    )
    return await service.delete_folder(folder_id=folder_id, user=current_user)


@router.post(
    "/move-items",
)
async def move_items(
    dto: MoveItemsDto,
    current_user: UserModel = Depends(get_current_user),
    service: FolderService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
) -> dict[str, int]:
    """Batch move media items, source assets, and folders to a destination folder."""
    await workspace_auth.authorize(
        workspace_id=dto.workspace_id,
        user=current_user,
    )
    return await service.move_items(dto=dto, user=current_user)
