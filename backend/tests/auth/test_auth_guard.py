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

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError
from google.auth import exceptions as google_auth_exceptions

from src.auth.auth_guard import (
    RoleChecker,
    clear_post_auth_hooks,
    get_current_user,
    get_post_auth_hooks,
    is_agent_request,
    register_post_auth_hook,
)
from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService


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

    @pytest.fixture(autouse=True)
    def reset_auth_config(self, monkeypatch):
        monkeypatch.setattr(config_service, "ENVIRONMENT", "local")
        monkeypatch.setattr(config_service, "ALLOWED_ORGS_STR", "")
        monkeypatch.setattr(config_service, "ALLOWED_EMAILS_STR", "")
        monkeypatch.setattr(
            config_service, "GOOGLE_TOKEN_AUDIENCE", "test-client-id"
        )
        saved_hooks = get_post_auth_hooks()
        clear_post_auth_hooks()
        token_reset = is_agent_request.set(False)
        try:
            yield
        finally:
            is_agent_request.reset(token_reset)
            clear_post_auth_hooks()
            for hook in saved_hooks:
                register_post_auth_hook(hook)

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

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_get_current_user_allowed_emails_fail(
        self, mock_verify, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_EMAILS_STR = "allowed@google.com"

        mock_verify.return_value = {
            "email": "denied@google.com",
            "name": "Denied User",
            "hd": "google.com",
        }

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert (
            exc_info.value.detail
            == "User is not authorized to access this application."
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_expired_firebase_falls_back_to_oidc_success(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = auth.ExpiredIdTokenError(
            "Firebase token expired", cause=None
        )
        mock_verify_oidc.return_value = {
            "email": "user@google.com",
            "name": "Google User",
            "picture": "http://example.com/pic.jpg",
            "hd": "google.com",
        }

        user = await get_current_user(
            request=mock_request,
            token="oidc_token",
            user_service=mock_user_service,
        )

        assert user.email == "test@example.com"
        mock_verify_oidc.assert_called_once()
        assert mock_verify_oidc.call_args.kwargs["audience"] == "test-client-id"

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_expired_firebase_and_non_expired_oidc_returns_401_expired(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = auth.ExpiredIdTokenError(
            "Firebase token expired", cause=None
        )
        mock_verify_oidc.side_effect = google_auth_exceptions.InvalidValue(
            "Wrong audience"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="expired_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication token has expired."

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_firebase_cert_error_surfaces_oidc_expired_401(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = FirebaseError(
            "UNKNOWN", "Certificate fetch failed"
        )
        mock_verify_oidc.side_effect = ValueError(
            "Token expired, 1700000000 < 1700000100"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="expired_oidc_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication token has expired."

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_firebase_cert_error_surfaces_oidc_transport_401(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = FirebaseError(
            "UNKNOWN", "Certificate fetch failed"
        )
        mock_verify_oidc.side_effect = google_auth_exceptions.TransportError(
            "Connection timed out to oauth2.googleapis.com"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_invalid_firebase_and_invalid_oidc_returns_401(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = auth.InvalidIdTokenError(
            "Bad Firebase signature"
        )
        mock_verify_oidc.side_effect = ValueError(
            "Internal secret parsing failure"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="bad_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid authentication token."
        assert "Internal secret" not in exc_info.value.detail

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("oidc_exc", "expected_detail", "forbidden_substr"),
        [
            (
                google_auth_exceptions.InvalidValue(
                    "Token expired, 1700000000 < 1700000500"
                ),
                "Authentication token has expired.",
                "1700000000",
            ),
            (
                ValueError("EXPIRED signature window"),
                "Authentication token has expired.",
                "window",
            ),
            (
                google_auth_exceptions.TransportError(
                    "Metadata server 169.254.169.254 unreachable"
                ),
                "Failed to contact Google authentication server.",
                "169.254",
            ),
            (
                google_auth_exceptions.MalformedError(
                    "Wrong number of segments in token: raw_secret"
                ),
                "Invalid authentication token.",
                "raw_secret",
            ),
            (
                ValueError("Wrong recipient, expected test-client-id"),
                "Invalid authentication token.",
                "Wrong recipient",
            ),
        ],
    )
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_non_local_oidc_errors_map_to_sanitized_401(
        self,
        mock_verify_fb,
        mock_verify_oidc,
        mock_user_service,
        mock_request,
        oidc_exc,
        expected_detail,
        forbidden_substr,
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.side_effect = oidc_exc

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="bad_oidc_token",
                user_service=mock_user_service,
            )

        mock_verify_fb.assert_not_called()
        mock_verify_oidc.assert_called_once()
        assert mock_verify_oidc.call_args.kwargs["audience"] == "test-client-id"
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == expected_detail
        assert forbidden_substr not in exc_info.value.detail

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "downstream_exc",
        [
            ValueError("DB duplicate key constraint leaked_row_id"),
            RuntimeError("DB connection refused on 10.0.0.5"),
        ],
    )
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    async def test_downstream_user_service_errors_still_return_500(
        self,
        mock_verify_oidc,
        mock_user_service,
        mock_request,
        downstream_exc,
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.return_value = {
            "email": "user@google.com",
            "name": "Google User",
            "hd": "google.com",
        }
        mock_user_service.create_user_if_not_exists.side_effect = downstream_exc

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_oidc_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "An unexpected error occurred during authentication."
        )
        assert "leaked_row_id" not in exc_info.value.detail
        assert "10.0.0.5" not in exc_info.value.detail

    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    def test_fastapi_route_oidc_headers_and_agent_flag(
        self, mock_verify_oidc, mock_user_service
    ):
        config_service.ENVIRONMENT = "prod"
        mini_app = FastAPI()
        mini_app.dependency_overrides[UserService] = lambda: mock_user_service

        @mini_app.get("/protected")
        async def protected(user: UserModel = Depends(get_current_user)):
            return {
                "email": user.email,
                "is_agent": is_agent_request.get(),
            }

        client = TestClient(mini_app)

        # Missing token -> 401
        missing_resp = client.get("/protected")
        assert missing_resp.status_code == 401
        assert missing_resp.json() == {
            "detail": "Missing authentication token."
        }

        # Expired token via Authorization header -> 401
        mock_verify_oidc.side_effect = google_auth_exceptions.InvalidValue(
            "Token expired, 1700000000 < 1700000100"
        )
        auth_expired = client.get(
            "/protected", headers={"Authorization": "Bearer expired-jwt"}
        )
        assert auth_expired.status_code == 401
        assert auth_expired.json() == {
            "detail": "Authentication token has expired."
        }
        assert is_agent_request.get() is False

        # Expired token via X-User-Authorization -> 401 and sets agent flag
        agent_expired = client.get(
            "/protected",
            headers={"X-User-Authorization": "Bearer expired-user-jwt"},
        )
        assert agent_expired.status_code == 401
        assert agent_expired.json() == {
            "detail": "Authentication token has expired."
        }

        # Valid token via X-User-Authorization -> 200 with is_agent=True
        mock_verify_oidc.side_effect = None
        mock_verify_oidc.return_value = {
            "email": "test@example.com",
            "name": "Test User",
            "hd": "example.com",
        }
        agent_ok = client.get(
            "/protected",
            headers={"X-User-Authorization": "Bearer valid-user-jwt"},
        )
        assert agent_ok.status_code == 200
        assert agent_ok.json() == {
            "email": "test@example.com",
            "is_agent": True,
        }

        # Follow-up Authorization header call resets is_agent to False
        user_ok = client.get(
            "/protected",
            headers={"Authorization": "Bearer valid-jwt"},
        )
        assert user_ok.status_code == 200
        assert user_ok.json() == {
            "email": "test@example.com",
            "is_agent": False,
        }

        # Invalid token via Authorization header -> 401
        mock_verify_oidc.side_effect = ValueError("Wrong recipient")
        auth_invalid = client.get(
            "/protected", headers={"Authorization": "Bearer bad-jwt"}
        )
        assert auth_invalid.status_code == 401
        assert auth_invalid.json() == {
            "detail": "Invalid authentication token."
        }

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_firebase_cert_fetch_error_and_oidc_malformed_returns_transport_401(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = auth.CertificateFetchError(
            "cert fetch failed", cause=None
        )
        mock_verify_oidc.side_effect = google_auth_exceptions.MalformedError(
            "Wrong number of segments"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="firebase-jwt",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_non_jwt_opaque_token_never_logged_in_fallback_or_warning(
        self,
        mock_verify_fb,
        mock_verify_oidc,
        mock_user_service,
        mock_request,
        caplog,
    ):
        opaque_secret = "1//0g_opaque_secret_token"
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = ValueError(
            f"Can't parse segment: {opaque_secret}"
        )
        mock_verify_oidc.side_effect = google_auth_exceptions.MalformedError(
            f"Wrong number of segments in token: {opaque_secret}"
        )

        with caplog.at_level(logging.INFO, logger="src.auth.auth_guard"):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=mock_request,
                    token=opaque_secret,
                    user_service=mock_user_service,
                )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid authentication token."
        assert opaque_secret not in caplog.text
        assert "Malformed JWT structure" in caplog.text

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    async def test_non_local_oidc_wrong_issuer_google_auth_error_returns_401(
        self, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.side_effect = google_auth_exceptions.GoogleAuthError(
            "Wrong issuer"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="bad_issuer_jwt",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid authentication token."
        assert "Wrong issuer" not in exc_info.value.detail

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    async def test_unexpected_verifier_runtime_error_reraises_to_500(
        self, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.side_effect = RuntimeError(
            "Unexpected internal verifier panic"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="valid_jwt",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "An unexpected error occurred during authentication."
        )
        assert "verifier panic" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_ya29_non_200_and_request_exception_return_sanitized_401(
        self, mock_user_service, mock_request, caplog
    ):
        config_service.ENVIRONMENT = "prod"
        access_token = "ya29" + ".fake_access_token_secret"

        bad_resp = MagicMock(status_code=400, text="leaked_token_body")
        with (
            patch("requests.get", return_value=bad_resp),
            caplog.at_level(logging.INFO, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid Google access token."
        assert "leaked_token_body" not in caplog.text

        with (
            patch(
                "requests.get",
                side_effect=requests.exceptions.JSONDecodeError(
                    "Expecting value", "bad", 0
                ),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )
        assert exc_info.value.status_code == 401
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )

        with (
            patch(
                "requests.get",
                side_effect=requests.exceptions.Timeout(
                    f"Timeout hitting ?access_token={access_token}"
                ),
            ),
            caplog.at_level(logging.INFO, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )
        assert exc_info.value.status_code == 401
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )
        assert access_token not in caplog.text

        missing_email_resp = MagicMock(status_code=200)
        missing_email_resp.json.return_value = {"scope": "openid"}
        with (
            patch("requests.get", return_value=missing_email_resp),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid Google access token."


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
