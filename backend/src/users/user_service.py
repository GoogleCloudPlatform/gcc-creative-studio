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

import dataclasses
import datetime
import logging

from fastapi import Depends, HTTPException, status

from src.auth.entra_graph_client import EntraGraphError, get_entra_graph_client
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.config.config_service import config_service
from src.users.dto.user_create_dto import UserCreateDto, UserUpdateRoleDto
from src.users.dto.user_search_dto import UserSearchDto
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum

logger = logging.getLogger(__name__)

_ROLE_ORDER = {role: index for index, role in enumerate(UserRoleEnum)}


def _role_values(roles: set[UserRoleEnum]) -> list[str]:
    """Returns the roles as strings, in a fixed order, for storage."""
    return [r.value for r in sorted(roles, key=_ROLE_ORDER.__getitem__)]


def _reject_if_deleted(user: UserModel | None) -> None:
    """Refuses sign-in for a deactivated (soft-deleted) account."""
    if user is not None and user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: this account has been deactivated.",
        )


@dataclasses.dataclass
class _SignIn:
    """What is known about the person signing in.

    The sign-in helpers below fill in more as they learn it.
    """

    email: str
    name: str
    picture: str | None
    entra_oid: str | None
    # True when an existing account found by email should be linked to
    # entra_oid.
    needs_link: bool = False


