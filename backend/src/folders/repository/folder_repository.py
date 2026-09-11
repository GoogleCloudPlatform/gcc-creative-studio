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

import copy
import re
from datetime import datetime, timezone
from fastapi import Depends
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.schema.media_item_model import MediaItem
from src.database import get_db
from src.folders.dto.folder_dto import (
    ConflictStrategyEnum,
    FolderBreadcrumbDto,
    FolderResponseDto,
    FolderTreeNodeDto,
)
from src.folders.schema.folder_model import Folder, FolderModel
from src.source_assets.schema.source_asset_model import SourceAsset
from src.tags.schema.tags_model import media_item_tags, source_asset_tags


def generate_disambiguated_name(
    base_name: str, existing_names_lower: set[str]
) -> str:
    """Generates a non-colliding name by appending ' (N)'."""
    base = base_name.strip()
    if base.lower() not in existing_names_lower:
        return base

    match = re.search(r"^(.*?)\s+\((\d+)\)$", base)
    if match:
        root_name = match.group(1).strip()
        current_num = int(match.group(2))
    else:
        root_name = base
        current_num = 0

    current_idx = current_num + 1 if current_num > 0 else 1
    while True:
        candidate = f"{root_name} ({current_idx})"
        if candidate.lower() not in existing_names_lower:
            return candidate
        current_idx += 1


