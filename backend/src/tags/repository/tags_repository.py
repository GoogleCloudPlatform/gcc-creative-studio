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

from fastapi import Depends
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.media_item_model import MediaItem
from src.database import get_db
from src.source_assets.schema.source_asset_model import SourceAsset
from src.tags.schema.tags_model import (
    Tag,
    TagModel,
    media_item_tags,
    source_asset_tags,
)
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceScopeEnum,
)


class TagsRepository(BaseRepository[Tag, TagModel]):
    """Handles database operations for Tag objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Tag, schema=TagModel, db=db)

    async def get_by_workspace(
        self,
        workspace_id: int,
        search: str | None = None,
        limit: int = 10,
        offset: int = 0,
        user_id: int | None = None,
    ) -> PaginationResponseDto[TagModel]:
        """Retrieves all tags for a specific workspace, optionally filtered by name."""
        query = select(self.model).where(
            self.model.workspace_id == workspace_id
        )

        if search:
            query = query.where(self.model.name.ilike(f"%{search}%"))

        if user_id:
            query = query.where(self.model.user_id == user_id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar_one()

        # Add ordering and pagination
        query = query.order_by(self.model.updated_at.desc())
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        tags = result.scalars().all()
        data = [self.schema.model_validate(tag) for tag in tags]

        page = (offset // limit) + 1
        page_size = limit
        total_pages = (total_count + page_size - 1) // page_size

        return PaginationResponseDto[TagModel](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=data,
        )

    async def list_global_tags(
        self,
        *,
        requesting_user_id: int | None = None,
        search: str | None = None,
        limit: int = 10,
        offset: int = 0,
        user_id: int | None = None,
    ) -> PaginationResponseDto[TagModel]:
        """Lists shared workspace tags, excluding other users' personal workspaces."""
        not_personal = Workspace.scope != WorkspaceScopeEnum.PERSONAL.value
        visibility = (
            or_(not_personal, Workspace.owner_id == requesting_user_id)
            if requesting_user_id is not None
            else not_personal
        )
        query = (
            select(self.model)
            .join(Workspace, self.model.workspace_id == Workspace.id)
            .where(visibility)
        )
        if search:
            query = query.where(self.model.name.ilike(f"%{search}%"))
        if user_id:
            query = query.where(self.model.user_id == user_id)

        total_count = (
            await self.db.execute(
                select(func.count()).select_from(query.subquery())
            )
        ).scalar_one()
        safe_limit = max(limit, 1)
        tags = (
            (
                await self.db.execute(
                    query.order_by(self.model.updated_at.desc())
                    .offset(offset)
                    .limit(safe_limit)
                )
            )
            .scalars()
            .all()
        )
        return PaginationResponseDto[TagModel](
            count=total_count,
            page=(offset // safe_limit) + 1,
            page_size=safe_limit,
            total_pages=(total_count + safe_limit - 1) // safe_limit,
            data=[self.schema.model_validate(t) for t in tags],
        )

    async def find_by_name(
        self, name: str, workspace_id: int
    ) -> TagModel | None:
        """Finds a tag by name within a specific workspace."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.name == name)
            .where(self.model.workspace_id == workspace_id)
            .limit(1)
        )
        tag = result.scalar_one_or_none()
        if not tag:
            return None
        return self.schema.model_validate(tag)

    async def count_by_workspace(self, workspace_id: int) -> int:
        """Counts tags in a workspace."""
        result = await self.db.execute(
            select(func.count(self.model.id)).where(
                self.model.workspace_id == workspace_id
            )
        )
        return result.scalar_one()

    async def assign_tag_to_media_item(self, media_item_id: int, tag_id: int):
        """Links a tag to a media item."""
        await self.db.execute(
            pg_insert(media_item_tags)
            .values(media_item_id=media_item_id, tag_id=tag_id)
            .on_conflict_do_nothing()
        )
        # Update updated_at of the tag to track usage!
        await self.db.execute(
            update(self.model)
            .where(self.model.id == tag_id)
            .values(updated_at=func.now())
        )
        await self.db.commit()

    async def assign_tag_to_source_asset(
        self, source_asset_id: int, tag_id: int
    ):
        """Links a tag to a source asset."""
        await self.db.execute(
            pg_insert(source_asset_tags)
            .values(source_asset_id=source_asset_id, tag_id=tag_id)
            .on_conflict_do_nothing()
        )
        # Update updated_at of the tag to track usage!
        await self.db.execute(
            update(self.model)
            .where(self.model.id == tag_id)
            .values(updated_at=func.now())
        )
        await self.db.commit()

    async def remove_tag_from_media_item(self, media_item_id: int, tag_id: int):
        """Unlinks a tag from a media item."""
        await self.db.execute(
            delete(media_item_tags)
            .where(media_item_tags.c.media_item_id == media_item_id)
            .where(media_item_tags.c.tag_id == tag_id)
        )
        await self.db.commit()

    async def remove_tag_from_source_asset(
        self, source_asset_id: int, tag_id: int
    ):
        """Unlinks a tag from a source asset."""
        await self.db.execute(
            delete(source_asset_tags)
            .where(source_asset_tags.c.source_asset_id == source_asset_id)
            .where(source_asset_tags.c.tag_id == tag_id)
        )
        await self.db.commit()

    async def clear_tags_for_media_item(self, media_item_id: int):
        """Removes all tags from a media item."""
        await self.db.execute(
            delete(media_item_tags).where(
                media_item_tags.c.media_item_id == media_item_id
            )
        )
        await self.db.commit()

    async def clear_tags_for_source_asset(self, source_asset_id: int):
        """Removes all tags from a source asset."""
        await self.db.execute(
            delete(source_asset_tags).where(
                source_asset_tags.c.source_asset_id == source_asset_id
            )
        )
        await self.db.commit()

    async def get_item_workspaces(
        self, item_ids: list[int], item_type: str
    ) -> dict[int, int]:
        """Returns ``{item_id: workspace_id}`` for non-deleted items."""
        if not item_ids:
            return {}
        unique_ids = list(dict.fromkeys(item_ids))
        model = MediaItem if item_type == "media_item" else SourceAsset
        result = await self.db.execute(
            select(model.id, model.workspace_id).where(
                model.id.in_(unique_ids),
                model.deleted_at.is_(None),
            )
        )
        return {row.id: row.workspace_id for row in result.all()}

    async def clear_tags_for_items(
        self, item_ids: list[int], item_type: str, commit: bool = True
    ):
        """Removes all tags from multiple items."""
        table = (
            media_item_tags if item_type == "media_item" else source_asset_tags
        )
        id_col = (
            table.c.media_item_id
            if item_type == "media_item"
            else table.c.source_asset_id
        )
        await self.db.execute(delete(table).where(id_col.in_(item_ids)))
        if commit:
            await self.db.commit()

    async def assign_tags_to_items(
        self,
        item_ids: list[int],
        tag_ids: list[int],
        item_type: str,
        commit: bool = True,
    ):
        """Links multiple tags to multiple items."""
        table = (
            media_item_tags if item_type == "media_item" else source_asset_tags
        )
        id_col_name = (
            "media_item_id" if item_type == "media_item" else "source_asset_id"
        )

        values = []
        for item_id in item_ids:
            for tag_id in tag_ids:
                values.append({id_col_name: item_id, "tag_id": tag_id})

        if values:
            await self.db.execute(
                pg_insert(table).values(values).on_conflict_do_nothing()
            )

            await self.db.execute(
                update(self.model)
                .where(self.model.id.in_(tag_ids))
                .values(updated_at=func.now())
            )

            if commit:
                await self.db.commit()

    async def update_tag(
        self, id: int, name: str | None = None, color: str | None = None
    ) -> TagModel | None:
        """Updates a tag's name and/or color."""
        values = {}
        if name is not None:
            values["name"] = name
        if color is not None:
            values["color"] = color

        if not values:
            return await self.get_by_id(id)

        await self.db.execute(
            update(self.model).where(self.model.id == id).values(**values)
        )
        await self.db.commit()
        return await self.get_by_id(id)

    async def get_tags_for_media_item(
        self, media_item_id: int
    ) -> list[TagModel]:
        """Gets all tags linked to a media item."""
        result = await self.db.execute(
            select(Tag)
            .join(media_item_tags, Tag.id == media_item_tags.c.tag_id)
            .where(media_item_tags.c.media_item_id == media_item_id)
        )
        tags = result.scalars().all()
        return [self.schema.model_validate(tag) for tag in tags]

    async def get_tags_for_source_asset(
        self, source_asset_id: int
    ) -> list[TagModel]:
        """Gets all tags linked to a source asset."""
        result = await self.db.execute(
            select(Tag)
            .join(source_asset_tags, Tag.id == source_asset_tags.c.tag_id)
            .where(source_asset_tags.c.source_asset_id == source_asset_id)
        )
        tags = result.scalars().all()
        return [self.schema.model_validate(tag) for tag in tags]
