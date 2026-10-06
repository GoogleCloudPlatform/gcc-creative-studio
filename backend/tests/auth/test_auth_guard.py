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

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.auth.auth_guard import RoleChecker, get_current_user
from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum


@pytest.fixture(name="mock_user_service")
def fixture_mock_user_service():
    service = AsyncMock()
    # Mock create_user_if_not_exists to return a user
    service.create_user_if_not_exists.return_value = UserModel(
        id=1,
        email="test@example.com",
        roles=["user"],
        name="Test User",
    )
    return service


@pytest.fixture(name="mock_request")
def fixture_mock_request():
    class MockRequest:
        def __init__(self, headers=None):
            self.headers = headers or {}

    return MockRequest()


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_get_current_user_local_success(
        self, mock_verify, mock_user_service, mock_request
    ):
        # Setup: Local environment
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_ORGS_STR = ""

        # Mock token verification
        mock_verify.return_value = {
            "email": "test@example.com",
            "name": "Test User",
            "picture": "http://example.com/pic.jpg",
            "hd": "example.com",
        }

        user = await get_current_user(
            request=mock_request,
            token="valid_token",
            user_service=mock_user_service,
        )

        assert user.email == "test@example.com"
        assert user.name == "Test User"
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="test@example.com",
            name="Test User",
            picture="http://example.com/pic.jpg",
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_get_current_user_no_email(
        self, mock_verify, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify.return_value = {"name": "Test User"}  # Missing email

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 403
        assert "User identity could not be confirmed" in exc_info.value.detail

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_get_current_user_allowed_orgs_fail(
        self, mock_verify, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_ORGS_STR = "allowed.com"

        mock_verify.return_value = {
            "email": "test@example.com",
            "name": "Test User",
            "hd": "forbidden.com",
        }

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert (
            "User is not authorized to access this application."
            in exc_info.value.detail
        )


class TestRoleChecker:
    """Tests for RoleChecker class."""

    def test_role_checker_authorized(self):
        checker = RoleChecker(allowed_roles=[UserRoleEnum.ADMIN])
        user = UserModel(
            id=1,
            email="admin@example.com",
            roles=["admin"],
            name="Admin User",
        )

        # Should not raise exception
        checker(user=user)

    def test_role_checker_forbidden(self):
        checker = RoleChecker(allowed_roles=[UserRoleEnum.ADMIN])
        user = UserModel(
            id=1,
            email="user@example.com",
            roles=["user"],
            name="Regular User",
        )

        with pytest.raises(HTTPException) as exc_info:
            checker(user=user)

        assert exc_info.value.status_code == 403
        assert "do not have sufficient permissions" in exc_info.value.detail
