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
"""Database queries, locking, folder subtree cloning, and upserts."""

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.folders.repository.folder_repository import (
    FolderRepository,
    generate_disambiguated_name,
)
from src.folders.schema.folder_model import Folder
from src.galleries.dto.bulk_copy_dto import BulkCopyItemDto
from src.galleries.dto.promote_dto import PromoteResultItemDto
from src.galleries.repository.promotion_mapper import copy_column_values
from src.galleries.revision_lineage import (
    COPIED_ASSET_EXCLUDE_FIELDS,
    COPIED_MEDIA_EXCLUDE_FIELDS,
    latest_completed_take_predicate,
    lock_media_stack_root,
    sanitize_copied_media_kwargs,
    stack_root_expr,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    SourceAsset,
)
from src.users.user_model import UserModel


class PromotionRepository:
    """Encapsulates promotion SQL queries, locking, and lineage-safe clones."""

    def __init__(self, db: AsyncSession, folder_repo: FolderRepository):
        self.db = db
        self.folder_repo = folder_repo

    async def collect_promotable_sources(
        self,
        source_workspace_id: int,
        items: list[BulkCopyItemDto],
    ) -> tuple[list[tuple[int, int]], list[int], int]:
        """Returns direct updatable pairs/assets plus net-new folder count."""
        media_pairs: list[tuple[int, int]] = []
        seen_roots: set[int] = set()
        asset_ids: list[int] = []
        seen_assets: set[int] = set()
        folder_item_count = 0

        req_media = [it.id for it in items if it.type == "media_item"]
        req_assets = [it.id for it in items if it.type == "source_asset"]
        req_folders = [it.id for it in items if it.type == "folder"]

        if req_media:
            res = await self.db.execute(
                select(MediaItem.id, MediaItem.revision_root_id).where(
                    MediaItem.id.in_(req_media),
                    MediaItem.workspace_id == source_workspace_id,
                    MediaItem.deleted_at.is_(None),
                    MediaItem.status == JobStatusEnum.COMPLETED.value,
                )
            )
            for mid, r_id in res.all():
                root_id = r_id or mid
                if root_id not in seen_roots:
                    seen_roots.add(root_id)
                    media_pairs.append((mid, root_id))

        if req_assets:
            res = await self.db.execute(
                select(SourceAsset.id).where(
                    SourceAsset.id.in_(req_assets),
                    SourceAsset.workspace_id == source_workspace_id,
                    SourceAsset.deleted_at.is_(None),
                )
            )
            for (aid,) in res.all():
                if aid not in seen_assets:
                    seen_assets.add(aid)
                    asset_ids.append(aid)

        if req_folders:
            descendants = await self.folder_repo.get_descendant_ids_batch(
                req_folders
            )
            if descendants:
                m_res = await self.db.execute(
                    select(func.count(MediaItem.id)).where(
                        MediaItem.folder_id.in_(descendants),
                        MediaItem.workspace_id == source_workspace_id,
                        MediaItem.deleted_at.is_(None),
                        MediaItem.status == JobStatusEnum.COMPLETED.value,
                        latest_completed_take_predicate(MediaItem),
                    )
                )
                a_res = await self.db.execute(
                    select(func.count(SourceAsset.id)).where(
                        SourceAsset.folder_id.in_(descendants),
                        SourceAsset.workspace_id == source_workspace_id,
                        SourceAsset.deleted_at.is_(None),
                    )
                )
                # Folders always promote as new cloned subtrees, so folder
                # contents count as net-new items in target previews.
                folder_item_count += int(m_res.scalar_one() or 0) + int(
                    a_res.scalar_one() or 0
                )

        return media_pairs, asset_ids, folder_item_count

    async def fetch_existing_media_promotions(
        self, target_ws_ids: list[int], stack_roots: list[int]
    ) -> tuple[list[Any], dict[int, int]]:
        """Loads existing promoted MediaItem copies and source revision nums."""
        if not stack_roots or not target_ws_ids:
            return [], {}
        pm_res = await self.db.execute(
            select(
                MediaItem.id,
                MediaItem.workspace_id,
                MediaItem.folder_id,
                MediaItem.user_id,
                MediaItem.promoted_from_root_id,
                MediaItem.promoted_from_media_item_id,
            )
            .where(
                MediaItem.workspace_id.in_(target_ws_ids),
                MediaItem.deleted_at.is_(None),
                MediaItem.promoted_from_root_id.in_(stack_roots),
            )
            .order_by(MediaItem.id.desc())
        )
        pm_rows = list(pm_res.all())
        src_ids = sorted(
            {
                r.promoted_from_media_item_id
                for r in pm_rows
                if r.promoted_from_media_item_id is not None
            }
        )
        rev_by_src: dict[int, int] = {}
        if src_ids:
            rev_res = await self.db.execute(
                select(MediaItem.id, MediaItem.revision_number)
                .where(MediaItem.id.in_(src_ids))
                .execution_options(include_deleted=True)
            )
            rev_by_src = {r.id: r.revision_number for r in rev_res.all()}
        return pm_rows, rev_by_src

    async def fetch_existing_asset_promotions(
        self, target_ws_ids: list[int], asset_ids: list[int]
    ) -> list[Any]:
        """Loads existing promoted SourceAsset copies in target workspaces."""
        if not asset_ids or not target_ws_ids:
            return []
        pa_res = await self.db.execute(
            select(
                SourceAsset.id,
                SourceAsset.workspace_id,
                SourceAsset.folder_id,
                SourceAsset.user_id,
                SourceAsset.promoted_from_source_asset_id,
            )
            .where(
                SourceAsset.workspace_id.in_(target_ws_ids),
                SourceAsset.deleted_at.is_(None),
                SourceAsset.promoted_from_source_asset_id.in_(asset_ids),
            )
            .order_by(SourceAsset.id.desc())
        )
        return list(pa_res.all())

    async def get_source_media(
        self, item_id: int, workspace_id: int
    ) -> MediaItem | None:
        """Fetches active MediaItem inside the validated source workspace."""
        res = await self.db.execute(
            select(MediaItem).where(
                MediaItem.id == item_id,
                MediaItem.workspace_id == workspace_id,
                MediaItem.deleted_at.is_(None),
            )
        )
        return res.scalar_one_or_none()

    async def get_source_asset(
        self, asset_id: int, workspace_id: int
    ) -> SourceAsset | None:
        """Fetches active SourceAsset inside the validated source workspace."""
        res = await self.db.execute(
            select(SourceAsset).where(
                SourceAsset.id == asset_id,
                SourceAsset.workspace_id == workspace_id,
                SourceAsset.deleted_at.is_(None),
            )
        )
        return res.scalar_one_or_none()

    async def list_updatable_media(
        self, target_workspace_id: int, root_id: int
    ) -> list[MediaItem]:
        """Lists active promoted MediaItem copies matching a personal stack."""
        res = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.workspace_id == target_workspace_id,
                MediaItem.deleted_at.is_(None),
                MediaItem.promoted_from_root_id == root_id,
            )
            .order_by(MediaItem.id.desc())
        )
        return list(res.scalars().all())

    async def list_updatable_assets(
        self, target_workspace_id: int, source_asset_id: int
    ) -> list[SourceAsset]:
        """Lists active promoted SourceAsset copies matching a personal asset."""
        res = await self.db.execute(
            select(SourceAsset)
            .where(
                SourceAsset.workspace_id == target_workspace_id,
                SourceAsset.deleted_at.is_(None),
                SourceAsset.promoted_from_source_asset_id == source_asset_id,
            )
            .order_by(SourceAsset.id.desc())
        )
        return list(res.scalars().all())

    async def build_clean_media_kwargs(
        self, src: MediaItem, target_workspace_id: int
    ) -> dict[str, Any]:
        """Locks stack root, clones column values, and strips private refs."""
        root_id = src.revision_root_id or src.id
        await lock_media_stack_root(self.db, root_id)
        cols = [
            c.key
            for c in MediaItem.__table__.columns
            if c.key not in COPIED_MEDIA_EXCLUDE_FIELDS
        ]
        kwargs = copy_column_values(src, cols)
        await sanitize_copied_media_kwargs(self.db, kwargs, target_workspace_id)
        return kwargs

    async def lock_source_asset(self, asset_id: int) -> None:
        """Locks the source asset row (even soft-deleted) during promotion."""
        await self.db.execute(
            select(SourceAsset.id)
            .where(SourceAsset.id == asset_id)
            .with_for_update()
            .execution_options(include_deleted=True)
        )

    def build_clean_asset_kwargs(self, src: SourceAsset) -> dict[str, Any]:
        """Clones SourceAsset attributes and normalizes scope to private."""
        cols = [
            c.key
            for c in SourceAsset.__table__.columns
            if c.key not in COPIED_ASSET_EXCLUDE_FIELDS
        ]
        kwargs = copy_column_values(src, cols)
        kwargs["scope"] = AssetScopeEnum.PRIVATE.value
        return kwargs

    async def clone_folder_structure(
        self,
        folder_id: int,
        root_name: str,
        *,
        source_workspace_id: int,
        target_workspace_id: int,
        target_parent_folder_id: int | None,
        current_user: UserModel,
    ) -> tuple[dict[int, int], list[MediaItem], list[SourceAsset]]:
        """Clones a folder tree and collects latest completed media & assets."""
        existing = await self.folder_repo.get_existing_folder_names(
            workspace_id=target_workspace_id, parent_id=target_parent_folder_id
        )
        disambiguated = generate_disambiguated_name(root_name, existing)
        cte_sql = text(
            """
            WITH RECURSIVE descendants AS (
                SELECT id, name, color, parent_id, 0 AS depth
                FROM folders
                WHERE id = :folder_id
                  AND workspace_id = :source_workspace_id
                  AND deleted_at IS NULL
                UNION ALL
                SELECT f.id, f.name, f.color, f.parent_id, d.depth + 1 AS depth
                FROM folders f
                JOIN descendants d ON f.parent_id = d.id
                WHERE f.deleted_at IS NULL
                  AND f.workspace_id = :source_workspace_id
            )
            SELECT id, name, color, parent_id, depth
            FROM descendants ORDER BY depth ASC, id ASC
            """
        )
        cte_res = await self.db.execute(
            cte_sql,
            {
                "folder_id": folder_id,
                "source_workspace_id": source_workspace_id,
            },
        )
        folder_rows = cte_res.fetchall()
        if not folder_rows:
            return {}, [], []

        depth_map: dict[int, list[Any]] = {}
        for row in folder_rows:
            depth_map.setdefault(row.depth, []).append(row)
        id_map: dict[int, int] = {}
        for depth in sorted(depth_map):
            batch: list[tuple[int, Folder]] = []
            for row in depth_map[depth]:
                is_root = row.id == folder_id
                folder_obj = Folder(
                    workspace_id=target_workspace_id,
                    user_id=current_user.id,
                    user_email=current_user.email,
                    name=disambiguated if is_root else row.name,
                    parent_id=(
                        target_parent_folder_id
                        if is_root
                        else id_map.get(row.parent_id)
                    ),
                    color=row.color,
                )
                self.db.add(folder_obj)
                batch.append((row.id, folder_obj))
            await self.db.flush()
            for old_id, new_f in batch:
                id_map[old_id] = new_f.id

        old_ids = list(id_map)
        m_res = await self.db.execute(
            select(MediaItem)
            .where(
                MediaItem.folder_id.in_(old_ids),
                MediaItem.workspace_id == source_workspace_id,
                MediaItem.deleted_at.is_(None),
                MediaItem.status == JobStatusEnum.COMPLETED.value,
                latest_completed_take_predicate(MediaItem),
            )
            .order_by(stack_root_expr(MediaItem).asc(), MediaItem.id.asc())
        )
        a_res = await self.db.execute(
            select(SourceAsset)
            .where(
                SourceAsset.folder_id.in_(old_ids),
                SourceAsset.workspace_id == source_workspace_id,
                SourceAsset.deleted_at.is_(None),
            )
            .order_by(SourceAsset.id.asc())
        )
        return id_map, list(m_res.scalars().all()), list(a_res.scalars().all())

    async def upsert_promoted(
        self,
        *,
        existing: MediaItem | SourceAsset | None,
        model_cls: type[MediaItem] | type[SourceAsset],
        attrs: dict[str, Any],
        lineage_attrs: dict[str, Any],
        create_extra: dict[str, Any],
        source_id: int,
        source_type: str,
        target_workspace_id: int,
        target_folder_id: int | None,
        clear_target_folder: bool = False,
    ) -> PromoteResultItemDto:
        """Updates an existing promoted copy in place or inserts a new row."""
        if existing is not None:
            for col, val in {**attrs, **lineage_attrs}.items():
                setattr(existing, col, val)
            if target_folder_id is not None:
                existing.folder_id = target_folder_id
            elif clear_target_folder:
                existing.folder_id = None
            await self.db.flush()
            return PromoteResultItemDto(
                source_id=source_id,
                source_type=source_type,
                target_id=existing.id,
                target_workspace_id=target_workspace_id,
                target_folder_id=existing.folder_id,
                action="updated",
            )
        created = model_cls(
            workspace_id=target_workspace_id,
            folder_id=target_folder_id,
            **create_extra,
            **lineage_attrs,
            **attrs,
        )
        self.db.add(created)
        await self.db.flush()
        return PromoteResultItemDto(
            source_id=source_id,
            source_type=source_type,
            target_id=created.id,
            target_workspace_id=target_workspace_id,
            target_folder_id=created.folder_id,
            action="created",
        )
