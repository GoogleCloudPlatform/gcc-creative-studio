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
import logging
import re
from typing import Any

from fastapi import Depends, HTTPException, status, Request, Header
from firebase_admin import auth


# --- Google Auth for Identity Platform ---
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService

# Initialize the service once to be used by dependencies.
# user_service = UserService()  <-- REMOVED

import fastapi.security.utils

logger = logging.getLogger(__name__)

# The "iss" value IAP puts in every token it signs.
_IAP_ISSUER = "https://cloud.google.com/iap"

# Header a workflow run uses to name the user who started it.
_ACTING_USER_HEADER = "x-acting-user-id"

_WORKFORCE_SUB_PREFIX = (
    "principal://iam.googleapis.com/locations/global/workforcePools/"
)
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _extract_workforce_oid(decoded_token: dict[str, Any]) -> str | None:
    """Returns the user's Entra object ID from a Workforce sign-in token.

    IAP puts the Workforce principal
    (`principal://.../workforcePools/<pool>/subject/<oid>`) in the
    `workforce_identity.iam_principal` claim, while `sub` holds an opaque
    Google ID. Older or synthetic tokens may carry the principal in `sub`
    instead, so that is used as a fallback.

    Returns the lowercased object ID, or None for a token that is not from
    a Workforce pool when WORKFORCE_POOL_ID is not set. Raises 401 if a
    Workforce token names a different pool or its subject is not a GUID.
    """
    sub = decoded_token.get("sub")
    identity_source = decoded_token.get("identity_source")
    workforce_identity = decoded_token.get("workforce_identity")
    iam_principal = (
        workforce_identity.get("iam_principal")
        if isinstance(workforce_identity, dict)
        else None
    )
    principal = iam_principal if isinstance(iam_principal, str) else sub
    configured_pool = config_service.WORKFORCE_POOL_ID.strip()
    is_workforce = (
        bool(configured_pool)
        or isinstance(workforce_identity, dict)
        or (isinstance(sub, str) and sub.startswith("principal://"))
        or identity_source
        in (
            "WORKFORCE_IDENTITY",
            "WORKFORCE_POOL",
            "WORKFORCE_IDENTITY_FEDERATION",
        )
    )
    if not is_workforce:
        return None

    if not isinstance(principal, str) or not principal.startswith(
        _WORKFORCE_SUB_PREFIX
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid IAP authentication token: missing or malformed "
                "workforce principal subject."
            ),
        )
    rest = principal[len(_WORKFORCE_SUB_PREFIX) :]
    if "/subject/" not in rest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid IAP authentication token: missing subject segment "
                "in workforce principal."
            ),
        )
    pool_id, oid_part = rest.split("/subject/", 1)
    if not pool_id or "/" in pool_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid IAP authentication token: invalid workforce pool "
                "identifier."
            ),
        )
    if configured_pool and pool_id != configured_pool:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid IAP authentication token: workforce pool does not "
                "match configured pool."
            ),
        )
    if not _GUID_RE.match(oid_part):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid IAP authentication token: workforce subject is not "
                "a valid Entra OID."
            ),
        )
    return oid_part.lower()


def _is_workflow_service_call(request: Request) -> bool:
    """Returns True if the request looks like a workflow run calling us.

    These calls come straight to Cloud Run (not through IAP), so they carry a
    bearer token and the ID of the user who started the run instead of an IAP
    header. The path is off unless the direct URL is configured.
    """
    if not config_service.BACKEND_INTERNAL_URL:
        return False
    authorization = request.headers.get("authorization") or ""
    return authorization.startswith("Bearer ") and (
        _ACTING_USER_HEADER in request.headers
    )


