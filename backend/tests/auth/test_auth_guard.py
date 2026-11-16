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

import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError
from google.auth import crypt as google_auth_crypt
from google.auth import exceptions as google_auth_exceptions
from google.auth import jwt as google_auth_jwt
import pytest
import requests

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


def _make_rsa_cert_and_tokens() -> tuple[str, str, str]:
    """Generates an ephemeral RSA keypair and signed valid/expired OIDC JWTs."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    signer = google_auth_crypt.RSASigner.from_string(
        private_pem, key_id="test-kid"
    )
    now = int(time.time())
    base_claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "email": "user@example.com",
        "name": "RSA User",
        "hd": "example.com",
    }
    valid_jwt = google_auth_jwt.encode(
        signer, {**base_claims, "iat": now - 60, "exp": now + 3600}
    ).decode("ascii")
    expired_jwt = google_auth_jwt.encode(
        signer, {**base_claims, "iat": now - 7200, "exp": now - 3600}
    ).decode("ascii")
    return public_pem, valid_jwt, expired_jwt


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
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_ORGS_STR = ""
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
        mock_verify.return_value = {"name": "Test User"}

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
            exc_info.value.detail
            == "User is not authorized to access this application."
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_get_current_user_allowed_emails_fail(
        self, mock_verify, mock_user_service, mock_request, caplog
    ):
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_EMAILS_STR = "allowed@example.com"
        mock_verify.return_value = {
            "email": "denied@example.com",
            "name": "Denied User",
            "hd": "example.com",
        }

        with (
            caplog.at_level(logging.WARNING, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
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
        assert "denied@example.com" in caplog.text
        assert [
            r.levelno
            for r in caplog.records
            if r.name == "src.auth.auth_guard" and r.levelno == logging.WARNING
        ] == [logging.WARNING]

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
            "email": "user@example.com",
            "name": "Example User",
            "picture": "http://example.com/pic.jpg",
            "hd": "example.com",
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
    async def test_local_expired_firebase_wins_over_oidc_invalid_401(
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
    async def test_local_firebase_cert_fetch_error_returns_503(
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

        assert exc_info.value.status_code == 503
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_local_firebase_error_surfaces_oidc_transport_503(
        self, mock_verify_fb, mock_verify_oidc, mock_user_service, mock_request
    ):
        config_service.ENVIRONMENT = "local"
        mock_verify_fb.side_effect = auth.InvalidIdTokenError(
            "Not a Firebase token"
        )
        mock_verify_oidc.side_effect = google_auth_exceptions.TransportError(
            "Connection timed out to oauth2.googleapis.com"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                token="oidc_token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 503
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("oidc_exc", "expected_detail"),
        [
            (
                google_auth_exceptions.InvalidValue(
                    "Token expired, 1700000000 < 1700000500"
                ),
                "Authentication token has expired.",
            ),
            (
                ValueError("EXPIRED signature window"),
                "Authentication token has expired.",
            ),
            (
                google_auth_exceptions.MalformedError(
                    "Wrong number of segments in token: raw_secret"
                ),
                "Invalid authentication token.",
            ),
            (
                ValueError("Wrong recipient, expected test-client-id"),
                "Invalid authentication token.",
            ),
            (
                google_auth_exceptions.GoogleAuthError("Wrong issuer"),
                "Invalid authentication token.",
            ),
        ],
    )
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_non_local_oidc_errors_map_to_401_and_log_once(
        self,
        mock_verify_fb,
        mock_verify_oidc,
        mock_user_service,
        mock_request,
        caplog,
        oidc_exc,
        expected_detail,
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.side_effect = oidc_exc

        with caplog.at_level(logging.INFO, logger="src.auth.auth_guard"):
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
        auth_levels = [
            r.levelno for r in caplog.records if r.name == "src.auth.auth_guard"
        ]
        assert auth_levels == [logging.WARNING]

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    async def test_non_local_oidc_transport_error_returns_503(
        self, mock_verify_oidc, mock_user_service, mock_request, caplog
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.side_effect = google_auth_exceptions.TransportError(
            "Metadata server 169.254.169.254 unreachable"
        )

        with caplog.at_level(logging.INFO, logger="src.auth.auth_guard"):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=mock_request,
                    token="valid_oidc_token",
                    user_service=mock_user_service,
                )

        assert exc_info.value.status_code == 503
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )
        auth_levels = [
            r.levelno for r in caplog.records if r.name == "src.auth.auth_guard"
        ]
        assert auth_levels == [logging.WARNING]

    @pytest.mark.anyio
    async def test_real_google_auth_library_valid_expired_malformed_and_503(
        self, mock_user_service, mock_request, caplog
    ):
        config_service.ENVIRONMENT = "prod"
        public_pem, valid_jwt, expired_jwt = _make_rsa_cert_and_tokens()
        certs_payload = json.dumps({"test-kid": public_pem}).encode("utf-8")

        def ok_transport():
            return lambda _url, method="GET": SimpleNamespace(
                status=200, data=certs_payload
            )

        with patch(
            "src.auth.auth_guard.google_auth_requests.Request",
            side_effect=ok_transport,
        ):
            user = await get_current_user(
                request=mock_request,
                token=valid_jwt,
                user_service=mock_user_service,
            )
            assert user.email == "test@example.com"

            caplog.clear()
            with caplog.at_level(logging.INFO, logger="src.auth.auth_guard"):
                with pytest.raises(HTTPException) as expired_exc:
                    await get_current_user(
                        request=mock_request,
                        token=expired_jwt,
                        user_service=mock_user_service,
                    )
            assert expired_exc.value.status_code == 401
            assert (
                expired_exc.value.detail == "Authentication token has expired."
            )
            assert [
                r.levelno
                for r in caplog.records
                if r.name == "src.auth.auth_guard"
            ] == [logging.WARNING]

            # Single-segment / bad-header tokens trigger google-auth's segment
            # messages without echoing the full token; logs must redact them.
            for bad_token, leaked_fragment, expected_reason in (
                (
                    "opaque-secret-token",
                    "opaque-secret-token",
                    "Wrong number of segments",
                ),
                (
                    "bm90LWpzb24.e30.c2ln",
                    "bm90LWpzb24",
                    "Can't parse segment",
                ),
            ):
                caplog.clear()
                with caplog.at_level(
                    logging.INFO, logger="src.auth.auth_guard"
                ):
                    with pytest.raises(HTTPException) as bad_exc:
                        await get_current_user(
                            request=mock_request,
                            token=bad_token,
                            user_service=mock_user_service,
                        )
                assert bad_exc.value.status_code == 401
                assert bad_exc.value.detail == "Invalid authentication token."
                assert leaked_fragment not in caplog.text
                assert "[REDACTED]" in caplog.text
                assert expected_reason in caplog.text
                assert [
                    r.levelno
                    for r in caplog.records
                    if r.name == "src.auth.auth_guard"
                ] == [logging.WARNING]

        def failing_transport():
            return lambda _url, method="GET": SimpleNamespace(
                status=503, data=b"upstream down"
            )

        with patch(
            "src.auth.auth_guard.google_auth_requests.Request",
            side_effect=failing_transport,
        ):
            with pytest.raises(HTTPException) as outage_exc:
                await get_current_user(
                    request=mock_request,
                    token=valid_jwt,
                    user_service=mock_user_service,
                )
        assert outage_exc.value.status_code == 503
        assert (
            outage_exc.value.detail
            == "Failed to contact Google authentication server."
        )

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
            "email": "user@example.com",
            "name": "Example User",
            "hd": "example.com",
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

        missing_resp = client.get("/protected")
        assert missing_resp.status_code == 401
        assert missing_resp.json() == {
            "detail": "Missing authentication token."
        }

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

        user_ok = client.get(
            "/protected",
            headers={"Authorization": "Bearer valid-jwt"},
        )
        assert user_ok.status_code == 200
        assert user_ok.json() == {
            "email": "test@example.com",
            "is_agent": False,
        }

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

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("response_kwargs", "expected_detail"),
        [
            (
                {"status_code": 400, "text": "leaked_token_body"},
                "Invalid Google access token.",
            ),
            (
                {"status_code": 200, "json_data": {"scope": "openid"}},
                "Invalid Google access token.",
            ),
        ],
    )
    async def test_ya29_invalid_token_returns_sanitized_401(
        self,
        mock_user_service,
        mock_request,
        caplog,
        response_kwargs,
        expected_detail,
    ):
        config_service.ENVIRONMENT = "prod"
        access_token = "ya29" + ".fake_access_token_secret"
        mock_resp = MagicMock(
            status_code=response_kwargs["status_code"],
            text=response_kwargs.get("text", ""),
        )
        if "json_data" in response_kwargs:
            mock_resp.json.return_value = response_kwargs["json_data"]

        with (
            patch("requests.get", return_value=mock_resp),
            caplog.at_level(logging.INFO, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == expected_detail
        assert "fake_access_token_secret" not in caplog.text

    @pytest.mark.anyio
    @pytest.mark.parametrize("status_code", [429, 503])
    async def test_ya29_tokeninfo_unavailable_returns_503(
        self,
        mock_user_service,
        mock_request,
        caplog,
        status_code,
    ):
        config_service.ENVIRONMENT = "prod"
        access_token = "ya29" + ".fake_access_token_secret"
        mock_resp = MagicMock(status_code=status_code, text="rate limited")

        with (
            patch("requests.get", return_value=mock_resp),
            caplog.at_level(logging.INFO, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 503
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )
        assert access_token not in caplog.text

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    @patch("src.auth.auth_guard.auth.verify_id_token")
    async def test_wrapped_malformed_error_redacts_base64_payload_in_logs(
        self,
        mock_verify,
        mock_verify_oidc,
        mock_user_service,
        mock_request,
        caplog,
    ):
        config_service.ENVIRONMENT = "local"
        wrapped = auth.InvalidIdTokenError(
            "Invalid token",
            cause=google_auth_exceptions.MalformedError(
                "Extra payload segment: eyJzdWIiOiJzZWNyZXQifQ"
            ),
        )
        mock_verify.side_effect = wrapped
        mock_verify_oidc.side_effect = google_auth_exceptions.MalformedError(
            "Wrong number of segments in token eyJbad.eyJzdWIiOiJzZWNyZXQifQ.sig"
        )

        with (
            caplog.at_level(logging.INFO, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token="eyJbad.eyJzdWIiOiJzZWNyZXQifQ.sig",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid authentication token."
        assert "eyJzdWIiOiJzZWNyZXQifQ" not in caplog.text
        assert "[REDACTED]" in caplog.text
        assert "Extra payload segment" in caplog.text
        assert "Wrong number of segments" in caplog.text

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("err_msg", "expected_reason"),
        [
            (
                "Token has wrong signature: eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln",
                "Token has wrong signature",
            ),
            (
                "Certificate for key id 0123456789abcdef0123456789abcdef01234567 not found",
                "Certificate for key id 0123456789abcdef0123456789abcdef01234567 not found",
            ),
            (
                "Wrong number of segments in AbCdEfGhIjKlMnOpQrStUvWxYz123456",
                "Wrong number of segments",
            ),
        ],
    )
    @patch("src.auth.auth_guard.id_token.verify_oauth2_token")
    async def test_sanitize_auth_error_keeps_diagnostic_reason_and_redacts_secrets(
        self,
        mock_verify_oidc,
        mock_user_service,
        mock_request,
        caplog,
        err_msg,
        expected_reason,
    ):
        config_service.ENVIRONMENT = "prod"
        mock_verify_oidc.side_effect = google_auth_exceptions.MalformedError(
            err_msg
        )

        with (
            caplog.at_level(logging.WARNING, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=mock_request,
                token="bad-token",
                user_service=mock_user_service,
            )

        assert exc_info.value.status_code == 401
        assert expected_reason in caplog.text
        assert "eyJhbGciOiJSUzI1NiJ9" not in caplog.text
        assert "AbCdEfGhIjKlMnOpQrStUvWxYz123456" not in caplog.text

    @pytest.mark.anyio
    async def test_ya29_transport_and_json_errors_return_503_and_redact(
        self, mock_user_service, mock_request, caplog
    ):
        config_service.ENVIRONMENT = "prod"
        access_token = "ya29" + ".fake_access_token_secret"

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

        assert exc_info.value.status_code == 503
        assert (
            exc_info.value.detail
            == "Failed to contact Google authentication server."
        )
        assert access_token not in caplog.text
        assert [
            r.levelno
            for r in caplog.records
            if r.name == "src.auth.auth_guard" and r.levelno >= logging.WARNING
        ] == [logging.WARNING]

        bad_json_resp = MagicMock(status_code=200)
        bad_json_resp.json.side_effect = requests.exceptions.JSONDecodeError(
            "Expecting value", "bad", 0
        )
        caplog.clear()
        with (
            patch("requests.get", return_value=bad_json_resp),
            caplog.at_level(logging.INFO, logger="src.auth.auth_guard"),
            pytest.raises(HTTPException) as json_exc,
        ):
            await get_current_user(
                request=mock_request,
                token=access_token,
                user_service=mock_user_service,
            )

        assert json_exc.value.status_code == 503
        assert (
            json_exc.value.detail
            == "Failed to contact Google authentication server."
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
