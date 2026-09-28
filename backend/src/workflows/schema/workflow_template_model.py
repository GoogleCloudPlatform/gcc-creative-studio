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

"""Workflow Template model and schema definitions."""

import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_dto import BaseDto
from src.common.base_repository import BaseStringDocument
from src.database import Base
from src.workflows.schema.workflow_model import WorkflowBase


class WorkflowTemplate(Base):
    """SQLAlchemy model for the 'workflow_templates' table."""

    __tablename__ = "workflow_templates"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", name="uq_user_workflow_template_name"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )


class WorkflowTemplateModel(BaseStringDocument, WorkflowBase):
    """The workflow template definition used across the application."""

    user_id: int
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class WorkflowTemplateCreateDto(WorkflowBase, BaseDto):
    """DTO for creating a new workflow template."""
