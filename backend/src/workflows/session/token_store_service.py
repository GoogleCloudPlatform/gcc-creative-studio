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

"""Encrypted short-lived ID token store for deferred workflow dispatch.

Stores the user's Google ID token (encrypted at rest with Fernet / MultiFernet)
in ``workflow_user_sessions`` so queued and retrying workflow runs can dispatch
while the token still has at least ``DEFAULT_MIN_TTL_SECONDS`` (120s) of
validity remaining.

Security invariants:
* Only 3-segment JWT ID tokens are accepted. OAuth access tokens (``ya29.*``)
  and agent ``X-User-Authorization`` tokens are rejected.
* If ``WORKFLOW_TOKEN_ENCRYPTION_KEY`` is missing, empty, set to the Terraform
  placeholder ``placeholder_value_waiting_for_bootstrap_sh``, or invalid, token
  storage is disabled with a warning and ``get_valid_token`` returns ``None``
  without crashing startup or requests.
* If decryption raises ``InvalidToken`` (e.g. after key rotation), the stored
  ciphertext is treated as absent (``None``) so the run parks in
  ``WAITING_FOR_SESSION`` until the user's next authenticated request.
* Raw tokens, ciphertexts, and encryption keys are never logged.
"""

import base64
import binascii
import datetime
import json
import logging
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.secret_redaction import install_secret_redaction
from src.config.config_service import config_service
from src.database import get_db
from src.workflows.schema.workflow_run_model import (
    WorkflowUserSession,
    WorkflowUserSessionModel,
)

logger = install_secret_redaction(logging.getLogger(__name__))

PLACEHOLDER_SECRET_VALUE = "placeholder_value_waiting_for_bootstrap_sh"
DEFAULT_MIN_TTL_SECONDS = 120
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _strip_bearer(token: str) -> str:
    cleaned = (token or "").strip()
    if cleaned.lower().startswith("bearer "):
        return cleaned[7:].strip()
    return cleaned


def is_jwt_id_token(token: str | None) -> bool:
    """True when ``token`` looks like a 3-segment JWT ID token (not ``ya29.``)."""
    if not token or not isinstance(token, str):
        return False
    cleaned = _strip_bearer(token)
    if not cleaned or cleaned.startswith("ya29."):
        return False
    parts = cleaned.split(".")
    return len(parts) == 3 and all(bool(part) for part in parts)


