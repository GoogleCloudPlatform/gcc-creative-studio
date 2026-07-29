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

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from firebase_admin import auth

# --- Google Auth for Identity Platform ---
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService
from src.common.request_context import is_agent_request

# Initialize the scheme without auto_error so we can handle fallback internal auth
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


logger = logging.getLogger(__name__)


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
            import requests

            try:
                response = await asyncio.to_thread(
                    requests.get,
                    f"https://oauth2.googleapis.com/tokeninfo?access_token={token}",
                    timeout=10,
                )
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Invalid Google access token: {response.text}",
                    )
                decoded_token = response.json()
            except requests.RequestException as req_err:
                logger.error(
                    "Failed to verify Google access token: %s", req_err
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to contact Google authentication server.",
                )

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
        elif config_service.ENVIRONMENT == "local":
            try:
                logger.info("Verifying token using Firebase Admin SDK...")
                decoded_token = await asyncio.to_thread(
                    auth.verify_id_token, token
                )
            except Exception as firebase_err:
                logger.info(
                    "Firebase verification failed, falling back to Google OIDC: %s",
                    firebase_err,
                )
                try:
                    google_token_audience = config_service.GOOGLE_TOKEN_AUDIENCE
                    decoded_token = await asyncio.to_thread(
                        id_token.verify_oauth2_token,
                        token,
                        google_auth_requests.Request(),
                        audience=google_token_audience,
                    )
                except Exception as oidc_err:
                    raise firebase_err from oidc_err
        else:
            # --- Development/Production: Use Google Identity Platform (OIDC) ---
            # Verifies the Google-issued OIDC ID token. The audience must be the
            # OAuth 2.0 client ID of the Identity Platform-protected resource.
            google_token_audience = config_service.GOOGLE_TOKEN_AUDIENCE
            decoded_token = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                token,
                google_auth_requests.Request(),
                audience=google_token_audience,
            )

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

        return user_doc

    except auth.ExpiredIdTokenError as exc:
        logger.error(
            "[get_current_user - auth.ExpiredIdTokenError] for %s",
            email or "Unknown email",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        ) from exc
    except auth.InvalidIdTokenError as e:
        logger.error(
            "[get_current_user - auth.InvalidIdTokenError] for %s: %s",
            email or "Unknown email",
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {e}",
        ) from e
    except HTTPException as e:
        logger.error("[get_current_user - Exception]: %s", e)
        raise e
    except Exception as e:
        logger.error("[get_current_user - Exception]: %s", e)
        raise HTTPException(
            status_code=getattr(
                e,
                "status_code",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            detail=f"An unexpected error occurred during authentication: {e}",
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
