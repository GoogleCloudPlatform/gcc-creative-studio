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

"""SQLAlchemy and Pydantic models for folders."""

import datetime
from pydantic import Field
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseDocument
from src.database import Base


class Folder(Base):
    """SQLAlchemy model for the 'folders' table."""

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)

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
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "idx_folders_workspace_parent",
            "workspace_id",
            "parent_id",
            postgresql_where=deleted_at.is_(None),
        ),
        Index("idx_folders_workspace_id", "workspace_id"),
        Index(
            "uq_folders_workspace_parent_name_active",
            "workspace_id",
            "parent_id",
            func.lower(func.trim(name)),
            unique=True,
            postgresql_where=text(
                "parent_id IS NOT NULL AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_folders_workspace_root_name_active",
            "workspace_id",
            func.lower(func.trim(name)),
            unique=True,
            postgresql_where=text("parent_id IS NULL AND deleted_at IS NULL"),
        ),
    )


class FolderModel(BaseDocument):
    """Pydantic model representing a Folder."""

    id: int | None = None
    workspace_id: int = Field(
        description="The ID of the workspace this folder belongs to."
    )
    user_id: int | None = Field(
        default=None, description="The ID of the user who created the folder."
    )
    user_email: str = Field(
        description="Email of the user who created the folder."
    )
    name: str = Field(description="The name of the folder.")
    parent_id: int | None = Field(
        default=None,
        description="Parent folder ID, or None if at root of workspace.",
    )
    color: str | None = Field(
        default=None, description="Optional color hex code for folder."
    )
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    deleted_at: datetime.datetime | None = None
    deleted_by: int | None = None
