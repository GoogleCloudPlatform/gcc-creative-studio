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

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from firebase_admin import auth

# --- Google Auth for Identity Platform ---
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService
from src.common.token_logger import current_user_email
from src.workspaces.workspace_service import WorkspaceService
from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto

# Initialize the service once to be used by dependencies.
# user_service = UserService()  <-- REMOVED

# This scheme will require the client to send a token in the Authorization
# header. It tells FastAPI how to find the token but doesn't validate it
# itself.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


logger = logging.getLogger(__name__)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_service: UserService = Depends(UserService),
    workspace_service: WorkspaceService = Depends(WorkspaceService),
) -> UserModel:
    """Dependency that handles the entire authentication and user
    provisioning flow.

    1. Verifies the Firebase ID token.
    2. Extracts user information (id, email).
    3. Checks if a user document exists in Firestore.
    4. If the user is new, creates their document ("Just-In-Time Provisioning").
    5. Returns a Pydantic model with the user's data.
    """
    try:
        decoded_token = {}
        # Try Firebase Admin SDK first (frontend uses signInWithPopup ->
        # Firebase ID tokens). Fall back to Google OIDC for Identity
        # Platform tokens.
        try:
            logger.info("Verifying token using Firebase Admin SDK...")
            decoded_token = await asyncio.to_thread(
                auth.verify_id_token, token
            )
        except Exception as fb_err:  # noqa: BLE001
            logger.info(
                "Firebase verify failed (%s); trying Google OIDC...", fb_err
            )
            google_token_audience = config_service.GOOGLE_TOKEN_AUDIENCE
            decoded_token = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                token,
                google_auth_requests.Request(),
                audience=google_token_audience,
            )

        email = decoded_token.get("email")
        try:
            current_user_email.set(email or "unknown")
        except Exception:
            pass
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
        # Firebase tokens lack 'hd', so derive domain from email.
        effective_hd = token_info_hd
        if not effective_hd and email:
            effective_hd = email.split("@")[-1].lower()
        if config_service.ALLOWED_ORGS:
            if (
                not effective_hd
                or effective_hd not in config_service.ALLOWED_ORGS
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

        # Auto-provision a default workspace on first login so every
        # colleague can start immediately (no "select a workspace" error).
        try:
            existing_ws = await workspace_service.list_workspaces_for_user(
                user_doc
            )
            if not existing_ws:
                ws_name = f"{(user_doc.name or 'My').strip()} Workspace"
                if len(ws_name) < 3:
                    ws_name = "My Workspace"
                await workspace_service.create_workspace(
                    user_doc,
                    CreateWorkspaceDto(name=ws_name),
                )
                logger.info(
                    "Auto-created default workspace for user: %s", email
                )
        except Exception as ws_exc:  # noqa: BLE001
            logger.warning(
                "Could not auto-create workspace for %s: %s", email, ws_exc
            )

        return user_doc

    except auth.ExpiredIdTokenError as exc:
        logger.error(
            "[get_current_user - auth.ExpiredIdTokenError] for %s", email
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        ) from exc
    except auth.InvalidIdTokenError as e:
        logger.error(
            "[get_current_user - auth.InvalidIdTokenError] for %s: %s",
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
