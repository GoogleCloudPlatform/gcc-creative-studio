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
    PromotionSummaryDto,
    RevisionHistoryResponseDto,
)
from src.galleries.gallery_service import GalleryService
from src.galleries.revision_lineage import stack_root_expr
from src.images.repository.media_item_repository import MediaRepository
from src.users.user_model import UserModel
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import (
    WorkspaceAuth,
    accessible_shared_workspace_clause,
)


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

    async def _load_accessible_promotions(
        self,
        root_id: int,
        workspace_id: int,
        current_user: UserModel,
        take_models: list[MediaItemModel],
    ) -> list[PromotionSummaryDto]:
        stmt = (
            select(
                MediaItem.id,
                MediaItem.workspace_id,
                Workspace.name.label("workspace_name"),
                MediaItem.folder_id,
                MediaItem.promoted_from_media_item_id,
            )
            .join(Workspace, Workspace.id == MediaItem.workspace_id)
            .where(
                MediaItem.deleted_at.is_(None),
                MediaItem.workspace_id != workspace_id,
                MediaItem.promoted_from_root_id == root_id,
                accessible_shared_workspace_clause(current_user),
            )
        )
        rows = (await self.db.execute(stmt.order_by(MediaItem.id.desc()))).all()
        if not rows:
            return []

        rev_by_id: dict[int, int] = {
            t.id: t.revision_number
            for t in take_models
            if t.id is not None and t.revision_number is not None
        }
        missing_src_ids = sorted(
            {
                r.promoted_from_media_item_id
                for r in rows
                if r.promoted_from_media_item_id is not None
                and r.promoted_from_media_item_id not in rev_by_id
            }
        )
        if missing_src_ids:
            rev_res = await self.db.execute(
                select(MediaItem.id, MediaItem.revision_number)
                .where(MediaItem.id.in_(missing_src_ids))
                .execution_options(include_deleted=True)
            )
            for mid, rev_num in rev_res.all():
                if rev_num is not None:
                    rev_by_id[mid] = rev_num

        return [
            PromotionSummaryDto(
                target_workspace_id=row.workspace_id,
                target_workspace_name=row.workspace_name,
                target_item_id=row.id,
                target_folder_id=row.folder_id,
                promoted_revision_number=(
                    rev_by_id.get(row.promoted_from_media_item_id)
                    if row.promoted_from_media_item_id is not None
                    else None
                ),
                promoted_from_media_item_id=row.promoted_from_media_item_id,
            )
            for row in rows
        ]

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
                promotions=[],
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
        promotions = await self._load_accessible_promotions(
            root_id=root_id,
            workspace_id=item.workspace_id,
            current_user=current_user,
            take_models=take_models,
        )
        return RevisionHistoryResponseDto(
            root_id=root_id,
            revision_count=len(hydrated_takes),
            takes=hydrated_takes,
            promotions=promotions,
        )
