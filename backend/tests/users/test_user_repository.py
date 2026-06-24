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
"""Tests for User Repository."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.users.dto.user_search_dto import UserSearchDto
from src.users.repository.user_repository import UserRepository
from src.users.user_model import User, UserRoleEnum


def get_dummy_user(**kwargs):
    now = datetime.datetime.now(datetime.UTC)
    defaults = {
        "id": 1,
        "email": "user@example.com",
        "name": "Test User",
        "picture": "http://example.com/pic.jpg",
        "roles": [UserRoleEnum.USER.value],
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    defaults.update(kwargs)
    return User(**defaults)


@pytest.mark.anyio
async def test_get_by_email_success():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_user = get_dummy_user(email="test@example.com")
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_db.execute.return_value = mock_result

    repo = UserRepository(db=mock_db)
    response = await repo.get_by_email(email="test@example.com")

    assert response is not None
    assert response.email == "test@example.com"
    assert response.id == 1
    mock_db.execute.assert_called_once()


@pytest.mark.anyio
async def test_get_by_email_not_found():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    repo = UserRepository(db=mock_db)
    response = await repo.get_by_email(email="nonexistent@example.com")

    assert response is None
    mock_db.execute.assert_called_once()


@pytest.mark.anyio
async def test_query_no_filters():
    mock_db = AsyncMock()

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 5

    mock_users_result = MagicMock()
    mock_user = get_dummy_user(id=1)
    mock_users_result.scalars().all.return_value = [mock_user]

    mock_db.execute.side_effect = [mock_count_result, mock_users_result]

    repo = UserRepository(db=mock_db)
    search_dto = UserSearchDto(limit=10, offset=0)
    response = await repo.query(search_dto=search_dto)

    assert response is not None
    assert response.count == 5
    assert response.page == 1
    assert response.page_size == 10
    assert response.total_pages == 1
    assert len(response.data) == 1
    assert response.data[0].id == 1

    assert mock_db.execute.call_count == 2


@pytest.mark.anyio
async def test_query_with_filters():
    mock_db = AsyncMock()

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1

    mock_users_result = MagicMock()
    mock_user = get_dummy_user(id=2, email="admin@example.com", roles=[UserRoleEnum.ADMIN.value])
    mock_users_result.scalars().all.return_value = [mock_user]

    mock_db.execute.side_effect = [mock_count_result, mock_users_result]

    repo = UserRepository(db=mock_db)
    search_dto = UserSearchDto(
        email="admin",
        role=UserRoleEnum.ADMIN,
        limit=5,
        offset=0,
        include_deleted=True,
    )
    response = await repo.query(search_dto=search_dto)

    assert response is not None
    assert response.count == 1
    assert response.page == 1
    assert response.page_size == 5
    assert response.total_pages == 1
    assert len(response.data) == 1
    assert response.data[0].email == "admin@example.com"

    assert mock_db.execute.call_count == 2
