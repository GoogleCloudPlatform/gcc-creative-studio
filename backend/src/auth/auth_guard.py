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
"""Authentication guards and user retrieval."""


import asyncio
from collections.abc import Awaitable, Callable
import inspect
import logging
import re
from typing import Any, NoReturn

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError

# --- Google Auth for Identity Platform ---
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token
import requests

from src.common.request_context import is_agent_request
from src.common.secret_redaction import install_secret_redaction
from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService

# Initialize the scheme without auto_error so we can handle fallback internal auth
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


logger = install_secret_redaction(logging.getLogger(__name__))

PostAuthHook = Callable[[UserModel, str, Any], Awaitable[Any] | Any]
_post_auth_hooks: list[PostAuthHook] = []


def register_post_auth_hook(hook: PostAuthHook) -> None:
    """Registers a callback invoked with ``(user, token, exp)`` after ID token auth.

    Hooks are only called for direct user JWT ID tokens (never for ``ya29.*``
    OAuth access tokens or ``X-User-Authorization`` agent requests, Q14).
    """
    if hook not in _post_auth_hooks:
        _post_auth_hooks.append(hook)


def clear_post_auth_hooks() -> None:
    """Removes all registered post-auth hooks (used by tests)."""
    _post_auth_hooks.clear()


def get_post_auth_hooks() -> tuple[PostAuthHook, ...]:
    """Returns a snapshot of the registered post-auth hooks."""
    return tuple(_post_auth_hooks)


async def _run_post_auth_hooks(user: UserModel, token: str, exp: Any) -> None:
    """Invokes registered post-auth hooks without failing authentication."""
    for hook in tuple(_post_auth_hooks):
        try:
            result = hook(user, token, exp)
            if inspect.isawaitable(result):
                await result
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Post-auth hook %s failed for user_id=%s",
                getattr(hook, "__name__", repr(hook)),
                user.id,
                exc_info=True,
            )


_TOKEN_VERIFICATION_ERRORS = (
    ValueError,
    google_auth_exceptions.GoogleAuthError,
    FirebaseError,
)


_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_B64_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9_=-])"
    r"(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[a-z0-9_-])"
    r"[A-Za-z0-9_-]{24,}={0,2}(?![A-Za-z0-9_=-])"
)
_CANT_PARSE_SEG_RE = re.compile(
    r"(Can't parse segment:\s*)b(['\"])(?:\\.|.)*?\2"
)
_AUTH_UNAVAILABLE_DETAIL = "Failed to contact Google authentication server."


def _raise_auth_service_unavailable(cause: Exception | None = None) -> NoReturn:
    """Raises HTTP 503 for upstream Google auth cert or transport outages."""
    exc = HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_AUTH_UNAVAILABLE_DETAIL,
    )
    if cause is not None:
        raise exc from cause
    raise exc


def _sanitize_auth_error(err: Exception, token: str) -> str:
    """Redacts JWT/base64 token segments while keeping diagnostic reasons."""
    msg = str(err)
    cause = err.cause if isinstance(err, FirebaseError) else err.__cause__
    if cause is not None:
        cause_str = str(cause)
        if cause_str and cause_str not in msg:
            msg = f"{msg}: {cause_str}" if msg else cause_str
    if token:
        msg = msg.replace(token, "[REDACTED]")
        if "." in token:
            for seg in token.split("."):
                if len(seg) >= 3:
                    msg = msg.replace(f"b'{seg}'", "[REDACTED]")
                    msg = msg.replace(f'b"{seg}"', "[REDACTED]")
                if len(seg) >= 6:
                    msg = msg.replace(seg, "[REDACTED]")
    msg = _CANT_PARSE_SEG_RE.sub(r"\1[REDACTED]", msg)
    msg = _JWT_RE.sub("[REDACTED]", msg)
    return _B64_RUN_RE.sub("[REDACTED]", msg)


def _raise_token_verification_error(err: Exception, token: str) -> NoReturn:
    """Maps Firebase/OIDC verification failures to 503 (transport) or 401."""
    sanitized = _sanitize_auth_error(err, token)
    if isinstance(
        err,
        (google_auth_exceptions.TransportError, auth.CertificateFetchError),
    ):
        logger.warning(
            "Identity token verification transport error: %s",
            sanitized,
        )
        _raise_auth_service_unavailable(err)

    # google-auth raises InvalidValue (subclass of both ValueError and
    # GoogleAuthError) with "Token expired, ..." rather than a dedicated
    # ExpiredError class; Firebase raises ExpiredIdTokenError.
    is_expired = isinstance(err, auth.ExpiredIdTokenError) or (
        isinstance(err, ValueError) and "expired" in str(err).lower()
    )
    detail = (
        "Authentication token has expired."
        if is_expired
        else "Invalid authentication token."
    )
    logger.warning("Identity token verification failed: %s", sanitized)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
    ) from err


async def _verify_oidc_token(token: str) -> dict[str, Any]:
    """Verifies a Google Identity Platform OIDC ID token.

    The audience must match the OAuth 2.0 client ID of the Identity
    Platform-protected resource.
    """
    return await asyncio.to_thread(
        id_token.verify_oauth2_token,
        token,
        google_auth_requests.Request(),
        audience=config_service.GOOGLE_TOKEN_AUDIENCE,
    )


