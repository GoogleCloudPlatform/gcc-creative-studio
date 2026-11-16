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
"""Revision stack history service for gallery items."""

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.schema.media_item_model import MediaItem, MediaItemModel
from src.database import get_db
from src.galleries.dto.unified_gallery_response import (
    RevisionHistoryResponseDto,
)
from src.galleries.gallery_service import GalleryService
from src.galleries.revision_lineage import stack_root_expr
from src.images.repository.media_item_repository import MediaRepository
from src.users.user_model import UserModel
from src.workspaces.schema.workspace_model import WorkspaceScopeEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth


class RevisionService:
    """Serves full stack history for gallery items."""

    def __init__(
        self,
        db: AsyncSession = Depends(get_db),
        media_repo: MediaRepository = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
        gallery_service: GalleryService = Depends(),
    ):
        self.db = db
        self.media_repo = media_repo
        self.workspace_auth = workspace_auth
        self.gallery_service = gallery_service

    async def get_revisions(
        self, item_id: int, current_user: UserModel
    ) -> RevisionHistoryResponseDto:
        """Returns ordered takes for an item's revision stack."""
        item = await self.media_repo.get_by_id(item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media item not found",
            )

        workspace = await self.workspace_auth.authorize(
            workspace_id=item.workspace_id, user=current_user
        )
        if workspace.scope != WorkspaceScopeEnum.PERSONAL:
            hydrated = await self.gallery_service.hydrate_media_items(
                [item], current_user
            )
            return RevisionHistoryResponseDto(
                root_id=item.id or item_id,
                revision_count=1,
                takes=hydrated,
            )

        root_id = item.revision_root_id or item.id or item_id
        takes_res = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.workspace_id == item.workspace_id,
                MediaItem.deleted_at.is_(None),
                stack_root_expr(MediaItem) == root_id,
            )
            .order_by(MediaItem.revision_number.asc(), MediaItem.id.asc())
        )
        take_rows = takes_res.scalars().all()
        take_models = (
            [MediaItemModel.model_validate(r) for r in take_rows]
            if take_rows
            else [item]
        )
        hydrated_takes = await self.gallery_service.hydrate_media_items(
            take_models, current_user
        )
        return RevisionHistoryResponseDto(
            root_id=root_id,
            revision_count=len(hydrated_takes),
            takes=hydrated_takes,
        )
