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
"""Tests for User Service."""


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.users.dto.user_create_dto import UserUpdateRoleDto
from src.users.user_model import UserRoleEnum
from src.users.user_service import UserService


@pytest.fixture(name="mock_user_repo")
def fixture_mock_user_repo():
    """Provides a mocked UserRepository."""
    # We mock the UserRepository class itself to avoid DB dependency
    repo = AsyncMock()
    return repo


@pytest.fixture(name="user_service")
def fixture_user_service(mock_user_repo):
    """Provides a UserService with a mocked repository."""
    return UserService(user_repo=mock_user_repo)


class TestCreateUserIfNotExists:
    """Tests for UserService.create_user_if_not_exists."""

    @pytest.mark.anyio
    async def test_user_exists(self, user_service, mock_user_repo, mock_user):
        # Setup: Mock repo to return existing user
        mock_user_repo.get_by_email.return_value = mock_user

        # Action: Call service method
        result = await user_service.create_user_if_not_exists(
            email="user@example.com",
            name="Regular User",
            picture="",
        )

        # Assertions
        assert result == mock_user
        mock_user_repo.get_by_email.assert_called_once_with(
            "user@example.com", include_deleted=True
        )
        # Verify create was NOT called
        mock_user_repo.create.assert_not_called()

    @pytest.mark.anyio
    async def test_user_does_not_exist(
        self, user_service, mock_user_repo, mock_user
    ):
        # Setup: Mock repo to return None (user doesn't exist)
        mock_user_repo.get_by_email.return_value = None
        # Mock create to return the created user
        mock_user_repo.create.return_value = mock_user

        # Action: Call service method
        result = await user_service.create_user_if_not_exists(
            email="new@example.com",
            name="New User",
            picture="http://pic.jpg",
        )

        # Assertions
        assert result == mock_user
        mock_user_repo.get_by_email.assert_called_once_with(
            "new@example.com", include_deleted=True
        )

        # Verify create was called with correct data
        called_args = mock_user_repo.create.call_args[0][0]
        assert called_args["email"] == "new@example.com"
        assert called_args["name"] == "New User"
        assert called_args["roles"] == [UserRoleEnum.USER]

    @pytest.mark.anyio
    async def test_mixed_case_email_is_looked_up_and_stored_lowercase(
        self, user_service, mock_user_repo, mock_user
    ):
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo.create.return_value = mock_user

        await user_service.create_user_if_not_exists(
            email="  New.User@Example.COM ", name="New User", picture=""
        )

        mock_user_repo.get_by_email.assert_called_once_with(
            "new.user@example.com", include_deleted=True
        )
        created = mock_user_repo.create.call_args.args[0]
        assert created["email"] == "new.user@example.com"


class TestGetUserById:
    """Tests for UserService.get_user_by_id."""

    @pytest.mark.anyio
    async def test_get_user_found(
        self, user_service, mock_user_repo, mock_user
    ):
        mock_user_repo.get_by_id.return_value = mock_user

        result = await user_service.get_user_by_id(1)

        assert result == mock_user
        mock_user_repo.get_by_id.assert_called_once_with(1)

    @pytest.mark.anyio
    async def test_get_user_not_found(self, user_service, mock_user_repo):
        mock_user_repo.get_by_id.return_value = None

        result = await user_service.get_user_by_id(999)

        assert result is None
        mock_user_repo.get_by_id.assert_called_once_with(999)


class TestUpdateUserRole:
    """Tests for UserService.update_user_role."""

    @pytest.mark.anyio
    async def test_user_not_found(self, user_service, mock_user_repo):
        mock_user_repo.get_by_id.return_value = None
        role_data = UserUpdateRoleDto(roles=[UserRoleEnum.ADMIN])

        result = await user_service.update_user_role(1, role_data)

        assert result is None
        mock_user_repo.get_by_id.assert_called_once_with(1)

    @pytest.mark.anyio
    async def test_prevent_removing_last_admin(
        self,
        user_service,
        mock_user_repo,
        mock_admin,
    ):
        # Setup: User IS an admin
        mock_user_repo.get_by_id.return_value = mock_admin

        # Mock DB execute to return 1 (only 1 admin left)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_user_repo.db.execute.return_value = mock_result

        # Action: Try to demote to regular user
        role_data = UserUpdateRoleDto(roles=[UserRoleEnum.USER])

        # Assertions
        with pytest.raises(HTTPException) as exc_info:
            await user_service.update_user_role(2, role_data)

        assert exc_info.value.status_code == 400
        assert "There must be at least 1 admin" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_valid_update(
        self,
        user_service,
        mock_user_repo,
        mock_user,
        mock_admin,
    ):
        # Setup: User is regular user, becoming admin
        mock_user_repo.get_by_id.return_value = mock_user
        mock_user_repo.update.return_value = mock_admin  # returns updated

        role_data = UserUpdateRoleDto(roles=[UserRoleEnum.ADMIN])

        result = await user_service.update_user_role(1, role_data)

        assert result == mock_admin
        mock_user_repo.update.assert_called_once_with(
            1,
            {"roles": [UserRoleEnum.ADMIN.value]},
        )
