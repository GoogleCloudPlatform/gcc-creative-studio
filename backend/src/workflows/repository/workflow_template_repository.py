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

"""Handles persistence for workflow templates in PostgreSQL."""

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseStringRepository
from src.database import get_db
from src.workflows.schema.workflow_template_model import (
    WorkflowTemplate,
    WorkflowTemplateModel,
)


class WorkflowTemplateRepository(
    BaseStringRepository[WorkflowTemplate, WorkflowTemplateModel]
):
    """Repository for persisting workflow templates."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=WorkflowTemplate, schema=WorkflowTemplateModel, db=db
        )

    async def get_by_user_and_name(
        self, user_id: int, name: str
    ) -> WorkflowTemplateModel | None:
        """Retrieves a workflow template by user_id and case-insensitive name."""
        query = select(self.model).where(
            self.model.user_id == user_id,
            func.lower(self.model.name) == func.lower(name.strip()),
        )
        result = await self.db.execute(query)
        instance = result.scalar_one_or_none()
        return self.schema.model_validate(instance) if instance else None

    async def list_by_user(self, user_id: int) -> list[WorkflowTemplateModel]:
        """Lists all workflow templates for a specific user ordered by creation date."""
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(query)
        templates = result.scalars().all()
        return [self.schema.model_validate(t) for t in templates]

    async def delete_by_id_and_user(
        self, template_id: str, user_id: int
    ) -> bool:
        """Deletes a workflow template if it belongs to the specified user."""
        template = await self.get_by_id(template_id)
        if not template or template.user_id != user_id:
            return False
        return await self.delete(template_id)
