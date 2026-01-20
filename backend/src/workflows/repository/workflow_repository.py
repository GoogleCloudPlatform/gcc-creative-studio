# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Optional

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseStringRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.database import get_db
from src.workflows.dto.workflow_search_dto import WorkflowSearchDto
from src.workflows.schema.workflow_model import Workflow, WorkflowModel


class WorkflowRepository(BaseStringRepository[Workflow, WorkflowModel]):
    """Handles persistence for workflow definitions in PostgreSQL."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Workflow, schema=WorkflowModel, db=db)

    async def query(
        self, user_id: int, search_dto: WorkflowSearchDto
    ) -> PaginationResponseDto[WorkflowModel]:
        """Performs a paginated query for workflows."""
        query = select(self.model).where(
            self.model.user_id == user_id
        )

        if search_dto.name:
            # Case-insensitive search
            query = query.where(self.model.name.ilike(f"%{search_dto.name}%"))

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar_one()

        # Order and Pagination
        query = query.order_by(self.model.created_at.desc())
        
        query = query.limit(search_dto.limit)
        query = query.offset(search_dto.offset)
        
        result = await self.db.execute(query)
        workflows = result.scalars().all()
        workflow_data = [self.schema.model_validate(w) for w in workflows]

        # Calculate pagination metadata
        page = (search_dto.offset // search_dto.limit) + 1
        page_size = search_dto.limit
        total_pages = (total_count + page_size - 1) // page_size

        return PaginationResponseDto[WorkflowModel](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=workflow_data,
        )


