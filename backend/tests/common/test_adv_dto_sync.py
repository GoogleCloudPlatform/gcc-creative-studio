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
"""Adversarial tests for Model/DTO synchronization."""

import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import BaseModel, ValidationError

from src.common.base_repository import BaseRepository
from src.users.user_model import User, UserModel, UserRoleEnum
from src.users.dto.user_create_dto import UserCreateDto


class TestUserRepository(BaseRepository[User, UserModel]):
    def __init__(self, db):
        super().__init__(model=User, schema=UserModel, db=db)


class ExtraFieldDto(BaseModel):
    email: str
    name: str
    extra_field: str  # Field that does not exist in the SQLAlchemy User model


@pytest.mark.anyio
async def test_update_restricted_fields_vulnerability():
    """Vulnerability test: Checks if BaseRepository.update allows overwriting
    restricted fields like 'id' or 'created_at'.
    """
    mock_db = AsyncMock()
    now = datetime.datetime.now(datetime.UTC)

    # Existing user in db
    existing_user = User(
        id=42,
        email="user@example.com",
        roles=["user"],
        name="Test User",
        picture="",
        created_at=now,
        updated_at=now,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    repo = TestUserRepository(db=mock_db)

    # Malicious update payload attempting to change ID and creation date
    malicious_update = {
        "id": 999,
        "created_at": now - datetime.timedelta(days=100),
        "updated_at": now - datetime.timedelta(days=100),
        "name": "Updated Name",
    }

    response = await repo.update(item_id=42, update_data=malicious_update)

    # Assertions to verify that restricted fields were NOT changed
    assert response is not None
    assert response.name == "Updated Name"
    assert response.id == 42  # Unchanged
    assert existing_user.id == 42
    assert existing_user.created_at == now  # Unchanged
    assert existing_user.updated_at != now - datetime.timedelta(
        days=100
    )  # User update_at is ignored


@pytest.mark.anyio
async def test_validation_error_on_corrupt_db_data():
    """Checks if repository raises ValidationError when database contains invalid enum values."""
    mock_db = AsyncMock()

    # User in DB with an invalid/corrupt role
    corrupt_user = User(
        id=42,
        email="user@example.com",
        roles=["invalid_role_from_db"],
        name="Corrupt User",
        picture="",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = corrupt_user
    mock_db.execute.return_value = mock_result

    repo = TestUserRepository(db=mock_db)

    # Validation should fail during model_validate of the db item
    with pytest.raises(ValidationError) as exc_info:
        await repo.get_by_id(item_id=42)

    assert "roles" in str(exc_info.value)


@pytest.mark.anyio
async def test_extra_fields_in_dto_causes_crash():
    """Checks if passing a DTO with extra fields to create() is successful and ignores extra fields."""
    mock_db = AsyncMock()

    # Mock refresh to populate DB fields for Pydantic validation
    async def mock_refresh(instance):
        instance.id = 42
        instance.created_at = datetime.datetime.now(datetime.UTC)
        instance.updated_at = datetime.datetime.now(datetime.UTC)
        instance.roles = ["user"]
        instance.picture = ""

    mock_db.refresh.side_effect = mock_refresh
    repo = TestUserRepository(db=mock_db)

    # DTO with a field not present in SQLAlchemy User model
    dto_with_extra = ExtraFieldDto(
        email="test@example.com", name="Test", extra_field="unsupported"
    )

    # This should now succeed without a crash and correctly ignore the extra field
    response = await repo.create(schema=dto_with_extra)

    assert response is not None
    assert response.id == 42
    assert response.email == "test@example.com"
    assert response.name == "Test"


@pytest.mark.anyio
async def test_hasattr_shadowing_vulnerability():
    """Vulnerability test: Checks if BaseRepository.create and update ignore
    class attributes (like metadata, registry) to prevent shadowing.
    """
    mock_db = AsyncMock()
    now = datetime.datetime.now(datetime.UTC)

    # 1. Test update
    existing_user = User(
        id=42,
        email="user@example.com",
        roles=["user"],
        name="Test User",
        picture="",
        created_at=now,
        updated_at=now,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    repo = TestUserRepository(db=mock_db)

    shadowing_update = {
        "metadata": "malicious_metadata",
        "registry": "malicious_registry",
        "name": "Updated Name",
    }

    response = await repo.update(item_id=42, update_data=shadowing_update)

    assert response is not None
    assert response.name == "Updated Name"
    # Ensure metadata and registry on the database model instance were not shadowed/overwritten
    assert existing_user.metadata != "malicious_metadata"
    assert existing_user.registry != "malicious_registry"
    # They should still be their original SQLAlchemy objects
    assert existing_user.metadata == User.metadata
    assert existing_user.registry == User.registry

    # 2. Test create
    async def mock_refresh(instance):
        instance.id = 43
        instance.created_at = datetime.datetime.now(datetime.UTC)
        instance.updated_at = datetime.datetime.now(datetime.UTC)
        instance.roles = ["user"]
        instance.picture = ""

    mock_db.refresh.side_effect = mock_refresh

    shadowing_create = {
        "email": "new@example.com",
        "name": "New User",
        "metadata": "malicious_metadata",
        "registry": "malicious_registry",
    }

    # Intercepting model instantiation to assert that metadata/registry were not passed
    original_init = User.__init__
    init_called_with = {}

    def custom_init(self, *args, **kwargs):
        init_called_with.update(kwargs)
        original_init(self, *args, **kwargs)

    try:
        User.__init__ = custom_init
        await repo.create(schema=shadowing_create)
    finally:
        User.__init__ = original_init

    assert "metadata" not in init_called_with
    assert "registry" not in init_called_with