async def _get_workflow_acting_user(
    request: Request, user_service: UserService
) -> UserModel:
    """Returns the user a workflow run acts for, after checking the caller.

    Only a token that Google signed for this backend's own service account,
    issued for our direct URL, is accepted. The user ID comes from the backend
    itself, which set it when an IAP-verified user started the run. This never
    creates users.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: invalid workflow service credentials.",
    )
    expected_email = config_service.BACKEND_SERVICE_ACCOUNT_EMAIL.lower()
    if not expected_email:
        raise unauthorized

    token = request.headers["authorization"].removeprefix("Bearer ")
    try:
        claims = await asyncio.to_thread(
            id_token.verify_oauth2_token,
            token,
            google_auth_requests.Request(),
            audience=config_service.BACKEND_INTERNAL_URL,
        )
    except ValueError as exc:
        logger.error("[workflow service call - invalid token]: %s", exc)
        raise unauthorized from exc

    if (
        str(claims.get("email", "")).lower() != expected_email
        or claims.get("email_verified") is not True
    ):
        logger.error(
            "[workflow service call - wrong caller]: %s", claims.get("email")
        )
        raise unauthorized

    acting_user_id = request.headers.get(_ACTING_USER_HEADER, "")
    if not acting_user_id.isdigit():
        raise unauthorized
    user = await user_service.user_repo.get_by_id(int(acting_user_id))
    if user is None or user.deleted_at is not None:
        raise unauthorized
    return user


async def get_iap_jwt(
    request: Request, x_goog_iap_jwt_assertion: str | None = Header(None)
) -> str | None:
    """Extracts the IAP JWT assertion. In local environment, this is optional.

    Returns None for a workflow run calling the backend directly; those calls
    are checked separately in get_current_user.
    """
    if config_service.ENVIRONMENT == "local":
        return x_goog_iap_jwt_assertion or "mock_local_token"
    if not x_goog_iap_jwt_assertion:
        if _is_workflow_service_call(request):
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing X-Goog-Iap-Jwt-Assertion header.",
        )
    return x_goog_iap_jwt_assertion


async def get_current_user(
    request: Request,
    token: str | None = Depends(get_iap_jwt),
    user_service: UserService = Depends(UserService),
) -> UserModel:
    """Dependency that handles the entire authentication and user
    provisioning flow via Identity-Aware Proxy (IAP).

    1. Checks if running locally to bypass verification.
    2. Verifies the Google-signed IAP JWT token.
    3. Extracts user information (entra_oid, email, name, picture).
    4. If the user is new, creates their profile JIT.
    5. Returns a Pydantic model with the user's data.
    """
    try:
        if token is None:
            # A workflow run calling the backend directly, not through IAP.
            return await _get_workflow_acting_user(request, user_service)

        if config_service.ENVIRONMENT == "local":
            # Local Dev Bypass: Use mock user
            mock_email = request.headers.get(
                "X-Mock-User-Email", "local-dev@example.com"
            )
            mock_name = request.headers.get(
                "X-Mock-User-Name", "Local Dev User"
            )
            user_doc = await user_service.create_user_if_not_exists(
                email=mock_email,
                name=mock_name,
                picture="",
            )
            return user_doc

        # Verify Google-signed IAP JWT assertion
        try:
            decoded_token = await asyncio.to_thread(
                id_token.verify_token,
                token,
                google_auth_requests.Request(),
                audience=config_service.IAP_EXPECTED_AUDIENCE,
                certs_url="https://www.gstatic.com/iap/verify/public_key",
            )
            # Only accept tokens that IAP itself issued, as Google's IAP
            # guide recommends. The signature check already rules out
            # forgery; this is a second lock against misconfiguration.
            if decoded_token.get("iss") != _IAP_ISSUER:
                raise ValueError(
                    f"Wrong issuer {decoded_token.get('iss')!r}; "
                    f"expected {_IAP_ISSUER!r}"
                )
        except ValueError as exc:
            logger.error("[get_current_user - Invalid IAP Token]: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid IAP authentication token: {exc}",
            ) from exc

        logger.info("Decoded IAP Token Claims: %s", list(decoded_token.keys()))
        logger.info(
            "Decoded Token values - email: %s, sub: %s, hd: %s",
            decoded_token.get("email"),
            decoded_token.get("sub"),
            decoded_token.get("hd"),
        )

        entra_oid = _extract_workforce_oid(decoded_token)

        email = decoded_token.get("email")
        # With Workforce Identity Federation the email may be in
        # preferred_username or upn instead. Never fall back to `sub`: it is
        # an opaque identifier, not an email.
        if not email:
            email = decoded_token.get("preferred_username")
        if not email:
            email = decoded_token.get("upn")

        has_token_email = isinstance(email, str) and "@" in email
        if not has_token_email:
            if entra_oid is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        "Unauthorized: User email could not be confirmed from "
                        "IAP token."
                    ),
                )
            # A Workforce user: UserService looks the email up in Microsoft
            # Graph by object ID.
            email = None

        name = decoded_token.get("name") or (
            email.split("@")[0] if email else ""
        )
        picture = decoded_token.get("picture", "")

        token_info_hd = decoded_token.get("hd")
        if not token_info_hd and email:
            token_info_hd = email.split("@")[-1]

        # If ALLOWED_ORGS is configured and the token shows a domain, check
        # the user's organization (case-insensitive) before any DB or Graph
        # calls. Without a domain, it is checked once the email is known.
        if config_service.ALLOWED_ORGS and token_info_hd:
            if token_info_hd.lower() not in config_service.ALLOWED_ORGS:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"User from '{token_info_hd}' is not part of an "
                        "allowed organization."
                    ),
                )

        # Just-In-Time (JIT) User Provisioning:
        # Create a user profile in our database on their first API call.
        # When the token has no email, UserService resolves it from Microsoft
        # Graph using entra_oid.
        create_kwargs: dict[str, Any] = {
            "email": email,
            "name": name,
            "picture": picture,
        }
        if entra_oid is not None:
            create_kwargs["entra_oid"] = entra_oid
        user_doc = await user_service.create_user_if_not_exists(**create_kwargs)

        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not create or retrieve user profile.",
            )

        # Defense in depth: UserService already checks the organization of
        # an email it resolved itself, but check the stored email here too
        # when the token had no domain.
        if config_service.ALLOWED_ORGS and not token_info_hd:
            resolved_hd = (
                user_doc.email.split("@")[-1]
                if user_doc.email and "@" in user_doc.email
                else ""
            )
            if (
                not resolved_hd
                or resolved_hd.lower() not in config_service.ALLOWED_ORGS
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"User from '{resolved_hd}' is not part of an "
                        "allowed organization."
                    ),
                )

        if not user_doc.picture and picture:
            logger.info(
                "Updating picture for user: %s", user_doc.email or email
            )
            user_doc.picture = picture
            if user_doc.id:
                await user_service.user_repo.update(
                    user_doc.id, {"picture": picture}
                )

        return user_doc

    except HTTPException as e:
        logger.error("[get_current_user - HTTPException]: %s", e)
        raise e
    except Exception as e:
        logger.error("[get_current_user - Unexpected Exception]: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during authentication: {e}",
        ) from e


async def require_workflow_service_caller(
    request: Request,
    user_service: UserService = Depends(UserService),
) -> UserModel:
    """Returns the user a workflow run acts for; refuses everyone else.

    Used by the workflow executor endpoints, which only a workflow run may
    call; signed-in users get 403. Local development keeps the mock user.
    """
    if config_service.ENVIRONMENT == "local":
        token = await get_iap_jwt(
            request, request.headers.get("x-goog-iap-jwt-assertion")
        )
        return await get_current_user(request, token, user_service)
    if not _is_workflow_service_call(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workflow runs may call this endpoint.",
        )
    return await _get_workflow_acting_user(request, user_service)


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
