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
import datetime
from src.workspaces.schema.workspace_model import Workspace
from src.users.user_model import User


from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.unified_gallery_view import UnifiedGalleryView
from src.database import get_db
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.unified_gallery_response import (
    UnifiedGalleryItemResponse,
)


class UnifiedGalleryRepository(
    BaseRepository[UnifiedGalleryView, UnifiedGalleryItemResponse],
):
    """Repository for accessing the unified_gallery_view."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=UnifiedGalleryView,
            schema=UnifiedGalleryItemResponse,
            db=db,
        )

    async def query(
        self,
        search_dto: GallerySearchDto,
        user_id: int | None = None,
    ) -> PaginationResponseDto[UnifiedGalleryItemResponse]:
        """Performs a paginated query on the unified view.
        user_id is successfully resolved from search_dto.user_email in the Service layer if present.
        """
        # 1. Build the base query
        query = select(self.model)

        # Soft Delete Filter
        if not search_dto.include_deleted:
            query = query.where(self.model.deleted_at.is_(None))

        # External resource filter: filter out external resources if include_external is False
        if not search_dto.include_external:
            query = query.where(
                self.model.metadata_["external_url"].astext.is_(None)
                | (self.model.metadata_["external_url"].astext == "")
            )

        # Filter by workspace (conditional for admins)
        if search_dto.workspace_id is not None:
            query = query.where(
                self.model.workspace_id == search_dto.workspace_id
            )

        # Filter by status
        if search_dto.status:
            # We cast to string because JobStatusEnum is an enum but DB view column is string
            query = query.where(self.model.status == search_dto.status.value)

        # Filter by user_id
        if user_id is not None:
            query = query.where(self.model.user_id == user_id)

        # Filter by user_email directly if provided in search_dto
        if hasattr(search_dto, "user_email") and search_dto.user_email:
            query = query.where(self.model.user_email == search_dto.user_email)

        # Filter by metadata using JSONB operators
        # 1. Mime Type
        if search_dto.mime_type:
            # Use .astext (->>) to get the unquoted string value from JSONB
            mime_val = (
                search_dto.mime_type.value
                if hasattr(search_dto.mime_type, "value")
                else search_dto.mime_type
            )
            if "*" in mime_val:
                # PostgreSQL: metadata->>'mime_type' LIKE 'image/%'
                prefix = mime_val.replace("*", "%")
                query = query.where(
                    self.model.metadata_["mime_type"].astext.like(prefix),
                )
            else:
                query = query.where(
                    self.model.metadata_["mime_type"].astext == mime_val,
                )

        # 2. Model
        if search_dto.model:
            query = query.where(
                self.model.metadata_["model"].astext == search_dto.model.value,
            )

        # 3. Item Type
        if hasattr(search_dto, "item_type") and search_dto.item_type:
            query = query.where(self.model.item_type == search_dto.item_type)

        # 4. Date Range
        if hasattr(search_dto, "start_date") and search_dto.start_date:
            query = query.where(self.model.created_at >= search_dto.start_date)

        if hasattr(search_dto, "end_date") and search_dto.end_date:
            # Add one day to include the full end date
            query = query.where(
                self.model.created_at
                < search_dto.end_date + datetime.timedelta(days=1)
            )

        # 4.5 Tags Filter
        if hasattr(search_dto, "tags") and search_dto.tags:
            for tag_name in search_dto.tags:
                query = query.where(
                    self.model.metadata_["tags"].contains([{"name": tag_name}])
                )

        # 5. Full-Text Word Search
        if hasattr(search_dto, "query") and search_dto.query:
            search_pattern = f"%{search_dto.query}%"
            query = query.where(
                func.coalesce(self.model.metadata_["prompt"].astext, "").ilike(
                    search_pattern
                )
                | func.coalesce(
                    self.model.metadata_["file_name"].astext, ""
                ).ilike(search_pattern)
                | func.coalesce(self.model.metadata_["model"].astext, "").ilike(
                    search_pattern
                )
                | func.coalesce(
                    self.model.metadata_["original_filename"].astext, ""
                ).ilike(search_pattern)
            )

        # 2. Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar_one()

        # 3. Add ordering and pagination
        # Default ordering by created_at DESC
        query = query.order_by(
            self.model.created_at.desc(), self.model.id.desc()
        )

        # Offset-based pagination
        query = query.offset(search_dto.offset).limit(search_dto.limit)

        # 4. Execute
        result = await self.db.execute(query)
        rows = result.scalars().all()

        data = []
        for item in rows:
            item_data = self.schema.model_validate(item)
            data.append(item_data)

        # 5. Determine next cursor (offset)
        page = (search_dto.offset // search_dto.limit) + 1
        page_size = search_dto.limit
        total_pages = (total_count + page_size - 1) // page_size

        return PaginationResponseDto[UnifiedGalleryItemResponse](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=data,
        )
