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


from typing import Any

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.database import get_db
from src.users.dto.user_search_dto import UserSearchDto
from src.users.user_model import User, UserModel


class UserRepository(BaseRepository[User, UserModel]):
    """Handles all database operations for the User table."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=User, schema=UserModel, db=db)

    async def get_by_email(
        self, email: str, include_deleted: bool = False
    ) -> UserModel | None:
        """Finds a single user by email, ignoring letter case.

        Emails are stored lowercase, so an equality match on the lowercased
        input stays on the users.email index.
        """
        result = await self.db.execute(
            select(self.model)
            .where(self.model.email == email.strip().lower())
            .execution_options(include_deleted=include_deleted),
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        return self.schema.model_validate(user)

    async def get_by_entra_oid(
        self, entra_oid: str, include_deleted: bool = False
    ) -> UserModel | None:
        """Finds a single user by Entra object ID (stored lowercase)."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.entra_oid == entra_oid.strip().lower())
            .execution_options(include_deleted=include_deleted),
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        return self.schema.model_validate(user)

    async def create_or_get_existing(
        self, user_data: dict[str, Any]
    ) -> UserModel:
        """Creates the user, or returns the row another request just created.

        A browser's first page load sends several requests at once, and each
        can try to create the new user. Only one insert can succeed; the
        others undo their failed insert and use the row that now exists, if
        it has the same email or Entra ID.
        """
        try:
            return await self.create(user_data)
        except IntegrityError:
            await self.db.rollback()
            existing = None
            if user_data.get("entra_oid"):
                existing = await self.get_by_entra_oid(
                    user_data["entra_oid"], include_deleted=True
                )
            if existing is None and user_data.get("email"):
                existing = await self.get_by_email(
                    user_data["email"], include_deleted=True
                )
            if existing is None:
                raise
            # Only reuse the row if it is the same, active person. Anything
            # else keeps the original error rather than handing over another
            # identity's (or a deactivated) account.
            if existing.deleted_at is not None or (
                user_data.get("entra_oid")
                and existing.entra_oid != user_data["entra_oid"]
            ):
                raise
            return existing

    async def query(
        self,
        search_dto: UserSearchDto,
    ) -> PaginationResponseDto[UserModel]:
        """Performs a paginated query that includes the total document count."""
        # 1. Start with select
        query = select(self.model).execution_options(
            include_deleted=search_dto.include_deleted
        )

        # 2. Apply filters
        if search_dto.email:
            query = query.where(self.model.email.ilike(f"%{search_dto.email}%"))

        if search_dto.role:
            query = query.where(
                self.model.roles.contains([search_dto.role.value])
            )

        # Count total documents matching filters
        count_query = query.with_only_columns(func.count(self.model.id))
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar_one()

        # 3. Add ordering and pagination
        # Default ordering by created_at DESC
        query = query.order_by(self.model.created_at.desc())

        # Offset-based pagination
        query = query.offset(search_dto.offset).limit(search_dto.limit)

        # 4. Execute
        result = await self.db.execute(query)
        users = result.scalars().all()

        user_data = [self.schema.model_validate(user) for user in users]

        # 5. Determine next cursor (offset)
        # Calculate pagination metadata
        page = (search_dto.offset // search_dto.limit) + 1
        page_size = search_dto.limit
        total_pages = (total_count + page_size - 1) // page_size

        return PaginationResponseDto[UserModel](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=user_data,
        )
