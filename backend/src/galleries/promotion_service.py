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
"""Promotes curated personal creations and folders into shared workspaces."""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.database import get_db
from src.folders.repository.folder_repository import FolderRepository
from src.galleries.dto.promote_dto import (
    PromoteItemsDto,
    PromoteResponseDto,
    PromoteResultItemDto,
    PromoteTargetWorkspaceDto,
    PromoteTargetsRequestDto,
)
from src.galleries.repository.promotion_mapper import (
    index_updatable_matches,
    pick_updatable_match,
    to_target_dto,
)
from src.galleries.repository.promotion_repository import PromotionRepository
from src.source_assets.schema.source_asset_model import SourceAsset
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
    coerce_workspace_role,
)
from src.workspaces.workspace_auth_guard import WorkspaceAuth
from src.workspaces.workspace_service import WorkspaceService

MAX_FOLDER_DEPTH: int = 20

_WRITER_ROLES = {
    WorkspaceRoleEnum.OWNER,
    WorkspaceRoleEnum.ADMIN,
    WorkspaceRoleEnum.EDITOR,
}


class PromotionService:
    """Handles target discovery and lineage-safe cross-workspace promotion."""

    def __init__(
        self,
        db: AsyncSession = Depends(get_db),
        workspace_auth: WorkspaceAuth = Depends(),
        workspace_service: WorkspaceService = Depends(),
        folder_repo: FolderRepository = Depends(),
    ):
        self.db = db
        self.workspace_auth = workspace_auth
        self.workspace_service = workspace_service
        self.folder_repo = folder_repo
        self.promo_repo = PromotionRepository(db, folder_repo)

    @staticmethod
    def _can_write(ws: WorkspaceModel, user: UserModel) -> bool:
        if ws.scope == WorkspaceScopeEnum.PERSONAL:
            return False
        if ws.scope == WorkspaceScopeEnum.PUBLIC or UserRoleEnum.ADMIN in (
            user.roles or []
        ):
            return True
        role = coerce_workspace_role(ws.current_user_role)
        return ws.owner_id == user.id or role in _WRITER_ROLES

    async def _require_personal_source(
        self, source_workspace_id: int, current_user: UserModel
    ) -> None:
        src_ws = await self.workspace_auth.authorize(
            source_workspace_id, current_user
        )
        if src_ws.scope != WorkspaceScopeEnum.PERSONAL:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Items can only be promoted from your personal workspace.",
            )

    async def _covered_child_folders(self, folder_ids: list[int]) -> set[int]:
        if len(folder_ids) <= 1:
            return set()
        covered: set[int] = set()
        for fid in folder_ids:
            descendants = await self.folder_repo.get_descendant_ids(fid)
            covered.update(d for d in descendants if d != fid)
        return covered

    async def get_promote_targets(
        self, request_dto: PromoteTargetsRequestDto, current_user: UserModel
    ) -> list[PromoteTargetWorkspaceDto]:
        """Lists writable shared workspaces with existing vs net-new counts."""
        src_ws_id = request_dto.source_workspace_id
        await self._require_personal_source(src_ws_id, current_user)
        all_ws = await self.workspace_service.list_workspaces_for_user(
            current_user
        )
        cands = [
            w
            for w in all_ws
            if w.id is not None
            and w.id != src_ws_id
            and self._can_write(w, current_user)
        ]
        if not cands:
            return []

        media_pairs, a_ids, folder_item_count = (
            await self.promo_repo.collect_promotable_sources(
                src_ws_id, request_dto.items
            )
        )
        total = len(media_pairs) + len(a_ids) + folder_item_count
        roots = [r for _, r in media_pairs]
        ws_by_id = {w.id: w for w in cands if w.id is not None}
        ws_ids = list(ws_by_id)
        pm, rev = await self.promo_repo.fetch_existing_media_promotions(
            ws_ids, roots
        )
        pa = await self.promo_repo.fetch_existing_asset_promotions(
            ws_ids, a_ids
        )
        m_idx = index_updatable_matches(
            pm,
            ws_by_id,
            current_user,
            lambda r: r.promoted_from_root_id,
        )
        a_idx = index_updatable_matches(
            pa,
            ws_by_id,
            current_user,
            lambda r: r.promoted_from_source_asset_id,
        )
        single = (
            len(request_dto.items) == 1
            and request_dto.items[0].type != "folder"
        )
        return [
            to_target_dto(w, roots, a_ids, m_idx, a_idx, rev, single, total)
            for w in cands
        ]

    async def _promote_one(
        self,
        kind: str,
        src: MediaItem | SourceAsset,
        target_ws: WorkspaceModel,
        folder_id: int | None,
        mode: str,
        user: UserModel,
        clear_target_folder: bool = False,
    ) -> PromoteResultItemDto:
        assert target_ws.id is not None
        tws_id = target_ws.id
        can_upd = mode == "update_or_create"
        if isinstance(src, MediaItem) and kind == "media_item":
            root_id = src.revision_root_id or src.id
            attrs = await self.promo_repo.build_clean_media_kwargs(src, tws_id)
            rows: list[MediaItem] | list[SourceAsset] = (
                await self.promo_repo.list_updatable_media(tws_id, root_id)
                if can_upd
                else []
            )
            lineage: dict[str, int | None] = {
                "revision_root_id": None,
                "revision_parent_id": None,
                "revision_number": 1,
                "promoted_from_media_item_id": src.id,
                "promoted_from_root_id": root_id,
            }
            extra: dict[str, int | str | None] = {
                "user_id": user.id,
                "user_email": user.email,
            }
            cls: type[MediaItem] | type[SourceAsset] = MediaItem
        elif isinstance(src, SourceAsset):
            await self.promo_repo.lock_source_asset(src.id)
            attrs = self.promo_repo.build_clean_asset_kwargs(src)
            rows = (
                await self.promo_repo.list_updatable_assets(tws_id, src.id)
                if can_upd
                else []
            )
            lineage = {"promoted_from_source_asset_id": src.id}
            extra = {"user_id": user.id}
            cls = SourceAsset
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Mismatched source type '{kind}' during promotion.",
            )
        existing = pick_updatable_match(rows, target_ws, user) if rows else None
        return await self.promo_repo.upsert_promoted(
            existing=existing,
            model_cls=cls,
            attrs=attrs,
            lineage_attrs=lineage,
            create_extra=extra,
            source_id=src.id,
            source_type=kind,
            target_workspace_id=tws_id,
            target_folder_id=folder_id,
            clear_target_folder=clear_target_folder,
        )

    async def promote_items(
        self, dto: PromoteItemsDto, current_user: UserModel
    ) -> PromoteResponseDto:
        """Promotes media items, source assets, and folders into target."""
        await self._require_personal_source(
            dto.source_workspace_id, current_user
        )
        if dto.source_workspace_id == dto.target_workspace_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Source and target workspaces must differ.",
            )
        target_ws = await self.workspace_auth.authorize_write(
            dto.target_workspace_id, current_user
        )
        if target_ws.scope == WorkspaceScopeEnum.PERSONAL:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot promote into a personal workspace.",
            )
        if dto.target_folder_id is not None:
            dest = await self.folder_repo.get_folder_by_id(dto.target_folder_id)
            if dest is None or dest.workspace_id != dto.target_workspace_id:
                raise HTTPException(
                    422,
                    "The selected destination folder was not found in the target workspace.",
                )

        clear_folder = bool(
            dto.clear_target_folder and dto.target_folder_id is None
        )
        deduped_entries = []
        seen_entries: set[tuple[str, int]] = set()
        for entry in dto.items:
            key = (entry.type, entry.id)
            if key not in seen_entries:
                seen_entries.add(key)
                deduped_entries.append(entry)

        req_folder_ids = [e.id for e in deduped_entries if e.type == "folder"]
        covered_folders = await self._covered_child_folders(req_folder_ids)
        target_depth = (
            await self.folder_repo.get_folder_depth(dto.target_folder_id)
            if dto.target_folder_id is not None
            else 0
        )
        seen_media_roots: set[int] = set()
        promoted: list[PromoteResultItemDto] = []
        for entry in deduped_entries:
            if entry.type == "media_item":
                src_m = await self.promo_repo.get_source_media(
                    entry.id, dto.source_workspace_id
                )
                if src_m is None:
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND,
                        f"Media item {entry.id} not found in source workspace.",
                    )
                status_val = (
                    src_m.status.value
                    if isinstance(src_m.status, JobStatusEnum)
                    else str(src_m.status or "")
                )
                if status_val.lower() != JobStatusEnum.COMPLETED.value:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        "Only completed media items can be promoted.",
                    )
                root_id = src_m.revision_root_id or src_m.id
                if root_id in seen_media_roots:
                    continue
                seen_media_roots.add(root_id)
                item = await self._promote_one(
                    entry.type,
                    src_m,
                    target_ws,
                    dto.target_folder_id,
                    dto.mode,
                    current_user,
                    clear_target_folder=clear_folder,
                )
                promoted.append(item)
            elif entry.type == "source_asset":
                src_a = await self.promo_repo.get_source_asset(
                    entry.id, dto.source_workspace_id
                )
                if src_a is None:
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND,
                        f"Source asset {entry.id} not found in source workspace.",
                    )
                item = await self._promote_one(
                    entry.type,
                    src_a,
                    target_ws,
                    dto.target_folder_id,
                    dto.mode,
                    current_user,
                    clear_target_folder=clear_folder,
                )
                promoted.append(item)
            elif entry.type == "folder":
                if entry.id in covered_folders:
                    continue
                root_f = await self.folder_repo.get_folder_by_id(entry.id)
                if not root_f or root_f.workspace_id != dto.source_workspace_id:
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND,
                        f"Folder {entry.id} not found in source workspace.",
                    )
                subtree_depth = await self.folder_repo.get_subtree_depth(
                    entry.id
                )
                if target_depth + subtree_depth > MAX_FOLDER_DEPTH:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        (
                            f"Cannot promote folder '{root_f.name}': would "
                            f"exceed maximum tree depth of {MAX_FOLDER_DEPTH}."
                        ),
                    )
                id_map, m_rows, a_rows = (
                    await self.promo_repo.clone_folder_structure(
                        entry.id,
                        root_f.name,
                        source_workspace_id=dto.source_workspace_id,
                        target_workspace_id=dto.target_workspace_id,
                        target_parent_folder_id=dto.target_folder_id,
                        current_user=current_user,
                    )
                )
                for row_m in m_rows:
                    item = await self._promote_one(
                        "media_item",
                        row_m,
                        target_ws,
                        id_map[row_m.folder_id],
                        "create_new",
                        current_user,
                    )
                    promoted.append(item)
                for row_a in a_rows:
                    item = await self._promote_one(
                        "source_asset",
                        row_a,
                        target_ws,
                        id_map[row_a.folder_id],
                        "create_new",
                        current_user,
                    )
                    promoted.append(item)
            else:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Unsupported item type '{entry.type}' for promotion.",
                )

        await self.db.commit()
        updated = sum(1 for item in promoted if item.action == "updated")
        return PromoteResponseDto(
            promoted_count=len(promoted),
            updated_count=updated,
            created_count=len(promoted) - updated,
            target_workspace_id=dto.target_workspace_id,
            target_folder_id=dto.target_folder_id,
            promoted_items=promoted,
        )
