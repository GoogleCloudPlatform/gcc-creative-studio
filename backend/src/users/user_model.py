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
from enum import Enum

from pydantic import Field, field_validator
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseDocument
from src.database import Base


class UserRoleEnum(str, Enum):
    """Defines the distinct roles a user can have within the application,
    enabling role-based access control.
    """

    USER = "user"  # Basic access to browse and use public features.
    CREATOR = "creator"  # Can create and manage their own content.
    ADMIN = "admin"  # Has full administrative privileges, including user management.
    WORKFLOWS = "workflows"  # Can interact with workflows.


class User(Base):
    """SQLAlchemy model for the 'users' table."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    entra_oid: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=[])
    name: Mapped[str] = mapped_column(String, default="")
    picture: Mapped[str] = mapped_column(String, default="")

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
    deleted_by: Mapped[int | None] = mapped_column(nullable=True)
    # Last time roles were reconciled against Entra ID (success or failure).
    roles_checked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class UserModel(BaseDocument):
    """Represents a user document (DTO) for the API."""

    # ID is required for Read DTOs
    id: int
    email: str
    entra_oid: str | None = None
    roles: list[UserRoleEnum] = Field(default_factory=list)
    name: str
    picture: str = ""
    deleted_at: datetime.datetime | None = None
    deleted_by: int | None = None
    roles_checked_at: datetime.datetime | None = None

    @field_validator("roles", mode="after")
    @classmethod
    def default_to_user_role(
        cls, roles: list[UserRoleEnum]
    ) -> list[UserRoleEnum]:
        """Ensures that if the 'roles' list is empty after initialization,
        it defaults to containing the 'USER' role.
        """
        if not roles:
            return [UserRoleEnum.USER]
        return roles