def extract_jwt_expiration(token: str | None) -> datetime.datetime | None:
    """Extracts the ``exp`` claim (UTC datetime) from a 3-segment JWT payload."""
    if not is_jwt_id_token(token):
        return None
    cleaned = _strip_bearer(token or "")
    payload_segment = cleaned.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_segment + padding)
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    exp_val = payload.get("exp")
    if isinstance(exp_val, bool) or not isinstance(exp_val, (int, float)):
        return None
    try:
        return datetime.datetime.fromtimestamp(float(exp_val), tz=datetime.UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _coerce_expiration(
    exp: datetime.datetime | int | float | None,
    token: str,
) -> datetime.datetime | None:
    if isinstance(exp, datetime.datetime):
        if exp.tzinfo is None:
            return exp.replace(tzinfo=datetime.UTC)
        return exp.astimezone(datetime.UTC)
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        try:
            return datetime.datetime.fromtimestamp(float(exp), tz=datetime.UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return extract_jwt_expiration(token)


def build_fernet(raw_key: str | None) -> MultiFernet | None:
    """Parses one or more comma-separated Fernet keys into a ``MultiFernet``.

    Returns ``None`` (and logs a warning without the key value) when the key is
    missing, equal to ``placeholder_value_waiting_for_bootstrap_sh``, or invalid.
    """
    cleaned = (raw_key or "").strip()
    if not cleaned or cleaned == PLACEHOLDER_SECRET_VALUE:
        logger.warning(
            "WORKFLOW_TOKEN_ENCRYPTION_KEY is missing or set to placeholder; "
            "workflow session token storage is disabled."
        )
        return None

    key_parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    if not key_parts or any(
        part == PLACEHOLDER_SECRET_VALUE for part in key_parts
    ):
        logger.warning(
            "WORKFLOW_TOKEN_ENCRYPTION_KEY contains a placeholder entry; "
            "workflow session token storage is disabled."
        )
        return None

    fernets: list[Fernet] = []
    for index, part in enumerate(key_parts):
        try:
            fernets.append(Fernet(part.encode("ascii")))
        except (ValueError, TypeError):
            logger.warning(
                "WORKFLOW_TOKEN_ENCRYPTION_KEY contains an invalid Fernet key "
                "at position %d; workflow session token storage is disabled.",
                index,
            )
            return None
    return MultiFernet(fernets)


class WorkflowUserSessionRepository:
    """Data access helper for ``workflow_user_sessions``."""

    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self.db = db

    async def get_by_user_id(
        self, user_id: int
    ) -> WorkflowUserSessionModel | None:
        """Reads the ``workflow_user_sessions`` row for ``user_id``."""
        result = await self.db.execute(
            select(WorkflowUserSession)
            .where(WorkflowUserSession.user_id == user_id)
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return WorkflowUserSessionModel.model_validate(row)

    async def upsert_if_fresher(
        self,
        *,
        user_id: int,
        encrypted_token: str,
        token_expires_at: datetime.datetime,
        now: datetime.datetime,
    ) -> None:
        """Upserts the encrypted token when ``token_expires_at`` is fresher.

        Preserves ``last_dispatched_at`` on conflict. Does not commit.
        """
        insert_stmt = pg_insert(WorkflowUserSession).values(
            user_id=user_id,
            encrypted_token=encrypted_token,
            token_expires_at=token_expires_at,
            updated_at=now,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[WorkflowUserSession.user_id],
            set_={
                "encrypted_token": insert_stmt.excluded.encrypted_token,
                "token_expires_at": insert_stmt.excluded.token_expires_at,
                "updated_at": insert_stmt.excluded.updated_at,
            },
            where=or_(
                WorkflowUserSession.token_expires_at
                < insert_stmt.excluded.token_expires_at,
                WorkflowUserSession.encrypted_token.is_(None),
            ),
        )
        await self.db.execute(upsert_stmt)

    async def touch_last_dispatched_at(
        self,
        user_id: int,
        now: datetime.datetime,
    ) -> None:
        """Updates ``last_dispatched_at`` for round-robin fairness.

        Creates a skeleton row with ``encrypted_token = NULL`` if none exists.
        Does not commit.
        """
        insert_stmt = pg_insert(WorkflowUserSession).values(
            user_id=user_id,
            encrypted_token=None,
            token_expires_at=_EPOCH,
            updated_at=now,
            last_dispatched_at=now,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[WorkflowUserSession.user_id],
            set_={
                "last_dispatched_at": insert_stmt.excluded.last_dispatched_at,
                "updated_at": insert_stmt.excluded.updated_at,
            },
        )
        await self.db.execute(upsert_stmt)


class TokenStoreService:
    """Encrypts, stores, and retrieves short-lived user ID tokens."""

    def __init__(
        self,
        repository: WorkflowUserSessionRepository = Depends(),
        *,
        encryption_key: str | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        min_ttl_seconds: int = DEFAULT_MIN_TTL_SECONDS,
    ) -> None:
        self._repository = repository
        self._clock = clock or _utcnow
        self._min_ttl_seconds = max(0, int(min_ttl_seconds))
        raw_key = (
            config_service.WORKFLOW_TOKEN_ENCRYPTION_KEY
            if encryption_key is None
            else encryption_key
        )
        self._fernet = build_fernet(raw_key)

    @property
    def is_enabled(self) -> bool:
        """True when a valid Fernet key is configured."""
        return self._fernet is not None

    def encrypt_token(self, token: str) -> str | None:
        """Encrypts a raw JWT ID token string, or ``None`` if disabled."""
        if self._fernet is None or not is_jwt_id_token(token):
            return None
        cleaned = _strip_bearer(token)
        return self._fernet.encrypt(cleaned.encode("utf-8")).decode("ascii")

    def decrypt_token(self, encrypted_token: str | None) -> str | None:
        """Decrypts a stored token, returning ``None`` on ``InvalidToken``."""
        if self._fernet is None or not encrypted_token:
            return None
        try:
            plaintext = self._fernet.decrypt(
                encrypted_token.encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError):
            logger.warning(
                "Could not decrypt stored workflow user session token; "
                "treating session as expired."
            )
            return None
        return plaintext if is_jwt_id_token(plaintext) else None

    async def store_token(
        self,
        user_id: int,
        token: str,
        *,
        exp: datetime.datetime | int | float | None = None,
        commit: bool = False,
    ) -> bool:
        """Encrypts and upserts ``token`` if it is a valid, non-expired JWT.

        Returns ``True`` when the token was accepted and written to the session,
        or ``False`` when token storage is disabled or the token is not a valid
        non-expired JWT ID token.
        """
        if self._fernet is None or not is_jwt_id_token(token):
            return False
        cleaned = _strip_bearer(token)
        expires_at = _coerce_expiration(exp, cleaned)
        now = self._clock()
        if expires_at is None or expires_at <= now:
            return False

        ciphertext = self.encrypt_token(cleaned)
        if ciphertext is None:
            return False

        await self._repository.upsert_if_fresher(
            user_id=user_id,
            encrypted_token=ciphertext,
            token_expires_at=expires_at,
            now=now,
        )
        if commit:
            await self._repository.db.commit()
        return True

    async def get_valid_token(
        self,
        user_id: int,
        *,
        min_ttl_seconds: int | None = None,
    ) -> str | None:
        """Returns the decrypted ID token if it has > ``min_ttl_seconds`` left.

        Returns ``None`` if encryption is disabled, no row exists, the token
        expires within ``min_ttl_seconds`` (default 120s), or decryption fails.
        """
        if self._fernet is None:
            return None
        session_row = await self._repository.get_by_user_id(user_id)
        if session_row is None or not session_row.encrypted_token:
            return None
        ttl = (
            self._min_ttl_seconds
            if min_ttl_seconds is None
            else max(0, int(min_ttl_seconds))
        )
        now = self._clock()
        expires_at = session_row.token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.UTC)
        if expires_at <= now + datetime.timedelta(seconds=ttl):
            return None
        return self.decrypt_token(session_row.encrypted_token)

    async def touch_last_dispatched_at(
        self,
        user_id: int,
        *,
        now: datetime.datetime | None = None,
    ) -> None:
        """Records ``last_dispatched_at`` for ``user_id`` (does not commit)."""
        await self._repository.touch_last_dispatched_at(
            user_id, now or self._clock()
        )


def get_token_store_service(
    repository: WorkflowUserSessionRepository = Depends(),
) -> TokenStoreService:
    """FastAPI dependency provider for :class:`TokenStoreService`."""
    return TokenStoreService(repository=repository)
