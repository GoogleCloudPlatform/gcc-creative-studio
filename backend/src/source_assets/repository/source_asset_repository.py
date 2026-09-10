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


from fastapi import Depends
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.database import get_db
from src.source_assets.dto.source_asset_search_dto import SourceAssetSearchDto
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
    SourceAssetModel,
)


class SourceAssetRepository(BaseRepository[SourceAsset, SourceAssetModel]):
    """Handles database operations for SourceAsset objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=SourceAsset, schema=SourceAssetModel, db=db)

    async def find_by_hash(
        self,
        user_id: int,
        file_hash: str,
        workspace_id: int,
    ) -> SourceAssetModel | None:
        """Finds a user asset by its file hash and workspace ID to prevent duplicates."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
            .where(self.model.file_hash == file_hash)
            .where(self.model.workspace_id == workspace_id)
            .limit(1),
        )
        asset = result.scalar_one_or_none()
        if not asset:
            return None
        return self.schema.model_validate(asset)

    async def find_by_external_url(
        self,
        user_id: int,
        external_url: str,
    ) -> SourceAssetModel | None:
        """Finds a user asset by its external URL to prevent duplicates."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
            .where(self.model.external_url == external_url)
            .limit(1),
        )
        asset = result.scalar_one_or_none()
        if not asset:
            return None
        return self.schema.model_validate(asset)

    async def query(
        self,
        search_dto: SourceAssetSearchDto,
        target_user_id: int | None = None,
    ) -> PaginationResponseDto[SourceAssetModel]:
        """Performs a paginated query for assets."""
        query = select(self.model)

        # Apply filters
        if search_dto.mime_type:
            if search_dto.mime_type == "image/*":
                # Filter for all image types using SQL LIKE
                query = query.where(self.model.mime_type.like("image/%"))
            elif search_dto.mime_type == "video/*":
                # Filter for all video types
                query = query.where(self.model.mime_type.like("video/%"))
            elif search_dto.mime_type == "audio/*":
                # Filter for all audio types
                query = query.where(self.model.mime_type.like("audio/%"))
            else:
                # Exact match for specific mime types like "image/png"
                query = query.where(
                    self.model.mime_type == search_dto.mime_type
                )

        if target_user_id:
            query = query.where(self.model.user_id == target_user_id)

        if search_dto.scope:
            query = query.where(self.model.scope == search_dto.scope.value)

        if search_dto.asset_type:
            query = query.where(
                self.model.asset_type == search_dto.asset_type.value
            )

        if search_dto.original_filename:
            # Prefix search
            query = query.where(
                self.model.original_filename.like(
                    f"{search_dto.original_filename}%"
                ),
            )

        if hasattr(search_dto, "workspace_id") and search_dto.workspace_id:
            query = query.where(
                self.model.workspace_id == search_dto.workspace_id
            )

        if hasattr(search_dto, "tags") and search_dto.tags:
            from sqlalchemy import exists
            from src.tags.schema.tags_model import source_asset_tags, Tag

            for tag_name in search_dto.tags:
                query = query.where(
                    select(source_asset_tags.c.source_asset_id)
                    .join(Tag, Tag.id == source_asset_tags.c.tag_id)
                    .where(source_asset_tags.c.source_asset_id == self.model.id)
                    .where(Tag.name == tag_name)
                    .exists()
                )

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar_one()

        # Order and Pagination
        query = query.order_by(self.model.created_at.desc())
        query = query.limit(search_dto.limit)

        # Execute
        result = await self.db.execute(query)
        assets = result.scalars().all()

        asset_data = [self.schema.model_validate(asset) for asset in assets]

        # Calculate pagination metadata
        page = (search_dto.offset // search_dto.limit) + 1
        page_size = search_dto.limit
        total_pages = (total_count + page_size - 1) // page_size

        return PaginationResponseDto[SourceAssetModel](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=asset_data,
        )

    async def find_by_scope_and_types(
        self,
        scope: AssetScopeEnum,
        asset_types: list[AssetTypeEnum],
    ) -> list[SourceAssetModel]:
        """Finds all assets matching a specific scope and a list of asset types."""
        if not asset_types:
            return []

        result = await self.db.execute(
            select(self.model)
            .where(self.model.scope == scope.value)
            .where(self.model.asset_type.in_([t.value for t in asset_types])),
        )
        assets = result.scalars().all()
        return [self.schema.model_validate(asset) for asset in assets]

    async def find_private_by_user_and_types(
        self,
        user_id: int,
        asset_types: list[AssetTypeEnum],
    ) -> list[SourceAssetModel]:
        """Finds all private assets for a specific user that match a list of asset types."""
        if not asset_types:
            return []

        result = await self.db.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
            .where(self.model.scope == AssetScopeEnum.PRIVATE.value)
            .where(self.model.asset_type.in_([t.value for t in asset_types])),
        )
        assets = result.scalars().all()
        return [self.schema.model_validate(asset) for asset in assets]

    async def get_by_gcs_uri(self, gcs_uri: str) -> SourceAssetModel | None:
        """Finds an asset by its GCS URI."""
        result = await self.db.execute(
            select(self.model).where(self.model.gcs_uri == gcs_uri).limit(1),
        )
        asset = result.scalar_one_or_none()
        if not asset:
            return None
        return self.schema.model_validate(asset)

    async def find_system_and_private_assets_by_types(
        self,
        user_id: int,
        asset_types: list[AssetTypeEnum],
    ) -> list[SourceAssetModel]:
        """Finds all system assets AND private assets for a specific user that match a list of asset types.
        This combines two queries into one using OR logic.
        """
        if not asset_types:
            return []

        result = await self.db.execute(
            select(self.model)
            .where(
                or_(
                    self.model.scope == AssetScopeEnum.SYSTEM.value,
                    and_(
                        self.model.user_id == user_id,
                        self.model.scope == AssetScopeEnum.PRIVATE.value,
                    ),
                ),
            )
            .where(self.model.asset_type.in_([t.value for t in asset_types])),
        )
        assets = result.scalars().all()
        return [self.schema.model_validate(asset) for asset in assets]
