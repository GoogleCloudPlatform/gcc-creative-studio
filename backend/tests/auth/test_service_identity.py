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
"""Tests for calls the backend makes to itself while running a workflow.

Cloud Workflows and the workflow executor cannot pass through IAP, so they
call the backend directly with a Google-signed token for the backend's own
service account, plus the ID of the user who started the run.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from src.auth.auth_guard import (
    get_current_user,
    get_iap_jwt,
    require_workflow_service_caller,
)
from src.config.config_service import config_service
from src.users.user_model import UserModel

INTERNAL_URL = "https://cstudio-be-123.us-central1.run.app"
BACKEND_SA = "cs-be-run@proj.iam.gserviceaccount.com"
VERIFY = "src.auth.auth_guard.id_token.verify_oauth2_token"


@pytest.fixture(autouse=True)
def service_identity_config(monkeypatch):
    monkeypatch.setattr(config_service, "ENVIRONMENT", "production")
    monkeypatch.setattr(config_service, "BACKEND_INTERNAL_URL", INTERNAL_URL)
    monkeypatch.setattr(
        config_service, "BACKEND_SERVICE_ACCOUNT_EMAIL", BACKEND_SA
    )


def _request(headers: dict[str, str]) -> MagicMock:
    request = MagicMock(spec=Request)
    request.headers = headers
    return request


def _service_request(acting_user_id: str = "7") -> MagicMock:
    return _request(
        {
            "authorization": "Bearer signed-token",
            "x-acting-user-id": acting_user_id,
        }
    )


def _user_service(user: UserModel | None) -> AsyncMock:
    service = AsyncMock()
    service.user_repo.get_by_id = AsyncMock(return_value=user)
    return service


ACTING_USER = UserModel(
    id=7, email="creator@example.com", name="Creator", roles=["user"]
)
GOOD_CLAIMS = {"email": BACKEND_SA, "email_verified": True}


@pytest.mark.anyio
async def test_service_call_acts_as_the_named_user():
    request = _service_request()
    token = await get_iap_jwt(request=request, x_goog_iap_jwt_assertion=None)

    with patch(VERIFY, return_value=GOOD_CLAIMS):
        user = await get_current_user(
            request=request,
            token=token,
            user_service=_user_service(ACTING_USER),
        )

    assert user.id == 7


@pytest.mark.anyio
async def test_service_token_is_checked_for_the_direct_url():
    """The token must be issued for our direct URL, not any audience."""
    with patch(VERIFY, return_value=GOOD_CLAIMS) as verify:
        await get_current_user(
            request=_service_request(),
            token=None,
            user_service=_user_service(ACTING_USER),
        )

    assert verify.call_args.kwargs["audience"] == INTERNAL_URL


@pytest.mark.anyio
async def test_service_call_never_creates_users():
    user_service = _user_service(ACTING_USER)

    with patch(VERIFY, return_value=GOOD_CLAIMS):
        await get_current_user(
            request=_service_request(), token=None, user_service=user_service
        )

    user_service.create_user_if_not_exists.assert_not_called()


@pytest.mark.anyio
async def test_token_for_another_service_account_is_refused():
    request = _service_request()
    claims = {
        "email": "attacker@proj.iam.gserviceaccount.com",
        "email_verified": True,
    }

    with patch(VERIFY, return_value=claims):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=request,
                token=None,
                user_service=_user_service(ACTING_USER),
            )

    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_unverified_email_is_refused():
    claims = {"email": BACKEND_SA, "email_verified": False}

    with patch(VERIFY, return_value=claims):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=_service_request(),
                token=None,
                user_service=_user_service(ACTING_USER),
            )

    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_bad_signature_is_refused():
    with patch(VERIFY, side_effect=ValueError("bad signature")):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=_service_request(),
                token=None,
                user_service=_user_service(ACTING_USER),
            )

    assert exc_info.value.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("acting_user_id", ["", "abc", "-1"])
async def test_malformed_acting_user_is_refused(acting_user_id):
    with patch(VERIFY, return_value=GOOD_CLAIMS):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=_service_request(acting_user_id),
                token=None,
                user_service=_user_service(ACTING_USER),
            )

    assert exc_info.value.status_code == 401


DELETED_USER = ACTING_USER.model_copy(
    update={"deleted_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)}
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "found", [None, DELETED_USER], ids=["unknown", "deleted"]
)
async def test_unknown_or_deleted_user_is_refused(found):
    with patch(VERIFY, return_value=GOOD_CLAIMS):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=_service_request(),
                token=None,
                user_service=_user_service(found),
            )

    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_path_is_off_when_no_direct_url_is_configured(monkeypatch):
    monkeypatch.setattr(config_service, "BACKEND_INTERNAL_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await get_iap_jwt(
            request=_service_request(), x_goog_iap_jwt_assertion=None
        )

    assert exc_info.value.status_code == 401
    assert "Missing X-Goog-Iap-Jwt-Assertion" in exc_info.value.detail


@pytest.mark.anyio
async def test_executor_endpoints_refuse_signed_in_users():
    """A browser user coming through IAP must not call the executor."""
    request = _request({"x-goog-iap-jwt-assertion": "iap-token"})

    with pytest.raises(HTTPException) as exc_info:
        await require_workflow_service_caller(
            request=request, user_service=_user_service(ACTING_USER)
        )

    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_executor_endpoints_accept_the_service_caller():
    with patch(VERIFY, return_value=GOOD_CLAIMS):
        user = await require_workflow_service_caller(
            request=_service_request(),
            user_service=_user_service(ACTING_USER),
        )

    assert user.id == 7
