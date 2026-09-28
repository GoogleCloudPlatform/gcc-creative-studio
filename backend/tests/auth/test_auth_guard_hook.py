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

"""Tests for the post-auth hook in auth_guard and handle_post_auth_session (Q14)."""

import base64
from contextlib import asynccontextmanager
import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet
from fastapi import Request
import pytest

from src.auth.auth_guard import (
    clear_post_auth_hooks,
    get_current_user,
    get_post_auth_hooks,
    register_post_auth_hook,
)
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.queue.workflow_dispatcher import (
    handle_post_auth_session,
    reset_dispatch_tick_throttle,
    should_run_throttled_tick,
)

pytestmark = pytest.mark.anyio

FIXED_NOW = datetime.datetime(2026, 9, 28, 12, 0, 0, tzinfo=datetime.UTC)


def _make_jwt(exp: int) -> str:
    hdr = (
        base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode("ascii").rstrip("=")
    )
    body = (
        base64.urlsafe_b64encode(
            json.dumps({"email": "u@example.com", "exp": exp}).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    return f"{hdr}.{body}.sig"


@pytest.fixture(autouse=True)
def _clean_hooks(monkeypatch):
    from src.config.config_service import config_service

    monkeypatch.setattr(config_service, "ALLOWED_ORGS_STR", "")
    saved = get_post_auth_hooks()
    clear_post_auth_hooks()
    reset_dispatch_tick_throttle()
    yield
    clear_post_auth_hooks()
    for hook in saved:
        register_post_auth_hook(hook)


def _make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {"type": "http", "headers": raw_headers}
    return Request(scope)


def _make_user_service() -> MagicMock:
    service = MagicMock()
    service.create_user_if_not_exists = AsyncMock(
        return_value=UserModel(
            id=11,
            email="u@example.com",
            name="Test User",
            picture="https://example.com/p.png",
            roles=[UserRoleEnum.USER],
        )
    )
    return service


async def test_post_auth_hook_invoked_with_exp_for_id_token():
    called_with: list[tuple[UserModel, str, int | None]] = []

    async def hook(user: UserModel, token: str, exp: int | None) -> None:
        called_with.append((user, token, exp))

    register_post_auth_hook(hook)
    jwt_token = _make_jwt(1890000000)

    with patch(
        "src.auth.auth_guard.auth.verify_id_token",
        return_value={
            "email": "u@example.com",
            "name": "Test User",
            "picture": "https://example.com/p.png",
            "exp": 1890000000,
        },
    ):
        user = await get_current_user(
            request=_make_request(),
            token=jwt_token,
            user_service=_make_user_service(),
        )

    assert user.id == 11
    assert len(called_with) == 1
    assert called_with[0] == (user, jwt_token, 1890000000)


async def test_post_auth_hook_skipped_for_ya29_access_token():
    hook = AsyncMock()
    register_post_auth_hook(hook)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "email": "u@example.com",
        "name": "Agent User",
    }

    with patch("requests.get", return_value=mock_resp):
        user = await get_current_user(
            request=_make_request(),
            token="ya29.a0AfH6SMBx_access_token",
            user_service=_make_user_service(),
        )

    assert user.id == 11
    hook.assert_not_called()


async def test_post_auth_hook_skipped_for_x_user_authorization_agent_header():
    hook = AsyncMock()
    register_post_auth_hook(hook)
    jwt_token = _make_jwt(1890000000)

    with patch(
        "src.auth.auth_guard.auth.verify_id_token",
        return_value={
            "email": "u@example.com",
            "name": "Test User",
            "exp": 1890000000,
        },
    ):
        user = await get_current_user(
            request=_make_request(
                {"X-User-Authorization": f"Bearer {jwt_token}"}
            ),
            token=None,
            user_service=_make_user_service(),
        )

    assert user.id == 11
    hook.assert_not_called()


async def test_post_auth_hook_exception_never_breaks_authentication():
    async def failing_hook(user: UserModel, token: str, exp: int | None):
        del user, token, exp
        raise RuntimeError("Database temporarily unavailable")

    register_post_auth_hook(failing_hook)
    jwt_token = _make_jwt(1890000000)

    with patch(
        "src.auth.auth_guard.auth.verify_id_token",
        return_value={
            "email": "u@example.com",
            "name": "Test User",
            "exp": 1890000000,
        },
    ):
        user = await get_current_user(
            request=_make_request(),
            token=jwt_token,
            user_service=_make_user_service(),
        )

    assert user.id == 11


async def test_handle_post_auth_session_unparks_and_dispatches_with_throttle(
    monkeypatch: pytest.MonkeyPatch,
):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(
        "src.config.config_service.config_service.WORKFLOW_TOKEN_ENCRYPTION_KEY",
        key,
    )
    exp_ts = int((FIXED_NOW + datetime.timedelta(hours=1)).timestamp())
    jwt_token = _make_jwt(exp_ts)
    user = UserModel(
        id=5,
        email="u@example.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    fake_db = AsyncMock()
    unpark_result = MagicMock()
    unpark_result.scalars.return_value.all.return_value = []
    due_result = MagicMock()
    due_result.scalar_one_or_none.return_value = "run-due-1"
    fake_db.execute = AsyncMock(
        side_effect=[MagicMock(), unpark_result, due_result]
    )

    @asynccontextmanager
    async def fake_session_factory():
        yield fake_db

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch = AsyncMock(return_value=[])

    await handle_post_auth_session(
        user,
        jwt_token,
        exp_ts,
        session_factory=fake_session_factory,
        dispatcher_factory=lambda **_: mock_dispatcher,
        clock=lambda: FIXED_NOW,
    )

    mock_dispatcher.dispatch.assert_awaited_once_with(trigger="tick", user_id=5)
    # Immediate second check within throttle interval returns False.
    assert (
        should_run_throttled_tick(
            min_interval_seconds=10.0, monotonic_now=100.0
        )
        is False
    )
