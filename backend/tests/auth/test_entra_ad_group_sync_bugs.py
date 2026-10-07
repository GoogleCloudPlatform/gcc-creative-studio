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
"""Regression tests that keep fixed sign-in defects from coming back.

App roles come from Microsoft Graph, never from the IAP token.
"""

import datetime
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException, Request

from src.auth.auth_guard import get_current_user
from src.auth.entra_graph_client import EntraGraphClient
from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService

REPO_ROOT = Path(__file__).resolve().parents[3]


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


class TestRoleSourceIsNotTheIapToken:
    def test_wif_attribute_mapping_uses_oid_and_groups_only_for_iap(self):
        """The pool keys users by Entra object ID and passes groups to IAP.

        The object ID never changes, so it identifies each user. The Entra
        groups are passed through only so IAP can check the access group.
        App roles never come from the sign-in token (see the next test).
        """
        content = (
            REPO_ROOT / "infra/modules/iap-load-balancer/main.tf"
        ).read_text(encoding="utf-8")
        assert re.search(r'"google\.subject"\s*=\s*"assertion\.oid"', content)
        assert re.search(r'"google\.groups"\s*=\s*"assertion\.groups"', content)

    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_guard_ignores_group_and_role_claims(self, mock_verify):
        mock_verify.return_value = {
            "iss": "https://cloud.google.com/iap",
            "email": "alice@company.com",
            "name": "Alice",
            "groups": ["11111111-1111-1111-1111-111111111111"],
            "roles": ["admin"],
            "google": {"groups": ["admins"]},
        }
        user_service = AsyncMock()
        user_service.create_user_if_not_exists.return_value = _user()

        await get_current_user(
            request=MagicMock(spec=Request),
            token="jwt",
            user_service=user_service,
        )

        user_service.create_user_if_not_exists.assert_called_once_with(
            email="alice@company.com", name="Alice", picture=""
        )


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
    async def test_sub_only_token_is_rejected_when_allowed_orgs_set(
        self, mock_verify, monkeypatch
    ):
        """A Workforce token with no email still gets the org allowlist.

        The email Graph returns for the object ID is outside the allowed
        organization, so sign-in is refused before any account is created.
        """
        monkeypatch.setattr(
            config_service, "ALLOWED_ORGS_STR", "yourcompany.com"
        )
        mock_verify.return_value = {
            "iss": "https://cloud.google.com/iap",
            "sub": "principal://iam.googleapis.com/locations/global/"
            "workforcePools/pool/subject/11111111-2222-3333-4444-555555555555",
        }
        repo = AsyncMock()
        repo.get_by_entra_oid.return_value = None
        repo.get_by_email.return_value = None
        graph = MagicMock()
        graph.get_user_profile = AsyncMock(
            return_value=("bob@other.com", "Bob", {"bob@other.com"})
        )

        with (
            patch(
                "src.users.user_service.get_entra_graph_client",
                return_value=graph,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(
                request=MagicMock(spec=Request),
                token="jwt",
                user_service=UserService(user_repo=repo),
            )

        assert exc_info.value.status_code == 401
        assert "not part of an allowed organization" in exc_info.value.detail
        repo.create_or_get_existing.assert_not_called()

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


_ADMIN_GROUP = "aaaaaaaa-0000-0000-0000-000000000001"
_TOKEN_OK = {"json": {"access_token": "tok", "expires_in": 3600}}


class TestMalformedGraphResponsesFailClosedWithoutLogout:
    """A 200 with an unreadable Graph or token body is a Graph failure.

    It must not raise 401 or 500 (which would log the user out). It removes
    privileged roles and advances the role check time.
    """

    @pytest.mark.parametrize(
        "token_response, graph_response",
        [
            pytest.param(
                {"content": b"<html>login</html>"},
                {"json": {}},
                id="a-token-non-json",
            ),
            pytest.param(
                _TOKEN_OK, {"content": b"not json"}, id="b-graph-non-json"
            ),
            pytest.param(
                {"json": {"token_type": "Bearer", "expires_in": 3600}},
                {"json": {}},
                id="c-token-missing-access-token",
            ),
        ],
    )
    @pytest.mark.anyio
    @patch("src.auth.auth_guard.id_token.verify_token")
    async def test_malformed_body_removes_privileged_roles_and_advances_marker(
        self, mock_verify, token_response, graph_response
    ):
        mock_verify.return_value = {
            "iss": "https://cloud.google.com/iap",
            "email": "alice@company.com",
        }
        stale_marker = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=601
        )
        stale_user = _user(
            roles=[UserRoleEnum.USER, UserRoleEnum.ADMIN],
            roles_checked_at=stale_marker,
        )
        repo = AsyncMock()
        repo.get_by_email.return_value = stale_user
        repo.update.side_effect = lambda uid, data: stale_user.model_copy(
            update=data
        )
        responses = {
            "login.microsoftonline.com": token_response,
            "graph.microsoft.com": graph_response,
        }
        graph_client = EntraGraphClient(
            "tenant",
            "client",
            "secret",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, **responses[request.url.host]
                    )
                )
            ),
        )
        sync_config = SimpleNamespace(
            ENTRA_ROLE_SYNC_ENABLED=True,
            ENTRA_ROLE_SYNC_TTL_SECONDS=600,
            ENTRA_GROUP_ROLES={_ADMIN_GROUP: frozenset({"admin"})},
            ADMIN_USER_EMAIL="system",
        )

        with (
            patch("src.users.user_service.config_service", sync_config),
            patch(
                "src.users.user_service.get_entra_graph_client",
                return_value=graph_client,
            ),
        ):
            user = await get_current_user(
                request=MagicMock(spec=Request),
                token="jwt",
                user_service=UserService(user_repo=repo),
            )

        assert {UserRoleEnum(r) for r in user.roles} == {UserRoleEnum.USER}
        repo.update.assert_called_once()
        uid, updates = repo.update.call_args.args
        assert uid == stale_user.id
        assert updates["roles"] == ["user"]
        assert updates["roles_checked_at"] > stale_marker
