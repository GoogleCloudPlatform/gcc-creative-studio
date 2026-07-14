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
"""Base repository class for database operations."""


import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

# Define generic types for SQLAlchemy Model and Pydantic Schema
ModelT = TypeVar("ModelT", bound=Any)
SchemaT = TypeVar("SchemaT", bound=BaseModel)
IdT = TypeVar("IdT", bound=int | str)


class BaseDocumentMixin(BaseModel, Generic[IdT]):
    """Base Pydantic model for all schemas.
    Now generic over IdT to enforce strict int or str IDs.
    """

    id: IdT
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    updated_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )

    # Pydantic v2 configuration for this sub-model
    model_config = ConfigDict(
        # Allows passing enum members like StyleEnum.MODERN
        use_enum_values=True,
        extra="ignore",  # Prevents accidental extra fields
        populate_by_name=True,
        from_attributes=True,
        alias_generator=to_camel,
    )


# Backward compatibility: BaseDocument defaults to int IDs
class BaseDocument(BaseDocumentMixin[int]):
    pass


# New base class for models that require String IDs (e.g. UUIDs)
class BaseStringDocument(BaseDocumentMixin[str]):
    pass


class BaseRepositoryMixin(Generic[ModelT, SchemaT, IdT]):
    """A generic repository mixin for common SQLAlchemy operations.
    Generic over IdT to enforce strict types.
    """

    def __init__(
        self,
        model: type[ModelT],
        schema: type[SchemaT],
        db: AsyncSession,
    ):
        self.model = model
        self.schema = schema
        self.db = db

    async def get_by_id(
        self,
        item_id: IdT,
        include_deleted: bool = False,
    ) -> SchemaT | None:
        """Retrieves a single document by its ID, excluding soft-deleted
        ones."""
        query = (
            select(self.model)
            .where(self.model.id == item_id)
            .execution_options(include_deleted=include_deleted)
        )

        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self.schema.model_validate(item)

    async def create(self, schema: BaseModel | dict[str, Any]) -> SchemaT:
        """Creates a new record in the database."""
        # Convert Pydantic schema to SQLAlchemy model
        if isinstance(schema, BaseModel):
            data = schema.model_dump(exclude_unset=True)
        else:
            data = schema.copy()

        # We exclude 'id' if it's None so the DB can auto-increment it
        # (for Int IDs)
        if data.get("id") is None:
            data.pop("id", None)

        # Filter out extra fields not present on the SQLAlchemy model
        data = {
            k: v for k, v in data.items() if k in self.model.__mapper__.attrs
        }

        db_item = self.model(**data)
        self.db.add(db_item)
        await self.db.commit()
        await self.db.refresh(db_item)
        return self.schema.model_validate(db_item)

    async def update(
        self,
        item_id: IdT,
        update_data: BaseModel | dict[str, Any],
    ) -> SchemaT | None:
        """Performs a partial update on a document."""
        # Fetch the item first
        query = select(self.model).where(self.model.id == item_id)
        result = await self.db.execute(query)
        db_item = result.scalar_one_or_none()
        if not db_item:
            return None

        # Prepare update data
        if isinstance(update_data, BaseModel):
            data = update_data.model_dump(exclude_unset=True)
        else:
            data = update_data

        # Update fields
        restricted_fields = {"id", "created_at", "updated_at"}
        for key, value in data.items():
            if key in restricted_fields:
                continue
            if key in self.model.__mapper__.attrs:
                setattr(db_item, key, value)

        # Update timestamp
        if hasattr(db_item, "updated_at"):
            db_item.updated_at = datetime.datetime.now(datetime.UTC)

        await self.db.commit()
        await self.db.refresh(db_item)
        return self.schema.model_validate(db_item)

    async def delete(self, item_id: IdT) -> bool:
        """Deletes a document by its ID (HARD DELETE).
        Returns True if deletion was successful (item existed), False otherwise.
        """
        # Check existence first or just delete and check rowcount
        result = await self.db.execute(
            delete(self.model).where(self.model.id == item_id),
        )
        await self.db.commit()
        return result.rowcount > 0  # type: ignore

    async def soft_delete(
        self,
        item_id: IdT,
        deleted_by: int | None = None,
    ) -> bool:
        """Soft deletes a document by setting its `deleted_at` timestamp.
        Returns True if successful, False if item not found.
        """
        query = select(self.model).where(self.model.id == item_id)
        result = await self.db.execute(query)
        db_item = result.scalar_one_or_none()
        if not db_item:
            return False

        if hasattr(db_item, "deleted_at"):
            db_item.deleted_at = datetime.datetime.now(datetime.UTC)

        if hasattr(db_item, "deleted_by") and deleted_by is not None:
            db_item.deleted_by = deleted_by

        await self.db.commit()
        return True

    async def restore(self, item_id: IdT) -> bool:
        """Soft restores a document by setting its `deleted_at` timestamp
        back to None.
        Returns True if successful, False if item not found.
        """
        query = (
            select(self.model)
            .where(self.model.id == item_id)
            .execution_options(include_deleted=True)
        )
        result = await self.db.execute(query)
        db_item = result.scalar_one_or_none()
        if not db_item:
            return False

        if hasattr(db_item, "deleted_at"):
            db_item.deleted_at = None

        if hasattr(db_item, "deleted_by"):
            db_item.deleted_by = None

        await self.db.commit()
        return True

    async def find_all(
        self,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[SchemaT]:
        """Finds all documents with pagination, excluding soft-deleted ones."""
        query = select(self.model).execution_options(
            include_deleted=include_deleted
        )
        result = await self.db.execute(query.limit(limit).offset(offset))
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]


# BaseRepository defaults to int IDs
class BaseRepository(BaseRepositoryMixin[ModelT, SchemaT, int]):
    pass


# BaseStringRepository requires String IDs (e.g. UUIDs)
class BaseStringRepository(BaseRepositoryMixin[ModelT, SchemaT, str]):
    pass
