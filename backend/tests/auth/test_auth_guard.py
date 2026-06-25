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

from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi import HTTPException, Request
from src.auth.auth_guard import RoleChecker, get_current_user, get_iap_jwt
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


class TestGetCurrentUser:
    """Tests for get_current_user dependency and IAP authentication."""

    @pytest.mark.anyio
    async def test_get_iap_jwt_missing_header_prod(self):
        # Setup: non-local env
        config_service.ENVIRONMENT = "production"
        mock_request = MagicMock(spec=Request)

        with pytest.raises(HTTPException) as exc_info:
            await get_iap_jwt(
                request=mock_request, x_goog_iap_jwt_assertion=None
            )

        assert exc_info.value.status_code == 401
        assert (
            "Missing X-Goog-Iap-Jwt-Assertion header" in exc_info.value.detail
        )

    @pytest.mark.anyio
    async def test_get_iap_jwt_local_default(self):
        # Setup: local env
        config_service.ENVIRONMENT = "local"
        mock_request = MagicMock(spec=Request)

        token = await get_iap_jwt(
            request=mock_request, x_goog_iap_jwt_assertion=None
        )
        assert token == "mock_local_token"

    @pytest.mark.anyio
    async def test_get_current_user_local_dev_bypass_default(
        self, mock_user_service
    ):
        config_service.ENVIRONMENT = "local"
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}  # No mock headers

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=1,
            email="local-dev@example.com",
            name="Local Dev User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="mock_local_token",
            user_service=mock_user_service,
        )

        assert user.email == "local-dev@example.com"
        assert user.name == "Local Dev User"
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="local-dev@example.com", name="Local Dev User", picture=""
        )

    @pytest.mark.anyio
    async def test_get_current_user_local_dev_bypass_custom_headers(
        self, mock_user_service
    ):
        config_service.ENVIRONMENT = "local"
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "X-Mock-User-Email": "custom-dev@example.com",
            "X-Mock-User-Name": "Custom Dev User",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=2,
            email="custom-dev@example.com",
            name="Custom Dev User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="mock_local_token",
            user_service=mock_user_service,
        )

        assert user.email == "custom-dev@example.com"
        assert user.name == "Custom Dev User"
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="custom-dev@example.com", name="Custom Dev User", picture=""
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_success(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = ""

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "email": "iap_user@example.com",
            "name": "IAP User",
            "picture": "http://example.com/pic.jpg",
            "hd": "example.com",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=3, email="iap_user@example.com", name="IAP User", roles=["user"]
        )

        user = await get_current_user(
            request=mock_request,
            token="valid_iap_jwt",
            user_service=mock_user_service,
        )

        assert user.email == "iap_user@example.com"
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="iap_user@example.com",
            name="IAP User",
            picture="http://example.com/pic.jpg",
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_success_fallback_to_sub(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = ""

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "sub": "principal://iam.googleapis.com/locations/global/workforcePools/pool/subject/user123",
            "name": "Federated User",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=4,
            email="principal://iam.googleapis.com/locations/global/workforcePools/pool/subject/user123",
            name="Federated User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="valid_iap_jwt",
            user_service=mock_user_service,
        )

        assert (
            user.email
            == "principal://iam.googleapis.com/locations/global/workforcePools/pool/subject/user123"
        )
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="principal://iam.googleapis.com/locations/global/workforcePools/pool/subject/user123",
            name="Federated User",
            picture="",
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_invalid_token(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"

        mock_request = MagicMock(spec=Request)
        mock_verify.side_effect = ValueError("Invalid signature")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="invalid_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert "Invalid IAP authentication token" in exc_info.value.detail

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_allowed_orgs_fail(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = "allowed.com"

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "email": "user@forbidden.com",
            "name": "Forbidden User",
            "hd": "forbidden.com",
        }

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert "not part of an allowed organization" in exc_info.value.detail
        config_service.ALLOWED_ORGS_STR = ""

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_success_fallback_preferred_username(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = ""

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "preferred_username": "preferred_user@example.com",
            "name": "Preferred User",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=5,
            email="preferred_user@example.com",
            name="Preferred User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="valid_iap_jwt",
            user_service=mock_user_service,
        )

        assert user.email == "preferred_user@example.com"
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="preferred_user@example.com",
            name="Preferred User",
            picture="",
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_success_fallback_upn(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = ""

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "upn": "upn_user@example.com",
            "name": "UPN User",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=6,
            email="upn_user@example.com",
            name="UPN User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="valid_iap_jwt",
            user_service=mock_user_service,
        )

        assert user.email == "upn_user@example.com"
        mock_user_service.create_user_if_not_exists.assert_called_once_with(
            email="upn_user@example.com",
            name="UPN User",
            picture="",
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_success_fallback_precedence_preferred_username(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = ""

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "preferred_username": "preferred@example.com",
            "upn": "upn@example.com",
            "sub": "sub-id",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=7,
            email="preferred@example.com",
            name="User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="valid_iap_jwt",
            user_service=mock_user_service,
        )

        assert user.email == "preferred@example.com"

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_get_current_user_iap_success_fallback_precedence_upn(
        self, mock_verify, mock_user_service
    ):
        config_service.ENVIRONMENT = "production"
        config_service.IAP_EXPECTED_AUDIENCE = "test-iap-audience"
        config_service.ALLOWED_ORGS_STR = ""

        mock_request = MagicMock(spec=Request)
        mock_verify.return_value = {
            "upn": "upn@example.com",
            "sub": "sub-id",
        }

        mock_user_service.create_user_if_not_exists.return_value = UserModel(
            id=8,
            email="upn@example.com",
            name="User",
            roles=["user"],
        )

        user = await get_current_user(
            request=mock_request,
            token="valid_iap_jwt",
            user_service=mock_user_service,
        )

        assert user.email == "upn@example.com"


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