class FolderRepository(BaseRepository[Folder, FolderModel]):
    """Handles database queries for folders and folder hierarchies."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Folder, schema=FolderModel, db=db)

    async def is_folder_name_taken(
        self,
        workspace_id: int,
        parent_id: int | None,
        name: str,
        exclude_folder_id: int | None = None,
    ) -> bool:
        """Check if an active folder with the given name exists under the specified parent."""
        clean_name = name.strip()
        query = select(self.model.id).where(
            self.model.workspace_id == workspace_id,
            func.lower(func.trim(self.model.name)) == clean_name.lower(),
            self.model.deleted_at.is_(None),
        )
        if parent_id is None:
            query = query.where(self.model.parent_id.is_(None))
        else:
            query = query.where(self.model.parent_id == parent_id)

        if exclude_folder_id is not None:
            query = query.where(self.model.id != exclude_folder_id)

        result = await self.db.execute(query)
        return result.first() is not None

    async def get_existing_folder_names(
        self,
        workspace_id: int,
        parent_id: int | None,
        exclude_folder_id: int | None = None,
    ) -> set[str]:
        """Fetch set of lowercase trimmed names of all active sibling folders."""
        query = select(func.lower(func.trim(self.model.name))).where(
            self.model.workspace_id == workspace_id,
            self.model.deleted_at.is_(None),
        )
        if parent_id is None:
            query = query.where(self.model.parent_id.is_(None))
        else:
            query = query.where(self.model.parent_id == parent_id)

        if exclude_folder_id is not None:
            query = query.where(self.model.id != exclude_folder_id)

        result = await self.db.execute(query)
        return {row[0] for row in result.fetchall()}

    async def get_folder_by_name(
        self,
        workspace_id: int,
        parent_id: int | None,
        name: str,
        exclude_folder_id: int | None = None,
    ) -> Folder | None:
        """Fetch active folder by case-insensitive trimmed name under the specified parent."""
        clean_name = name.strip().lower()
        query = select(self.model).where(
            self.model.workspace_id == workspace_id,
            func.lower(func.trim(self.model.name)) == clean_name,
            self.model.deleted_at.is_(None),
        )
        if parent_id is None:
            query = query.where(self.model.parent_id.is_(None))
        else:
            query = query.where(self.model.parent_id == parent_id)

        if exclude_folder_id is not None:
            query = query.where(self.model.id != exclude_folder_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_existing_folders_map(
        self,
        workspace_id: int,
        parent_id: int | None,
        exclude_folder_ids: list[int] | None = None,
    ) -> dict[str, Folder]:
        """Fetch dictionary mapping lowercase trimmed name to active Folder instance."""
        query = select(self.model).where(
            self.model.workspace_id == workspace_id,
            self.model.deleted_at.is_(None),
        )
        if parent_id is None:
            query = query.where(self.model.parent_id.is_(None))
        else:
            query = query.where(self.model.parent_id == parent_id)

        if exclude_folder_ids:
            query = query.where(~self.model.id.in_(exclude_folder_ids))

        result = await self.db.execute(query)
        return {
            folder.name.strip().lower(): folder
            for folder in result.scalars().all()
        }

    async def get_unique_folder_name(
        self,
        workspace_id: int,
        parent_id: int | None,
        base_name: str,
        exclude_folder_id: int | None = None,
    ) -> str:
        """Calculates a unique disambiguated name for a folder within its destination."""
        existing_names = await self.get_existing_folder_names(
            workspace_id=workspace_id,
            parent_id=parent_id,
            exclude_folder_id=exclude_folder_id,
        )
        return generate_disambiguated_name(base_name, existing_names)

    async def get_folder_by_id(
        self, folder_id: int, include_deleted: bool = False
    ) -> Folder | None:
        """Fetch single folder by primary key."""
        query = select(self.model).where(self.model.id == folder_id)
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_folders_by_ids(
        self,
        folder_ids: list[int],
        workspace_id: int | None = None,
        include_deleted: bool = False,
    ) -> list[Folder]:
        """Fetch multiple active folders by IDs, optionally scoped to a workspace."""
        if not folder_ids:
            return []
        query = select(self.model).where(self.model.id.in_(folder_ids))
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        if workspace_id is not None:
            query = query.where(self.model.workspace_id == workspace_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_parent(
        self, workspace_id: int, parent_id: int | None = None
    ) -> list[FolderResponseDto]:
        """List immediate child folders in a workspace, including aggregated item & subfolder counts."""
        # Subquery for media_items count per folder
        media_count_sq = (
            select(
                MediaItem.folder_id,
                func.count(MediaItem.id).label("media_count"),
            )
            .where(
                MediaItem.workspace_id == workspace_id,
                MediaItem.deleted_at.is_(None),
                MediaItem.folder_id.is_not(None),
            )
            .group_by(MediaItem.folder_id)
            .subquery()
        )

        # Subquery for source_assets count per folder
        asset_count_sq = (
            select(
                SourceAsset.folder_id,
                func.count(SourceAsset.id).label("asset_count"),
            )
            .where(
                SourceAsset.workspace_id == workspace_id,
                SourceAsset.deleted_at.is_(None),
                SourceAsset.folder_id.is_not(None),
            )
            .group_by(SourceAsset.folder_id)
            .subquery()
        )

        # Subquery for direct subfolder count per folder
        subfolder_count_sq = (
            select(
                Folder.parent_id.label("parent_id"),
                func.count(Folder.id).label("subfolder_count"),
            )
            .where(
                Folder.workspace_id == workspace_id,
                Folder.deleted_at.is_(None),
                Folder.parent_id.is_not(None),
            )
            .group_by(Folder.parent_id)
            .subquery()
        )

        query = (
            select(
                self.model,
                func.coalesce(media_count_sq.c.media_count, 0).label(
                    "media_count"
                ),
                func.coalesce(asset_count_sq.c.asset_count, 0).label(
                    "asset_count"
                ),
                func.coalesce(subfolder_count_sq.c.subfolder_count, 0).label(
                    "subfolder_count"
                ),
            )
            .outerjoin(
                media_count_sq, self.model.id == media_count_sq.c.folder_id
            )
            .outerjoin(
                asset_count_sq, self.model.id == asset_count_sq.c.folder_id
            )
            .outerjoin(
                subfolder_count_sq,
                self.model.id == subfolder_count_sq.c.parent_id,
            )
            .where(
                self.model.workspace_id == workspace_id,
                self.model.deleted_at.is_(None),
            )
        )

        if parent_id is None:
            query = query.where(self.model.parent_id.is_(None))
        else:
            query = query.where(self.model.parent_id == parent_id)

        query = query.order_by(self.model.name.asc())
        result = await self.db.execute(query)

        folders_list: list[FolderResponseDto] = []
        for row in result.all():
            folder_obj = row[0]
            media_count = row[1]
            asset_count = row[2]
            subfolder_count = row[3]
            folders_list.append(
                FolderResponseDto(
                    id=folder_obj.id,
                    workspace_id=folder_obj.workspace_id,
                    user_id=folder_obj.user_id,
                    user_email=folder_obj.user_email,
                    name=folder_obj.name,
                    parent_id=folder_obj.parent_id,
                    color=folder_obj.color,
                    item_count=media_count + asset_count,
                    subfolder_count=subfolder_count,
                    created_at=folder_obj.created_at,
                    updated_at=folder_obj.updated_at,
                )
            )

        return folders_list

    async def get_breadcrumbs(
        self, folder_id: int
    ) -> list[FolderBreadcrumbDto]:
        """Fetch ancestor hierarchy from root to current folder using recursive CTE."""
        cte_query = text(
            """
            WITH RECURSIVE breadcrumbs AS (
                SELECT id, name, parent_id, 1 AS depth
                FROM folders
                WHERE id = :folder_id AND deleted_at IS NULL
                UNION ALL
                SELECT f.id, f.name, f.parent_id, b.depth + 1
                FROM folders f
                JOIN breadcrumbs b ON f.id = b.parent_id
                WHERE f.deleted_at IS NULL
            )
            SELECT id, name, parent_id FROM breadcrumbs ORDER BY depth DESC;
            """
        )
        result = await self.db.execute(cte_query, {"folder_id": folder_id})
        rows = result.fetchall()
        return [
            FolderBreadcrumbDto(
                id=row.id, name=row.name, parent_id=row.parent_id
            )
            for row in rows
        ]

    async def get_descendant_ids(self, folder_id: int) -> list[int]:
        """Fetch all descendant folder IDs (subfolders, sub-subfolders, etc.) using recursive CTE."""
        cte_query = text(
            """
            WITH RECURSIVE descendants AS (
                SELECT id FROM folders WHERE id = :folder_id AND deleted_at IS NULL
                UNION ALL
                SELECT f.id FROM folders f
                JOIN descendants d ON f.parent_id = d.id
                WHERE f.deleted_at IS NULL
            )
            SELECT id FROM descendants;
            """
        )
        result = await self.db.execute(cte_query, {"folder_id": folder_id})
        return [row.id for row in result.fetchall()]

    async def get_folder_depth(self, folder_id: int) -> int:
        """Returns the depth of a folder from the workspace root (root folder = 1)."""
        breadcrumbs = await self.get_breadcrumbs(folder_id)
        return len(breadcrumbs)

    async def get_subtree_depth(self, folder_id: int) -> int:
        """Returns the maximum depth of the subtree rooted at folder_id (single folder with no subfolders = 1)."""
        cte_query = text(
            """
            WITH RECURSIVE subtree AS (
                SELECT id, 1 AS depth
                FROM folders
                WHERE id = :folder_id AND deleted_at IS NULL
                UNION ALL
                SELECT f.id, s.depth + 1
                FROM folders f
                JOIN subtree s ON f.parent_id = s.id
                WHERE f.deleted_at IS NULL
            )
            SELECT COALESCE(MAX(depth), 0) FROM subtree;
            """
        )
        result = await self.db.execute(cte_query, {"folder_id": folder_id})
        val = result.scalar()
        return int(val) if val is not None else 0

    async def get_tree(self, workspace_id: int) -> list[FolderTreeNodeDto]:
        """Fetch full folder hierarchy tree for a workspace."""
        query = (
            select(self.model)
            .where(
                self.model.workspace_id == workspace_id,
                self.model.deleted_at.is_(None),
            )
            .order_by(self.model.name.asc())
        )
        result = await self.db.execute(query)
        all_folders = result.scalars().all()

        # Build tree in memory
        nodes_by_id: dict[int, FolderTreeNodeDto] = {}
        for f in all_folders:
            nodes_by_id[f.id] = FolderTreeNodeDto(
                id=f.id,
                name=f.name,
                parent_id=f.parent_id,
                color=f.color,
                children=[],
            )

        root_nodes: list[FolderTreeNodeDto] = []
        for f in all_folders:
            node = nodes_by_id[f.id]
            if f.parent_id and f.parent_id in nodes_by_id:
                nodes_by_id[f.parent_id].children.append(node)
            else:
                root_nodes.append(node)

        return root_nodes

    async def soft_delete(
        self, folder_id: int, user_id: int | None = None
    ) -> bool:
        """Soft deletes a folder and all its descendant subfolders."""
        descendant_ids = await self.get_descendant_ids(folder_id)
        if not descendant_ids:
            return False

        now = datetime.now(timezone.utc)

        # 1. Soft-delete all media items in the deleted folder hierarchy
        media_stmt = (
            update(MediaItem)
            .where(
                MediaItem.folder_id.in_(descendant_ids),
                MediaItem.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=user_id)
        )
        await self.db.execute(media_stmt)
        # 2. Soft-delete all source assets in the deleted folder hierarchy
        asset_stmt = (
            update(SourceAsset)
            .where(
                SourceAsset.folder_id.in_(descendant_ids),
                SourceAsset.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=user_id)
        )
        await self.db.execute(asset_stmt)

        stmt = (
            update(self.model)
            .where(self.model.id.in_(descendant_ids))
            .values(deleted_at=now, deleted_by=user_id)
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return True

    async def move_media_items(
        self,
        media_item_ids: list[int],
        workspace_id: int,
        destination_folder_id: int | None,
    ) -> int:
        """Move multiple media items to a destination folder."""
        if not media_item_ids:
            return 0
        stmt = (
            update(MediaItem)
            .where(
                MediaItem.id.in_(media_item_ids),
                MediaItem.workspace_id == workspace_id,
            )
            .values(folder_id=destination_folder_id)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def move_source_assets(
        self,
        source_asset_ids: list[int],
        workspace_id: int,
        destination_folder_id: int | None,
    ) -> int:
        """Move multiple source assets to a destination folder."""
        if not source_asset_ids:
            return 0
        stmt = (
            update(SourceAsset)
            .where(
                SourceAsset.id.in_(source_asset_ids),
                SourceAsset.workspace_id == workspace_id,
            )
            .values(folder_id=destination_folder_id)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def move_folders(
        self,
        folder_ids: list[int],
        workspace_id: int,
        destination_folder_id: int | None,
        conflict_strategy: ConflictStrategyEnum = ConflictStrategyEnum.KEEP_BOTH,
        user_id: int | None = None,
        user_email: str | None = None,
    ) -> int:
        """Move multiple folders to a destination parent folder with automatic name disambiguation or merge."""
        if not folder_ids:
            return 0

        # Query all folders to move
        query = select(self.model).where(
            self.model.id.in_(folder_ids),
            self.model.workspace_id == workspace_id,
            self.model.deleted_at.is_(None),
        )
        result = await self.db.execute(query)
        folders = result.scalars().all()
        if not folders:
            return 0

        if conflict_strategy == ConflictStrategyEnum.MERGE:
            existing_map = await self.get_existing_folders_map(
                workspace_id=workspace_id,
                parent_id=destination_folder_id,
                exclude_folder_ids=folder_ids,
            )
            moved_count = 0
            for f in folders:
                if f.parent_id == destination_folder_id:
                    continue
                name_key = f.name.strip().lower()
                if name_key in existing_map:
                    target_folder = existing_map[name_key]
                    await self.merge_folders(
                        source_folder_id=f.id,
                        target_folder_id=target_folder.id,
                        target_workspace_id=workspace_id,
                        user_id=user_id or f.user_id,
                        user_email=user_email or f.user_email,
                        is_copy=False,
                        clear_tags=False,
                    )
                    moved_count += 1
                else:
                    f.parent_id = destination_folder_id
                    existing_map[name_key] = f
                    moved_count += 1
            await self.db.commit()
            return moved_count

        # Existing KEEP_BOTH:
        existing_names = await self.get_existing_folder_names(
            workspace_id=workspace_id,
            parent_id=destination_folder_id,
        )
        for f in folders:
            if f.parent_id == destination_folder_id:
                existing_names.discard(f.name.strip().lower())

        moved_count = 0
        for f in folders:
            if f.parent_id != destination_folder_id:
                new_name = generate_disambiguated_name(f.name, existing_names)
                f.name = new_name
                f.parent_id = destination_folder_id
                existing_names.add(new_name.strip().lower())
                moved_count += 1

        await self.db.commit()
        return moved_count

    async def copy_media_items(
        self,
        media_item_ids: list[int],
        workspace_id: int,
        destination_folder_id: int | None,
        user_id: int | None = None,
        user_email: str | None = None,
    ) -> int:
        """Copy multiple media items to a destination folder within the same workspace."""
        if not media_item_ids:
            return 0
        stmt = select(MediaItem).where(
            MediaItem.id.in_(media_item_ids),
            MediaItem.workspace_id == workspace_id,
            MediaItem.deleted_at.is_(None),
        )
        res = await self.db.execute(stmt)
        items = res.scalars().all()
        if not items:
            return 0

        media_exclude = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "workspace_id",
            "folder_id",
            "user_id",
            "user_email",
        }
        media_columns = [
            c.key
            for c in MediaItem.__table__.columns
            if c.key not in media_exclude
        ]

        pairs: list[tuple[int, MediaItem]] = []
        for item in items:
            kwargs = {}
            for col in media_columns:
                val = getattr(item, col)
                if isinstance(val, (list, dict)):
                    val = copy.deepcopy(val)
                kwargs[col] = val

            new_media = MediaItem(
                workspace_id=workspace_id,
                folder_id=destination_folder_id,
                user_id=user_id or item.user_id,
                user_email=user_email or item.user_email,
                **kwargs,
            )
            self.db.add(new_media)
            pairs.append((item.id, new_media))

        await self.db.flush()

        old_media_ids = [p[0] for p in pairs]
        media_tags_stmt = select(media_item_tags).where(
            media_item_tags.c.media_item_id.in_(old_media_ids)
        )
        media_tags_res = await self.db.execute(media_tags_stmt)
        media_tag_rows = media_tags_res.fetchall()

        old_to_new = {
            p[0]: p[1].id
            for p in pairs
            if getattr(p[1], "id", None) is not None
        }
        new_tag_inserts = [
            {
                "media_item_id": old_to_new[row.media_item_id],
                "tag_id": row.tag_id,
            }
            for row in media_tag_rows
            if row.media_item_id in old_to_new
        ]
        if new_tag_inserts:
            await self.db.execute(insert(media_item_tags), new_tag_inserts)

        await self.db.commit()
        return len(pairs)

    async def copy_source_assets(
        self,
        source_asset_ids: list[int],
        workspace_id: int,
        destination_folder_id: int | None,
        user_id: int | None = None,
    ) -> int:
        """Copy multiple source assets to a destination folder within the same workspace."""
        if not source_asset_ids:
            return 0
        stmt = select(SourceAsset).where(
            SourceAsset.id.in_(source_asset_ids),
            SourceAsset.workspace_id == workspace_id,
            SourceAsset.deleted_at.is_(None),
        )
        res = await self.db.execute(stmt)
        assets = res.scalars().all()
        if not assets:
            return 0

        asset_exclude = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "workspace_id",
            "folder_id",
            "user_id",
        }
        asset_columns = [
            c.key
            for c in SourceAsset.__table__.columns
            if c.key not in asset_exclude
        ]

        pairs: list[tuple[int, SourceAsset]] = []
        for asset in assets:
            kwargs = {}
            for col in asset_columns:
                val = getattr(asset, col)
                if isinstance(val, (list, dict)):
                    val = copy.deepcopy(val)
                kwargs[col] = val

            new_asset = SourceAsset(
                workspace_id=workspace_id,
                folder_id=destination_folder_id,
                user_id=user_id or asset.user_id,
                **kwargs,
            )
            self.db.add(new_asset)
            pairs.append((asset.id, new_asset))

        await self.db.flush()

        old_asset_ids = [p[0] for p in pairs]
        asset_tags_stmt = select(source_asset_tags).where(
            source_asset_tags.c.source_asset_id.in_(old_asset_ids)
        )
        asset_tags_res = await self.db.execute(asset_tags_stmt)
        asset_tag_rows = asset_tags_res.fetchall()

        old_to_new = {
            p[0]: p[1].id
            for p in pairs
            if getattr(p[1], "id", None) is not None
        }
        new_tag_inserts = [
            {
                "source_asset_id": old_to_new[row.source_asset_id],
                "tag_id": row.tag_id,
            }
            for row in asset_tag_rows
            if row.source_asset_id in old_to_new
        ]
        if new_tag_inserts:
            await self.db.execute(insert(source_asset_tags), new_tag_inserts)

        await self.db.commit()
        return len(pairs)

    async def copy_folders(
        self,
        folder_ids: list[int],
        workspace_id: int,
        destination_folder_id: int | None,
        conflict_strategy: ConflictStrategyEnum = ConflictStrategyEnum.KEEP_BOTH,
        user_id: int | None = None,
        user_email: str | None = None,
    ) -> dict[str, int]:
        """Copies multiple folders to a destination parent folder within the same workspace with conflict handling."""
        if not folder_ids:
            return {
                "folders_copied": 0,
                "media_copied": 0,
                "assets_copied": 0,
            }

        query = select(self.model).where(
            self.model.id.in_(folder_ids),
            self.model.workspace_id == workspace_id,
            self.model.deleted_at.is_(None),
        )
        res = await self.db.execute(query)
        folders = res.scalars().all()
        if not folders:
            return {
                "folders_copied": 0,
                "media_copied": 0,
                "assets_copied": 0,
            }

        total_folders = 0
        total_media = 0
        total_assets = 0

        existing_names = await self.get_existing_folder_names(
            workspace_id=workspace_id,
            parent_id=destination_folder_id,
        )

        for f in folders:
            if conflict_strategy == ConflictStrategyEnum.MERGE:
                existing_target = await self.get_folder_by_name(
                    workspace_id=workspace_id,
                    parent_id=destination_folder_id,
                    name=f.name,
                )
                if existing_target and existing_target.id != f.id:
                    merge_res = await self.merge_folders(
                        source_folder_id=f.id,
                        target_folder_id=existing_target.id,
                        target_workspace_id=workspace_id,
                        user_id=user_id or f.user_id,
                        user_email=user_email or f.user_email,
                        is_copy=True,
                        clear_tags=False,
                    )
                    total_folders += merge_res.get("folders_copied", 1)
                    total_media += merge_res.get("media_copied", 0)
                    total_assets += merge_res.get("assets_copied", 0)
                    continue

            disambiguated_name = generate_disambiguated_name(
                f.name, existing_names
            )
            existing_names.add(disambiguated_name.strip().lower())
            sub_res = await self._copy_subtree_under(
                subtree_root_id=f.id,
                new_parent_id=destination_folder_id,
                target_workspace_id=workspace_id,
                user_id=user_id or f.user_id,
                user_email=user_email or f.user_email,
                root_name_override=disambiguated_name,
            )
            total_folders += sub_res.get("folders_copied", 0)
            total_media += sub_res.get("media_copied", 0)
            total_assets += sub_res.get("assets_copied", 0)

        return {
            "folders_copied": total_folders,
            "media_copied": total_media,
            "assets_copied": total_assets,
        }

    async def copy_items(
        self,
        workspace_id: int,
        media_item_ids: list[int],
        source_asset_ids: list[int],
        folder_ids: list[int],
        destination_folder_id: int | None,
        conflict_strategy: ConflictStrategyEnum = ConflictStrategyEnum.KEEP_BOTH,
        user_id: int | None = None,
        user_email: str | None = None,
    ) -> dict[str, int]:
        """Batch copy media items, source assets, and folders within a workspace."""
        media_copied = await self.copy_media_items(
            media_item_ids=media_item_ids,
            workspace_id=workspace_id,
            destination_folder_id=destination_folder_id,
            user_id=user_id,
            user_email=user_email,
        )
        assets_copied = await self.copy_source_assets(
            source_asset_ids=source_asset_ids,
            workspace_id=workspace_id,
            destination_folder_id=destination_folder_id,
            user_id=user_id,
        )
        folders_res = await self.copy_folders(
            folder_ids=folder_ids,
            workspace_id=workspace_id,
            destination_folder_id=destination_folder_id,
            conflict_strategy=conflict_strategy,
            user_id=user_id,
            user_email=user_email,
        )
        folders_copied = folders_res.get("folders_copied", 0)
        media_copied += folders_res.get("media_copied", 0)
        assets_copied += folders_res.get("assets_copied", 0)

        return {
            "media_items_copied": media_copied,
            "source_assets_copied": assets_copied,
            "folders_copied": folders_copied,
            "total_copied": media_copied + assets_copied + folders_copied,
        }

    async def move_folder_to_workspace(
        self,
        folder_id: int,
        target_workspace_id: int,
        user_id: int | None = None,
        conflict_strategy: ConflictStrategyEnum = ConflictStrategyEnum.KEEP_BOTH,
    ) -> dict[str, int]:
        """Moves a folder hierarchy and all contained media items and source assets to a target workspace with conflict handling."""
        root_folder = await self.get_folder_by_id(folder_id)
        if not root_folder:
            return {"folders_moved": 0, "media_moved": 0, "assets_moved": 0}

        descendant_ids = await self.get_descendant_ids(folder_id)
        if not descendant_ids:
            return {"folders_moved": 0, "media_moved": 0, "assets_moved": 0}

        if conflict_strategy == ConflictStrategyEnum.MERGE:
            existing_target = await self.get_folder_by_name(
                workspace_id=target_workspace_id,
                parent_id=None,
                name=root_folder.name,
                exclude_folder_id=(
                    folder_id
                    if root_folder.workspace_id == target_workspace_id
                    else None
                ),
            )
            if existing_target:
                return await self.merge_folders(
                    source_folder_id=root_folder.id,
                    target_folder_id=existing_target.id,
                    target_workspace_id=target_workspace_id,
                    user_id=user_id or root_folder.user_id,
                    user_email=root_folder.user_email,
                    is_copy=False,
                    clear_tags=(
                        root_folder.workspace_id != target_workspace_id
                    ),
                )

        # Check for name collision at root level of target workspace
        existing_root_names = await self.get_existing_folder_names(
            workspace_id=target_workspace_id,
            parent_id=None,
        )
        disambiguated_name = generate_disambiguated_name(
            root_folder.name, existing_root_names
        )

        if root_folder.workspace_id != target_workspace_id:
            # Remove tag associations from media items and source assets being moved across workspaces
            media_tags_delete = delete(media_item_tags).where(
                media_item_tags.c.media_item_id.in_(
                    select(MediaItem.id).where(
                        MediaItem.folder_id.in_(descendant_ids)
                    )
                )
            )
            await self.db.execute(media_tags_delete)

            asset_tags_delete = delete(source_asset_tags).where(
                source_asset_tags.c.source_asset_id.in_(
                    select(SourceAsset.id).where(
                        SourceAsset.folder_id.in_(descendant_ids)
                    )
                )
            )
            await self.db.execute(asset_tags_delete)

        # 1. Update media items belonging to any folder in the subtree
        media_stmt = (
            update(MediaItem)
            .where(MediaItem.folder_id.in_(descendant_ids))
            .values(workspace_id=target_workspace_id)
        )
        media_res = await self.db.execute(media_stmt)

        # 2. Update source assets belonging to any folder in the subtree
        asset_stmt = (
            update(SourceAsset)
            .where(SourceAsset.folder_id.in_(descendant_ids))
            .values(workspace_id=target_workspace_id)
        )
        asset_res = await self.db.execute(asset_stmt)

        # 3. Update descendant child folders (excluding the root folder being moved)
        child_folder_ids = [fid for fid in descendant_ids if fid != folder_id]
        if child_folder_ids:
            child_folders_stmt = (
                update(Folder)
                .where(
                    Folder.id.in_(child_folder_ids),
                    Folder.deleted_at.is_(None),
                )
                .values(workspace_id=target_workspace_id)
            )
            await self.db.execute(child_folders_stmt)

        # 4. Update the root folder being moved: set workspace_id, reset parent_id to None, and apply disambiguated name
        root_folder.workspace_id = target_workspace_id
        root_folder.parent_id = None
        root_folder.name = disambiguated_name

        await self.db.commit()

        return {
            "folders_moved": len(descendant_ids),
            "media_moved": media_res.rowcount,
            "assets_moved": asset_res.rowcount,
        }

    async def merge_folders(
        self,
        source_folder_id: int,
        target_folder_id: int,
        target_workspace_id: int,
        user_id: int | None = None,
        user_email: str | None = None,
        is_copy: bool = False,
        clear_tags: bool = False,
    ) -> dict[str, int]:
        """Recursively merges source folder into target folder."""
        source_folder = await self.get_folder_by_id(source_folder_id)
        target_folder = await self.get_folder_by_id(target_folder_id)
        if not source_folder or not target_folder:
            key_f = "folders_copied" if is_copy else "folders_moved"
            key_m = "media_copied" if is_copy else "media_moved"
            key_a = "assets_copied" if is_copy else "assets_moved"
            return {key_f: 0, key_m: 0, key_a: 0}

        # 1. Media items directly in source_folder
        media_stmt = select(MediaItem).where(
            MediaItem.folder_id == source_folder_id,
            MediaItem.deleted_at.is_(None),
        )
        media_res = await self.db.execute(media_stmt)
        source_media_items = media_res.scalars().all()
        media_count = 0

        media_exclude = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "workspace_id",
            "folder_id",
            "user_id",
            "user_email",
        }
        media_columns = [
            c.key
            for c in MediaItem.__table__.columns
            if c.key not in media_exclude
        ]

        if is_copy:
            for item in source_media_items:
                kwargs = {
                    col: (
                        copy.deepcopy(getattr(item, col))
                        if isinstance(getattr(item, col), (list, dict))
                        else getattr(item, col)
                    )
                    for col in media_columns
                }
                new_media = MediaItem(
                    workspace_id=target_workspace_id,
                    folder_id=target_folder_id,
                    user_id=user_id or source_folder.user_id,
                    user_email=user_email or item.user_email,
                    **kwargs,
                )
                self.db.add(new_media)
                media_count += 1
        else:
            if source_media_items:
                media_ids = [m.id for m in source_media_items]
                if clear_tags:
                    await self.db.execute(
                        delete(media_item_tags).where(
                            media_item_tags.c.media_item_id.in_(media_ids)
                        )
                    )
                await self.db.execute(
                    update(MediaItem)
                    .where(MediaItem.folder_id == source_folder_id)
                    .values(
                        folder_id=target_folder_id,
                        workspace_id=target_workspace_id,
                    )
                )
                media_count += len(source_media_items)

        # 2. Source Assets directly in source_folder
        asset_stmt = select(SourceAsset).where(
            SourceAsset.folder_id == source_folder_id,
            SourceAsset.deleted_at.is_(None),
        )
        asset_res = await self.db.execute(asset_stmt)
        source_assets = asset_res.scalars().all()
        assets_count = 0

        asset_exclude = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "workspace_id",
            "folder_id",
            "user_id",
        }
        asset_columns = [
            c.key
            for c in SourceAsset.__table__.columns
            if c.key not in asset_exclude
        ]

        if is_copy:
            for asset in source_assets:
                kwargs = {
                    col: (
                        copy.deepcopy(getattr(asset, col))
                        if isinstance(getattr(asset, col), (list, dict))
                        else getattr(asset, col)
                    )
                    for col in asset_columns
                }
                new_asset = SourceAsset(
                    workspace_id=target_workspace_id,
                    folder_id=target_folder_id,
                    user_id=user_id or source_folder.user_id,
                    **kwargs,
                )
                self.db.add(new_asset)
                assets_count += 1
        else:
            if source_assets:
                asset_ids = [a.id for a in source_assets]
                if clear_tags:
                    await self.db.execute(
                        delete(source_asset_tags).where(
                            source_asset_tags.c.source_asset_id.in_(asset_ids)
                        )
                    )
                await self.db.execute(
                    update(SourceAsset)
                    .where(SourceAsset.folder_id == source_folder_id)
                    .values(
                        folder_id=target_folder_id,
                        workspace_id=target_workspace_id,
                    )
                )
                assets_count += len(source_assets)

        # 3. Direct child subfolders of source_folder
        source_children_stmt = select(Folder).where(
            Folder.parent_id == source_folder_id,
            Folder.deleted_at.is_(None),
        )
        source_children_res = await self.db.execute(source_children_stmt)
        source_children = source_children_res.scalars().all()

        target_children_stmt = select(Folder).where(
            Folder.parent_id == target_folder_id,
            Folder.deleted_at.is_(None),
        )
        target_children_res = await self.db.execute(target_children_stmt)
        target_children = target_children_res.scalars().all()
        target_children_map = {
            c.name.strip().lower(): c for c in target_children
        }

        folders_count = 1
        for child in source_children:
            child_name_key = child.name.strip().lower()
            if child_name_key in target_children_map:
                # Collision in subfolder -> recursive merge!
                target_child = target_children_map[child_name_key]
                sub_res = await self.merge_folders(
                    source_folder_id=child.id,
                    target_folder_id=target_child.id,
                    target_workspace_id=target_workspace_id,
                    user_id=user_id,
                    user_email=user_email,
                    is_copy=is_copy,
                    clear_tags=clear_tags,
                )
                folders_count += sub_res.get(
                    "folders_copied", sub_res.get("folders_moved", 1)
                )
                media_count += sub_res.get(
                    "media_copied", sub_res.get("media_moved", 0)
                )
                assets_count += sub_res.get(
                    "assets_copied", sub_res.get("assets_moved", 0)
                )
            else:
                if is_copy:
                    sub_copy_res = await self._copy_subtree_under(
                        subtree_root_id=child.id,
                        new_parent_id=target_folder_id,
                        target_workspace_id=target_workspace_id,
                        user_id=user_id or source_folder.user_id,
                        user_email=user_email or child.user_email,
                    )
                    folders_count += sub_copy_res.get("folders_copied", 0)
                    media_count += sub_copy_res.get("media_copied", 0)
                    assets_count += sub_copy_res.get("assets_copied", 0)
                else:
                    child.parent_id = target_folder_id
                    child_descendants = await self.get_descendant_ids(child.id)
                    folders_count += len(child_descendants)
                    if child.workspace_id != target_workspace_id:
                        if clear_tags:
                            await self.db.execute(
                                delete(media_item_tags).where(
                                    media_item_tags.c.media_item_id.in_(
                                        select(MediaItem.id).where(
                                            MediaItem.folder_id.in_(
                                                child_descendants
                                            )
                                        )
                                    )
                                )
                            )
                            await self.db.execute(
                                delete(source_asset_tags).where(
                                    source_asset_tags.c.source_asset_id.in_(
                                        select(SourceAsset.id).where(
                                            SourceAsset.folder_id.in_(
                                                child_descendants
                                            )
                                        )
                                    )
                                )
                            )
                        await self.db.execute(
                            update(Folder)
                            .where(
                                Folder.id.in_(child_descendants),
                                Folder.deleted_at.is_(None),
                            )
                            .values(workspace_id=target_workspace_id)
                        )
                        await self.db.execute(
                            update(MediaItem)
                            .where(MediaItem.folder_id.in_(child_descendants))
                            .values(workspace_id=target_workspace_id)
                        )
                        await self.db.execute(
                            update(SourceAsset)
                            .where(SourceAsset.folder_id.in_(child_descendants))
                            .values(workspace_id=target_workspace_id)
                        )

        # 4. On move, soft-delete the emptied source folder
        if not is_copy:
            source_folder.deleted_at = datetime.now(timezone.utc)
            source_folder.deleted_by = user_id

        await self.db.commit()

        key_f = "folders_copied" if is_copy else "folders_moved"
        key_m = "media_copied" if is_copy else "media_moved"
        key_a = "assets_copied" if is_copy else "assets_moved"
        return {
            key_f: folders_count,
            key_m: media_count,
            key_a: assets_count,
        }

    async def _insert_copied_hierarchy(
        self,
        folder_rows: list,
        subtree_root_id: int,
        new_parent_id: int | None,
        target_workspace_id: int,
        user_id: int,
        user_email: str | None = None,
        root_name_override: str | None = None,
        source_workspace_id: int | None = None,
    ) -> dict[str, int]:
        """Inserts copied folders, media items, and assets for given folder_rows."""
        depth_map: dict[int, list] = {}
        row_depth_map: dict[int, int] = {}
        for row in folder_rows:
            if isinstance(getattr(row, "depth", None), int):
                depth = row.depth
            elif row.id == subtree_root_id or row.parent_id is None:
                depth = 0
            else:
                depth = row_depth_map.get(row.parent_id, 0) + 1
            row_depth_map[row.id] = depth
            depth_map.setdefault(depth, []).append(row)

        id_map: dict[int, int] = {}
        for depth in sorted(depth_map.keys()):
            folders_at_depth: list[tuple[int, Folder]] = []
            for row in depth_map[depth]:
                if row.id == subtree_root_id:
                    new_folder = Folder(
                        workspace_id=target_workspace_id,
                        user_id=user_id,
                        user_email=user_email or "",
                        name=root_name_override or row.name,
                        parent_id=new_parent_id,
                        color=row.color,
                    )
                else:
                    new_parent = id_map.get(row.parent_id)
                    new_folder = Folder(
                        workspace_id=target_workspace_id,
                        user_id=user_id,
                        user_email=user_email or "",
                        name=row.name,
                        parent_id=new_parent,
                        color=row.color,
                    )
                self.db.add(new_folder)
                folders_at_depth.append((row.id, new_folder))

            await self.db.flush()
            for old_id, new_folder in folders_at_depth:
                id_map[old_id] = new_folder.id

        old_folder_ids = list(id_map.keys())

        # Copy media items in any of the copied folders
        media_stmt = select(MediaItem).where(
            MediaItem.folder_id.in_(old_folder_ids),
            MediaItem.deleted_at.is_(None),
        )
        media_res = await self.db.execute(media_stmt)
        media_items = media_res.scalars().all()

        media_exclude = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "workspace_id",
            "folder_id",
            "user_id",
            "user_email",
        }
        media_columns = [
            c.key
            for c in MediaItem.__table__.columns
            if c.key not in media_exclude
        ]

        media_copied_count = 0
        media_pairs: list[tuple[int, MediaItem]] = []
        for item in media_items:
            kwargs = {}
            for col in media_columns:
                val = getattr(item, col)
                if isinstance(val, (list, dict)):
                    val = copy.deepcopy(val)
                kwargs[col] = val

            new_media = MediaItem(
                workspace_id=target_workspace_id,
                folder_id=id_map[item.folder_id],
                user_id=user_id,
                user_email=user_email or item.user_email,
                **kwargs,
            )
            self.db.add(new_media)
            media_pairs.append((item.id, new_media))
            media_copied_count += 1

        # Copy source assets in any of the copied folders
        asset_stmt = select(SourceAsset).where(
            SourceAsset.folder_id.in_(old_folder_ids),
            SourceAsset.deleted_at.is_(None),
        )
        asset_res = await self.db.execute(asset_stmt)
        assets = asset_res.scalars().all()

        asset_exclude = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "workspace_id",
            "folder_id",
            "user_id",
        }
        asset_columns = [
            c.key
            for c in SourceAsset.__table__.columns
            if c.key not in asset_exclude
        ]

        assets_copied_count = 0
        asset_pairs: list[tuple[int, SourceAsset]] = []
        for asset in assets:
            kwargs = {}
            for col in asset_columns:
                val = getattr(asset, col)
                if isinstance(val, (list, dict)):
                    val = copy.deepcopy(val)
                kwargs[col] = val

            new_asset = SourceAsset(
                workspace_id=target_workspace_id,
                folder_id=id_map[asset.folder_id],
                user_id=user_id,
                **kwargs,
            )
            self.db.add(new_asset)
            asset_pairs.append((asset.id, new_asset))
            assets_copied_count += 1

        if (
            source_workspace_id is not None
            and source_workspace_id == target_workspace_id
            and (media_pairs or asset_pairs)
        ):
            await self.db.flush()
            if media_pairs:
                old_media_ids = [p[0] for p in media_pairs]
                media_tags_stmt = select(media_item_tags).where(
                    media_item_tags.c.media_item_id.in_(old_media_ids)
                )
                media_tags_res = await self.db.execute(media_tags_stmt)
                media_tag_rows = media_tags_res.fetchall()
                old_to_new_media = {
                    p[0]: p[1].id
                    for p in media_pairs
                    if getattr(p[1], "id", None) is not None
                }
                new_media_tag_inserts = [
                    {
                        "media_item_id": old_to_new_media[row.media_item_id],
                        "tag_id": row.tag_id,
                    }
                    for row in media_tag_rows
                    if row.media_item_id in old_to_new_media
                ]
                if new_media_tag_inserts:
                    await self.db.execute(
                        insert(media_item_tags), new_media_tag_inserts
                    )

            if asset_pairs:
                old_asset_ids = [p[0] for p in asset_pairs]
                asset_tags_stmt = select(source_asset_tags).where(
                    source_asset_tags.c.source_asset_id.in_(old_asset_ids)
                )
                asset_tags_res = await self.db.execute(asset_tags_stmt)
                asset_tag_rows = asset_tags_res.fetchall()
                old_to_new_asset = {
                    p[0]: p[1].id
                    for p in asset_pairs
                    if getattr(p[1], "id", None) is not None
                }
                new_asset_tag_inserts = [
                    {
                        "source_asset_id": old_to_new_asset[
                            row.source_asset_id
                        ],
                        "tag_id": row.tag_id,
                    }
                    for row in asset_tag_rows
                    if row.source_asset_id in old_to_new_asset
                ]
                if new_asset_tag_inserts:
                    await self.db.execute(
                        insert(source_asset_tags), new_asset_tag_inserts
                    )

        await self.db.commit()

        return {
            "folders_copied": len(id_map),
            "media_copied": media_copied_count,
            "assets_copied": assets_copied_count,
        }

    async def _copy_subtree_under(
        self,
        subtree_root_id: int,
        new_parent_id: int | None,
        target_workspace_id: int,
        user_id: int,
        user_email: str | None = None,
        root_name_override: str | None = None,
    ) -> dict[str, int]:
        """Copies a folder subtree under new_parent_id with batch level insertions."""
        root_folder = await self.get_folder_by_id(subtree_root_id)
        if not root_folder:
            return {"folders_copied": 0, "media_copied": 0, "assets_copied": 0}

        cte_query = text(
            """
            WITH RECURSIVE descendants AS (
                SELECT id, name, color, parent_id, 0 AS depth
                FROM folders
                WHERE id = :folder_id AND deleted_at IS NULL
                UNION ALL
                SELECT f.id, f.name, f.color, f.parent_id, d.depth + 1 AS depth
                FROM folders f
                JOIN descendants d ON f.parent_id = d.id
                WHERE f.deleted_at IS NULL
            )
            SELECT id, name, color, parent_id, depth FROM descendants ORDER BY depth ASC, id ASC;
            """
        )
        res = await self.db.execute(cte_query, {"folder_id": subtree_root_id})
        folder_rows = res.fetchall()
        if not folder_rows:
            return {"folders_copied": 0, "media_copied": 0, "assets_copied": 0}

        return await self._insert_copied_hierarchy(
            folder_rows=folder_rows,
            subtree_root_id=subtree_root_id,
            new_parent_id=new_parent_id,
            target_workspace_id=target_workspace_id,
            user_id=user_id,
            user_email=user_email or root_folder.user_email,
            root_name_override=root_name_override,
            source_workspace_id=root_folder.workspace_id,
        )

    async def copy_folder_to_workspace(
        self,
        folder_id: int,
        target_workspace_id: int,
        user_id: int,
        user_email: str | None = None,
        conflict_strategy: ConflictStrategyEnum = ConflictStrategyEnum.KEEP_BOTH,
    ) -> dict[str, int]:
        """Copies a folder hierarchy and all contained media items and source assets to a target workspace with conflict handling."""
        root_folder = await self.get_folder_by_id(folder_id)
        if not root_folder:
            return {"folders_copied": 0, "media_copied": 0, "assets_copied": 0}

        if conflict_strategy == ConflictStrategyEnum.MERGE:
            existing_target = await self.get_folder_by_name(
                workspace_id=target_workspace_id,
                parent_id=None,
                name=root_folder.name,
                exclude_folder_id=(
                    folder_id
                    if root_folder.workspace_id == target_workspace_id
                    else None
                ),
            )
            if existing_target:
                return await self.merge_folders(
                    source_folder_id=root_folder.id,
                    target_folder_id=existing_target.id,
                    target_workspace_id=target_workspace_id,
                    user_id=user_id,
                    user_email=user_email or root_folder.user_email,
                    is_copy=True,
                    clear_tags=(
                        root_folder.workspace_id != target_workspace_id
                    ),
                )

        cte_query = text(
            """
            WITH RECURSIVE descendants AS (
                SELECT id, name, color, parent_id, 0 AS depth
                FROM folders
                WHERE id = :folder_id AND deleted_at IS NULL
                UNION ALL
                SELECT f.id, f.name, f.color, f.parent_id, d.depth + 1 AS depth
                FROM folders f
                JOIN descendants d ON f.parent_id = d.id
                WHERE f.deleted_at IS NULL
            )
            SELECT id, name, color, parent_id, depth FROM descendants ORDER BY depth ASC, id ASC;
            """
        )
        res = await self.db.execute(cte_query, {"folder_id": folder_id})
        folder_rows = res.fetchall()
        if not folder_rows:
            return {"folders_copied": 0, "media_copied": 0, "assets_copied": 0}

        # Check for name collision at root level of target workspace
        existing_root_names = await self.get_existing_folder_names(
            workspace_id=target_workspace_id,
            parent_id=None,
        )
        disambiguated_root_name = generate_disambiguated_name(
            root_folder.name, existing_root_names
        )

        return await self._insert_copied_hierarchy(
            folder_rows=folder_rows,
            subtree_root_id=folder_id,
            new_parent_id=None,
            target_workspace_id=target_workspace_id,
            user_id=user_id,
            user_email=user_email or root_folder.user_email,
            root_name_override=disambiguated_root_name,
            source_workspace_id=root_folder.workspace_id,
        )