class UserService:
    """Handles the business logic for user management."""

    def __init__(self, user_repo: UserRepository = Depends()):
        self.user_repo = user_repo

    async def create_user_if_not_exists(
        self,
        email: str,
        name: str,
        picture: str | None,
        entra_oid: str | None = None,
    ) -> UserModel:
        """Returns the signed-in user's account, creating it on first sign-in.

        Users who sign in through Entra are found by their Entra object ID,
        which never changes, rather than by email, which can. An older
        account with the same email but no object ID is linked to the
        object ID once. Emails are compared and stored in lowercase.
        """
        sign_in = _SignIn(
            # The same address in any letter case is the same person.
            email=email.strip().lower(),
            name=name,
            picture=picture,
            entra_oid=(entra_oid or "").strip().lower() or None,
        )
        existing_user = await self._find_or_link_user(sign_in)
        # Deactivated users get a clear 403 instead of a failed attempt to
        # create them again.
        _reject_if_deleted(existing_user)

        if existing_user is None:
            return await self._create_new_user(
                sign_in, datetime.datetime.now(datetime.UTC)
            )
        if sign_in.needs_link:
            return (
                await self.user_repo.update(
                    existing_user.id, {"entra_oid": sign_in.entra_oid}
                )
                or existing_user
            )
        return existing_user

    async def _find_or_link_user(self, sign_in: _SignIn) -> UserModel | None:
        """Finds the account for this sign-in, or None for a new user.

        Looks up by Entra object ID first, then by email. Deactivated
        accounts are included. An account found by email that has no object
        ID yet is marked to be linked to this one, after Microsoft Graph
        confirms the email belongs to it.
        """
        if sign_in.entra_oid is None:
            return await self.user_repo.get_by_email(
                sign_in.email, include_deleted=True
            )

        user = await self.user_repo.get_by_entra_oid(
            sign_in.entra_oid, include_deleted=True
        )
        if user is not None:
            return user

        user = await self.user_repo.get_by_email(
            sign_in.email, include_deleted=True
        )
        if user is None:
            return None
        _reject_if_deleted(user)
        if user.entra_oid is not None and user.entra_oid != sign_in.entra_oid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: email is already linked to a different "
                    "Entra identity."
                ),
            )
        if config_service.ENTRA_ROLE_SYNC_ENABLED:
            await self._confirm_oid_email_via_graph(
                sign_in.entra_oid, sign_in.email
            )
        else:
            logger.info(
                "Linking existing user %s to Entra OID %s "
                "(Entra role sync disabled).",
                user.email,
                sign_in.entra_oid,
            )
        sign_in.needs_link = True
        return user

    async def _create_new_user(
        self, sign_in: _SignIn, now: datetime.datetime
    ) -> UserModel:
        """Creates the account for someone signing in for the first time.

        When role sync is on, their roles come from their Entra groups, and
        `now` is recorded as when the roles were last checked. If Graph
        fails they start with the basic user role only.
        """
        sync_enabled = config_service.ENTRA_ROLE_SYNC_ENABLED
        user_data = UserCreateDto(
            email=sign_in.email,
            name=sign_in.name,
            picture=sign_in.picture or "",
            entra_oid=sign_in.entra_oid,
        ).model_dump(exclude_none=True)
        entra_roles = (
            await self._fetch_entra_roles(
                sign_in.entra_oid or sign_in.email, sign_in.email
            )
            if sync_enabled
            else None
        )
        user_data["roles"] = _role_values(entra_roles or {UserRoleEnum.USER})
        if sync_enabled:
            user_data["roles_checked_at"] = now
        return await self.user_repo.create_or_get_existing(user_data)

    async def _confirm_oid_email_via_graph(
        self, entra_oid: str, email: str
    ) -> None:
        """Checks with Microsoft Graph that `email` belongs to `entra_oid`.

        Raises 403 if Graph lists only other emails for that user, and 503 if
        Graph can't be reached. Does nothing when Graph is not configured.
        """
        client = get_entra_graph_client()
        if client is None:
            return
        try:
            graph_emails = await client.get_user_emails(entra_oid)
        except EntraGraphError as exc:
            logger.error(
                "Failed to confirm Entra OID %s for %s via Graph: %s",
                entra_oid,
                email,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Unable to verify user identity with Microsoft Graph; "
                    "please try again later."
                ),
            ) from exc
        if email.strip().lower() not in graph_emails:
            logger.warning(
                "Refusing to link existing user %s to Entra OID %s: Graph "
                "reported emails %s",
                email,
                entra_oid,
                sorted(graph_emails),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: Entra user profile email does not match "
                    "existing account."
                ),
            )

    async def _fetch_entra_roles(
        self, user_ref: str, log_email: str | None = None
    ) -> set[UserRoleEnum] | None:
        """Returns the roles the user's Entra groups grant, or None on failure.

        `user_ref` is the user's Entra object ID, or their email when the ID
        is not known.
        """
        client = get_entra_graph_client()
        if client is None:
            return None
        group_roles = config_service.ENTRA_GROUP_ROLES
        try:
            matched = await client.member_group_ids(
                user_ref, group_roles.keys()
            )
        except EntraGraphError as exc:
            logger.error(
                "Entra role sync failed for %s; removing privileged roles: %s",
                log_email or user_ref,
                exc,
            )
            return None
        roles = {UserRoleEnum.USER}
        for group_id in matched:
            roles.update(UserRoleEnum(r) for r in group_roles.get(group_id, ()))
        return roles

    async def get_user_by_id(self, user_id: int) -> UserModel | None:
        """Finds a single user by their ID."""
        return await self.user_repo.get_by_id(user_id)

    async def find_all_users(
        self,
        search_dto: UserSearchDto,
    ) -> PaginationResponseDto[UserModel]:
        """Retrieves a paginated list of all users."""
        return await self.user_repo.query(search_dto)

    async def delete_user(
        self, user_id: int, deleted_by: int | None = None
    ) -> bool:
        """Soft deletes a user."""
        return await self.user_repo.soft_delete(user_id, deleted_by=deleted_by)

    async def restore_user(self, user_id: int) -> bool:
        """Restores a soft-deleted user."""
        return await self.user_repo.restore(user_id)

    async def update_user_role(
        self,
        user_id: int,
        role_data: UserUpdateRoleDto,
    ) -> UserModel | None:
        """Updates the role of a specific user with safeties."""
        from fastapi import HTTPException
        from sqlalchemy import func, select

        from src.users.user_model import User

        existing_user = await self.user_repo.get_by_id(user_id)
        if not existing_user:
            return None

        was_admin = "admin" in existing_user.roles
        will_be_admin = "admin" in [role.value for role in role_data.roles]

        if was_admin and not will_be_admin:
            admin_query = (
                select(func.count())
                .select_from(User)
                .where(User.roles.contains(["admin"]))
            )
            admin_count_result = await self.user_repo.db.execute(admin_query)
            admin_count = admin_count_result.scalar() or 0
            if admin_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="There must be at least 1 admin on the app.",
                )

        roles_as_strings = [role.value for role in role_data.roles]
        return await self.user_repo.update(user_id, {"roles": roles_as_strings})