async def _verify_identity_token(token: str) -> dict[str, Any]:
    """Verifies an ID token using Firebase (local fallback) or Google OIDC."""
    if config_service.ENVIRONMENT == "local":
        try:
            logger.info("Verifying token using Firebase Admin SDK...")
            return await asyncio.to_thread(auth.verify_id_token, token)
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.info(
                "Firebase verification failed, falling back to Google OIDC: %s",
                _sanitize_auth_error(err, token),
            )
            try:
                return await _verify_oidc_token(token)
            except _TOKEN_VERIFICATION_ERRORS as oidc_err:
                # Local mode tries Firebase first; keep Firebase expiry or
                # cert-fetch failures instead of masking them behind OIDC.
                err_to_classify = (
                    err
                    if isinstance(
                        err,
                        (auth.ExpiredIdTokenError, auth.CertificateFetchError),
                    )
                    else oidc_err
                )
                _raise_token_verification_error(err_to_classify, token)
    try:
        return await _verify_oidc_token(token)
    except _TOKEN_VERIFICATION_ERRORS as oidc_err:
        _raise_token_verification_error(oidc_err, token)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    user_service: UserService = Depends(UserService),
) -> UserModel:
    """Dependency that handles the entire authentication and user
    provisioning flow. Supports standard token or internal agent key auth.
    """
    try:
        is_agent_request.set(False)
        user_auth_header = request.headers.get("X-User-Authorization")
        if user_auth_header:
            is_agent_request.set(True)
            token = (
                user_auth_header.replace("Bearer ", "")
                .replace("bearer ", "")
                .strip()
            )

        # 2. Fall back to Token verification
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token.",
            )

        decoded_token = {}
        if token.startswith("ya29."):
            # --- Verify Google OAuth Access Token (Agent Engine) ---
            logger.info("Verifying Google OAuth Access Token...")

            try:
                response = await asyncio.to_thread(
                    requests.get,
                    f"https://oauth2.googleapis.com/tokeninfo?access_token={token}",
                    timeout=10,
                )
                if response.status_code != 200:
                    if (
                        response.status_code >= 500
                        or response.status_code == 429
                    ):
                        logger.warning(
                            "Google tokeninfo endpoint unavailable (status=%s)",
                            response.status_code,
                        )
                        _raise_auth_service_unavailable()
                    logger.warning(
                        "Invalid Google access token (status=%s)",
                        response.status_code,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid Google access token.",
                    )
                decoded_token = response.json()
            except requests.RequestException as req_err:
                logger.warning(
                    "Failed to verify Google access token: %s",
                    _sanitize_auth_error(req_err, token),
                )
                _raise_auth_service_unavailable(req_err)

            if not decoded_token or "email" not in decoded_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Google access token.",
                )

            if "name" not in decoded_token and "email" in decoded_token:
                email_prefix = decoded_token["email"].split("@")[0]
                decoded_token["name"] = (
                    email_prefix if len(email_prefix) >= 2 else "User"
                )
        else:
            decoded_token = await _verify_identity_token(token)

        email = decoded_token.get("email")
        name = decoded_token.get("name")
        picture = decoded_token.get("picture", "")
        token_info_hd = decoded_token.get("hd")

        # Restrict by particular organizations if it's a closed environment
        if not email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: User identity could not be confirmed from "
                    "token."
                ),
            )

        # Check if user is allowed by email or organization
        is_allowed = False

        if config_service.ALLOWED_EMAILS:
            if email in config_service.ALLOWED_EMAILS:
                is_allowed = True

        if not is_allowed and config_service.ALLOWED_ORGS:
            if token_info_hd and token_info_hd in config_service.ALLOWED_ORGS:
                is_allowed = True

        # If at least one restriction is configured and user is not allowed, reject.
        if (
            config_service.ALLOWED_EMAILS or config_service.ALLOWED_ORGS
        ) and not is_allowed:
            logger.warning(
                "Unauthorized access attempt rejected for email=%s hd=%s",
                email,
                token_info_hd,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is not authorized to access this application.",
            )

        # Just-In-Time (JIT) User Provisioning:
        # Create a user profile in our database on their first API call.
        user_doc = await user_service.create_user_if_not_exists(
            email=email,
            name=name,
            picture=picture,
        )

        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not create or retrieve user profile.",
            )

        if not user_doc.picture and picture:
            logger.info("Updating picture for user: %s", email)
            user_doc.picture = picture
            if user_doc.id:
                await user_service.user_repo.update(
                    user_doc.id, {"picture": picture}
                )

        if not user_auth_header and not token.startswith("ya29."):
            await _run_post_auth_hooks(
                user_doc, token, decoded_token.get("exp")
            )

        return user_doc

    except HTTPException as e:
        if e.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("[get_current_user - Exception]: %s", e)
        raise e
    except Exception as e:
        logger.error(
            "[get_current_user - Exception]: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=getattr(
                e,
                "status_code",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            detail="An unexpected error occurred during authentication.",
        ) from e


class RoleChecker:
    """Dependency that checks if the authenticated user has the required roles.
    It depends on `get_current_user` to ensure the user is authenticated first.
    """

    def __init__(self, allowed_roles: list[UserRoleEnum]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: UserModel = Depends(get_current_user)):
        """Checks the user's roles against the allowed roles."""
        is_authorized = any(role in self.allowed_roles for role in user.roles)

        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You do not have sufficient permissions to perform this "
                    "action."
                ),
            )
