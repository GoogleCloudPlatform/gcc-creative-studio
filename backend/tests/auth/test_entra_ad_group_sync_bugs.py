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
"""Regression tests that keep fixed sign-in defects from coming back."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from src.auth.auth_guard import get_current_user
from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService


@pytest.fixture(autouse=True)
def _iap_production_config(monkeypatch):
    monkeypatch.setattr(config_service, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        config_service, "IAP_EXPECTED_AUDIENCE", "test-iap-audience"
    )
    monkeypatch.setattr(config_service, "ALLOWED_ORGS_STR", "")


def _user(**overrides) -> UserModel:
    fields = {
        "id": 1,
        "email": "alice@company.com",
        "name": "Alice",
        "roles": [UserRoleEnum.USER],
        "picture": "",
    }
    fields.update(overrides)
    return UserModel(**fields)


class TestAuthDefectsStayFixed:
    def test_auth_session_endpoint_stays_removed(self, api_client):
        """IAP is the only login path, so POST /api/auth/session is gone."""
        assert api_client.post("/api/auth/session").status_code == 404

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_mixed_case_upn_domain_passes_allowed_orgs(
        self, mock_verify, monkeypatch
    ):
        monkeypatch.setattr(
            config_service, "ALLOWED_ORGS_STR", "yourcompany.com"
        )
        mock_verify.return_value = {
            "iss": "https://cloud.google.com/iap",
            "upn": "Alice.Smith@YourCompany.com",
        }
        user_service = AsyncMock()
        user_service.create_user_if_not_exists.return_value = _user()

        await get_current_user(
            request=MagicMock(spec=Request),
            token="jwt",
            user_service=user_service,
        )

        user_service.create_user_if_not_exists.assert_called_once()
        call = user_service.create_user_if_not_exists.call_args
        assert call.kwargs["email"] == "Alice.Smith@YourCompany.com"

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_soft_deleted_user_gets_403_not_500(self, mock_verify):
        mock_verify.return_value = {
            "iss": "https://cloud.google.com/iap",
            "email": "gone@company.com",
            "name": "Gone",
        }
        repo = AsyncMock()
        repo.get_by_email.return_value = _user(
            email="gone@company.com", deleted_at="2026-01-01T00:00:00Z"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=MagicMock(spec=Request),
                token="jwt",
                user_service=UserService(user_repo=repo),
            )

        assert exc_info.value.status_code == 403
        repo.create_or_get_existing.assert_not_called()
