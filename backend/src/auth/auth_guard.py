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

import jwt
from jwt import PyJWKClient

# --- Google Auth for Identity Platform ---
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService

# Initialize the service once to be used by dependencies.
# user_service = UserService()  <-- REMOVED

import fastapi.security.utils


class CustomOAuth2PasswordBearer(OAuth2PasswordBearer):
    async def __call__(self, request: Request) -> str | None:
        authorization = request.headers.get(
            "X-Custom-Auth"
        ) or request.headers.get("Authorization")
        cookie_token = request.cookies.get("session_token")

        if not authorization and not cookie_token:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                return None

        if authorization:
            scheme, param = (
                fastapi.security.utils.get_authorization_scheme_param(
                    authorization
                )
            )
            if scheme.lower() != "bearer":
                if self.auto_error:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid authentication credentials",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                else:
                    return None
            return param

        return cookie_token


# This scheme will require the client to send a token in the X-Custom-Auth or Authorization
# header. It tells FastAPI how to find the token but doesn't validate it
# itself.
oauth2_scheme = CustomOAuth2PasswordBearer(tokenUrl="token")


logger = logging.getLogger(__name__)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_service: UserService = Depends(UserService),
) -> UserModel:
    """Dependency that handles the entire authentication and user
    provisioning flow.

    1. Verifies the Firebase ID token.
    2. Extracts user information (id, email).
    3. Checks if a user document exists in Firestore.
    4. If the user is new, creates their document ("Just-In-Time Provisioning").
    5. Returns a Pydantic model with the user's data.
    """
    email = None
    try:
        decoded_token = {}
        if config_service.ENTRA_CLIENT_ID:
            # --- Microsoft Entra ID ---
            logger.info("Verifying token using Microsoft Entra ID...")
            jwks_url = f"https://login.microsoftonline.com/{config_service.ENTRA_TENANT_ID}/discovery/v2.0/keys"
            jwks_client = PyJWKClient(jwks_url)
            signing_key = await asyncio.to_thread(
                jwks_client.get_signing_key_from_jwt, token
            )
            decoded_token = await asyncio.to_thread(
                jwt.decode,
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=config_service.ENTRA_CLIENT_ID,
                issuer=[
                    f"https://login.microsoftonline.com/{config_service.ENTRA_TENANT_ID}/v2.0",
                    "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
                ],
            )
            email = decoded_token.get(
                "preferred_username"
            ) or decoded_token.get("email")
            name = decoded_token.get("name")
            picture = ""
            token_info_hd = None
        elif config_service.ENVIRONMENT == "local":
            # --- Local: Use Firebase Auth ---
            # Verifies the token using the standard Firebase Admin SDK method.
            logger.info("Verifying token using Firebase Admin SDK...")
            decoded_token = await asyncio.to_thread(auth.verify_id_token, token)
            email = decoded_token.get("email")
            name = decoded_token.get("name")
            picture = decoded_token.get("picture", "")
            token_info_hd = decoded_token.get("hd")
        else:
            # --- Development/Production: Use Google Identity Platform
            # (OIDC) ---
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

        # If ALLOWED_ORGS is configured, check the user's organization.
        if config_service.ALLOWED_ORGS:
            if (
                not token_info_hd
                or token_info_hd not in config_service.ALLOWED_ORGS
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"User from '{token_info_hd}' is not part of an "
                        "allowed organization."
                    ),
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

    except (auth.ExpiredIdTokenError, jwt.ExpiredSignatureError) as exc:
        logger.error("[get_current_user - ExpiredIdTokenError] for %s", email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        ) from exc
    except (
        auth.InvalidIdTokenError,
        jwt.InvalidTokenError,
        jwt.PyJWKError,
    ) as e:
        logger.error(
            "[get_current_user - InvalidIdTokenError] for %s: %s",
            email,
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
