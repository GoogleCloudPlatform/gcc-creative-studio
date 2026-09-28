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

"""Unit tests for TokenStoreService and WorkflowUserSessionRepository (§8.5, Q3, Q14, E19)."""

import base64
import datetime
import json
import logging
from unittest.mock import AsyncMock, MagicMock

from cryptography.fernet import Fernet
import pytest
from sqlalchemy.dialects import postgresql

from src.workflows.schema.workflow_run_model import WorkflowUserSessionModel
from src.workflows.session.token_store_service import (
    PLACEHOLDER_SECRET_VALUE,
    TokenStoreService,
    WorkflowUserSessionRepository,
    extract_jwt_expiration,
    is_jwt_id_token,
)

pytestmark = pytest.mark.anyio

FIXED_NOW = datetime.datetime(2026, 9, 28, 12, 0, 0, tzinfo=datetime.UTC)


def _make_jwt(exp: int | float | None) -> str:
    header = (
        base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}')
        .decode("ascii")
        .rstrip("=")
    )
    payload_dict = {"sub": "user-123", "email": "user@example.com"}
    if exp is not None:
        payload_dict["exp"] = exp
    payload = (
        base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    return f"{header}.{payload}.signature_part"


@pytest.fixture(name="fernet_key")
def fixture_fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture(name="rotated_fernet_key")
def fixture_rotated_fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _make_session_repo(
    row: WorkflowUserSessionModel | None = None,
) -> tuple[WorkflowUserSessionRepository, AsyncMock]:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return WorkflowUserSessionRepository(db=db), db


async def test_fernet_encrypt_decrypt_round_trip(fernet_key: str):
    repo, _ = _make_session_repo()
    service = TokenStoreService(
        repository=repo,
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    raw_token = _make_jwt((FIXED_NOW + datetime.timedelta(hours=1)).timestamp())

    assert service.is_enabled is True
    ciphertext = service.encrypt_token(raw_token)
    assert ciphertext is not None
    assert ciphertext != raw_token
    assert raw_token not in ciphertext
    assert service.decrypt_token(ciphertext) == raw_token


async def test_store_token_upserts_only_when_fresher_and_get_valid_token(
    fernet_key: str,
):
    repo, db = _make_session_repo()
    service = TokenStoreService(
        repository=repo,
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    exp_dt = FIXED_NOW + datetime.timedelta(hours=1)
    raw_token = _make_jwt(exp_dt.timestamp())

    stored = await service.store_token(42, f"Bearer {raw_token}", commit=True)
    assert stored is True
    db.commit.assert_awaited_once()

    stmt = db.execute.await_args.args[0]
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO workflow_user_sessions" in compiled
    assert "ON CONFLICT (user_id) DO UPDATE" in compiled
    assert (
        "workflow_user_sessions.token_expires_at < excluded.token_expires_at"
        in compiled
    )

    encrypted = service.encrypt_token(raw_token)
    repo_with_row, _ = _make_session_repo(
        WorkflowUserSessionModel(
            user_id=42,
            encrypted_token=encrypted,
            token_expires_at=exp_dt,
        )
    )
    reader = TokenStoreService(
        repository=repo_with_row,
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    assert await reader.get_valid_token(42) == raw_token


async def test_get_valid_token_returns_none_when_expired_or_within_ttl_buffer(
    fernet_key: str,
):
    raw_token = _make_jwt(
        (FIXED_NOW + datetime.timedelta(seconds=90)).timestamp()
    )
    temp_service = TokenStoreService(
        repository=WorkflowUserSessionRepository(db=AsyncMock()),
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    ciphertext = temp_service.encrypt_token(raw_token)

    # 90s remaining <= 120s min TTL buffer -> treated as expired.
    repo, _ = _make_session_repo(
        WorkflowUserSessionModel(
            user_id=7,
            encrypted_token=ciphertext,
            token_expires_at=FIXED_NOW + datetime.timedelta(seconds=90),
        )
    )
    service = TokenStoreService(
        repository=repo,
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    assert await service.get_valid_token(7) is None


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "   ",
        PLACEHOLDER_SECRET_VALUE,
        "not-a-valid-fernet-key",
        f"{Fernet.generate_key().decode('ascii')},{PLACEHOLDER_SECRET_VALUE}",
    ],
)
async def test_missing_placeholder_or_invalid_key_disables_store_without_crashing(
    bad_key: str,
    caplog: pytest.LogCaptureFixture,
):
    repo, db = _make_session_repo()
    with caplog.at_level(logging.WARNING):
        service = TokenStoreService(
            repository=repo,
            encryption_key=bad_key,
            clock=lambda: FIXED_NOW,
        )

    assert service.is_enabled is False
    raw_token = _make_jwt((FIXED_NOW + datetime.timedelta(hours=1)).timestamp())
    assert await service.store_token(1, raw_token) is False
    assert await service.get_valid_token(1) is None
    db.execute.assert_not_called()
    # Never log the key value itself.
    if bad_key.strip() and bad_key != PLACEHOLDER_SECRET_VALUE:
        assert bad_key not in caplog.text


async def test_rotated_key_catches_invalid_token_and_multifernet_supports_rotation(
    fernet_key: str,
    rotated_fernet_key: str,
):
    raw_token = _make_jwt((FIXED_NOW + datetime.timedelta(hours=1)).timestamp())
    old_service = TokenStoreService(
        repository=WorkflowUserSessionRepository(db=AsyncMock()),
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    old_ciphertext = old_service.encrypt_token(raw_token)

    repo, _ = _make_session_repo(
        WorkflowUserSessionModel(
            user_id=9,
            encrypted_token=old_ciphertext,
            token_expires_at=FIXED_NOW + datetime.timedelta(hours=1),
        )
    )

    # Single rotated key without old key -> InvalidToken caught -> returns None (E19).
    rotated_only = TokenStoreService(
        repository=repo,
        encryption_key=rotated_fernet_key,
        clock=lambda: FIXED_NOW,
    )
    assert await rotated_only.get_valid_token(9) is None

    # MultiFernet with "new_key,old_key" -> decrypts old_ciphertext cleanly!
    multi_service = TokenStoreService(
        repository=repo,
        encryption_key=f"{rotated_fernet_key},{fernet_key}",
        clock=lambda: FIXED_NOW,
    )
    assert await multi_service.get_valid_token(9) == raw_token


@pytest.mark.parametrize(
    "rejected_token",
    [
        "ya29.a0AfH6SMBx_access_token",
        "Bearer ya29.a0AfH6SMBx.with.dots",
        "not-a-jwt",
        "two.parts",
        "",
    ],
)
async def test_ya29_and_non_jwt_tokens_are_rejected(
    fernet_key: str,
    rejected_token: str,
):
    repo, db = _make_session_repo()
    service = TokenStoreService(
        repository=repo,
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    assert is_jwt_id_token(rejected_token) is False
    assert extract_jwt_expiration(rejected_token) is None
    assert await service.store_token(1, rejected_token) is False
    db.execute.assert_not_called()


async def test_touch_last_dispatched_at_upserts_session_row(fernet_key: str):
    repo, db = _make_session_repo()
    service = TokenStoreService(
        repository=repo,
        encryption_key=fernet_key,
        clock=lambda: FIXED_NOW,
    )
    await service.touch_last_dispatched_at(15)

    stmt = db.execute.await_args.args[0]
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO workflow_user_sessions" in compiled
    assert "ON CONFLICT (user_id) DO UPDATE" in compiled
    assert "last_dispatched_at" in compiled
