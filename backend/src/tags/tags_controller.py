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

from fastapi import APIRouter, Depends, HTTPException, status
from src.auth.auth_guard import RoleChecker, get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.tags.dto.tags_dto import (
    BulkAssignTagsDto,
    TagCreateDto,
    TagUpdateDto,
    TagSearchDto,
)
from src.tags.tags_service import TagsService
from src.tags.schema.tags_model import TagModel
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.workspace_auth_guard import (
    WorkspaceAuth,
    is_workspace_manager,
)

router = APIRouter(
    prefix="/api/tags",
    tags=["Creative Studio Tags"],
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


@router.post("/search", response_model=PaginationResponseDto[TagModel])
async def search_tags(
    search_dto: TagSearchDto,
    current_user: UserModel = Depends(get_current_user),
    service: TagsService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Searches tags with pagination."""
    is_admin = UserRoleEnum.ADMIN in current_user.roles

    if search_dto.workspace_id:
        await workspace_auth.authorize(
            workspace_id=search_dto.workspace_id,
            user=current_user,
        )
        return await service.list_tags(
            search_dto.workspace_id,
            search_dto.search,
            search_dto.limit,
            search_dto.offset,
            search_dto.user_id,
        )

    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non-admin users must specify a workspace_id.",
        )

    return await service.list_tags(
        search=search_dto.search,
        limit=search_dto.limit,
        offset=search_dto.offset,
        creator_user_id=search_dto.user_id,
        requesting_user_id=current_user.id,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tag(
    dto: TagCreateDto,
    current_user: UserModel = Depends(get_current_user),
    service: TagsService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Creates a new tag in a workspace."""
    await workspace_auth.authorize_write(
        workspace_id=dto.workspace_id,
        user=current_user,
    )
    return await service.create_tag(dto, current_user.id)


@router.put("/{tag_id}")
async def update_tag(
    tag_id: int,
    dto: TagUpdateDto,
    current_user: UserModel = Depends(get_current_user),
    service: TagsService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Updates a tag."""
    tag = await service.repo.get_by_id(tag_id)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    workspace = await workspace_auth.authorize_write(
        workspace_id=tag.workspace_id,
        user=current_user,
    )
    return await service.update_tag(
        tag_id,
        dto,
        current_user.id,
        is_workspace_manager(current_user, workspace),
    )


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: TagsService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Deletes a tag."""
    tag = await service.repo.get_by_id(tag_id)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    workspace = await workspace_auth.authorize_write(
        workspace_id=tag.workspace_id,
        user=current_user,
    )

    return await service.delete_tag(
        tag_id,
        current_user.id,
        is_workspace_manager(current_user, workspace),
        tag=tag,
    )


@router.post("/bulk-assign")
async def bulk_assign_tags(
    dto: BulkAssignTagsDto,
    current_user: UserModel = Depends(get_current_user),
    service: TagsService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    """Bulk assigns tags to multiple items."""
    await workspace_auth.authorize_write(
        workspace_id=dto.workspace_id,
        user=current_user,
    )
    return await service.bulk_assign(dto, current_user.id)
