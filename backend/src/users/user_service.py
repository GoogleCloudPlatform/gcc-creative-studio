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
from typing import Any

from fastapi import Depends, HTTPException, status

from src.auth.entra_graph_client import (
    EntraGraphError,
    EntraUserNotFoundError,
    get_entra_graph_client,
)
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


def _roles_check_due(user: UserModel, now: datetime.datetime) -> bool:
    """Returns True if the user's roles were never checked or are stale."""
    return user.roles_checked_at is None or (
        now - user.roles_checked_at
    ) >= datetime.timedelta(seconds=config_service.ENTRA_ROLE_SYNC_TTL_SECONDS)


def _is_deployer_admin(email: str) -> bool:
    """Returns True if `email` is the deployer's break-glass admin email."""
    admin_email = config_service.ADMIN_USER_EMAIL.strip().lower()
    if not admin_email or admin_email == "system":
        return False
    return email.strip().lower() == admin_email


def _check_allowed_org(email: str) -> None:
    """Refuses an email outside IDENTITY_PLATFORM_ALLOWED_ORGS, if it is set.

    Used when the email came from the database or Graph rather than the
    sign-in token, so the sign-in guard could not check it up front.
    """
    allowed_orgs = config_service.ALLOWED_ORGS
    if not allowed_orgs:
        return
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if not domain or domain not in allowed_orgs:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"User from '{domain}' is not part of an allowed organization."
            ),
        )


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
    # True when the token had no email and it was looked up in Graph.
    email_from_graph: bool = False
    # Every email Graph lists for the user, when it was looked up.
    graph_emails: set[str] = dataclasses.field(default_factory=set)


class UserService:
    """Handles the business logic for user management."""

    def __init__(self, user_repo: UserRepository = Depends()):
        self.user_repo = user_repo

    async def create_user_if_not_exists(
        self,
        email: str | None,
        name: str,
        picture: str | None,
        entra_oid: str | None = None,
    ) -> UserModel:
        """Returns the signed-in user's account, creating it on first sign-in.

        Users who sign in through Entra are found by their Entra object ID,
        which never changes, rather than by email, which can. An older
        account with the same email but no object ID is linked to the
        object ID once. Emails are compared and stored in lowercase.

        A Workforce token may carry no email. The email (and the display
        name, when `name` is empty) is then looked up in Microsoft Graph by
        object ID.
        """
        sign_in = _SignIn(
            # The same address in any letter case is the same person.
            email=(email or "").strip().lower(),
            name=name,
            picture=picture,
            entra_oid=(entra_oid or "").strip().lower() or None,
        )
        existing_user = await self._find_or_link_user(sign_in)
        # Deactivated users get a clear 403 instead of a failed attempt to
        # create them again.
        _reject_if_deleted(existing_user)

        now = datetime.datetime.now(datetime.UTC)
        if existing_user is None:
            return await self._create_new_user(sign_in, now)
        return await self._recheck_roles(existing_user, sign_in, now)

    async def _find_or_link_user(self, sign_in: _SignIn) -> UserModel | None:
        """Finds the account for this sign-in, or None for a new user.

        Looks up by Entra object ID first, then by email. Deactivated
        accounts are included. An account found by email that has no object
        ID yet is marked to be linked to this one, after Microsoft Graph
        confirms the email belongs to it.
        """
        if sign_in.entra_oid is None:
            if not sign_in.email:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        "Unauthorized: User email could not be confirmed from "
                        "IAP token."
                    ),
                )
            return await self.user_repo.get_by_email(
                sign_in.email, include_deleted=True
            )

        user = await self.user_repo.get_by_entra_oid(
            sign_in.entra_oid, include_deleted=True
        )
        if user is not None:
            if not sign_in.email:
                # The token had no email, so its organization is checked here.
                _check_allowed_org(user.email)
            return user

        if not sign_in.email:
            (
                sign_in.email,
                graph_display_name,
                sign_in.graph_emails,
            ) = await self._resolve_oid_profile_via_graph(sign_in.entra_oid)
            sign_in.email_from_graph = True
            if not sign_in.name and graph_display_name:
                sign_in.name = graph_display_name
            _check_allowed_org(sign_in.email)

        # An older account may be under any of the user's emails.
        candidate_emails = [sign_in.email] + sorted(
            sign_in.graph_emails - {sign_in.email}
        )
        user = None
        for candidate in candidate_emails:
            user = await self.user_repo.get_by_email(
                candidate, include_deleted=True
            )
            if user is not None:
                break
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
        sync_enabled = config_service.ENTRA_ROLE_SYNC_ENABLED
        if sync_enabled and not sign_in.email_from_graph:
            await self._confirm_oid_email_via_graph(
                sign_in.entra_oid, sign_in.email
            )
        elif not sync_enabled:
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
            name=sign_in.name or sign_in.email.split("@")[0],
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
        roles = entra_roles or {UserRoleEnum.USER}
        if sync_enabled and (
            _is_deployer_admin(sign_in.email)
            or any(_is_deployer_admin(e) for e in sign_in.graph_emails)
        ):
            if sign_in.entra_oid is not None and not sign_in.email_from_graph:
                # The deployer email came from the sign-in token. Confirm with
                # Graph that this object ID really owns it before giving a new
                # account break-glass admin.
                try:
                    await self._confirm_oid_email_via_graph(
                        sign_in.entra_oid, sign_in.email
                    )
                    roles = self._apply_deployer_admin_safeguard(
                        sign_in.email, roles
                    )
                except HTTPException as exc:
                    # Sign-in still goes ahead: IAP has already verified this
                    # person, and only the extra admin grant is withheld. They
                    # get the roles their Entra groups grant, like anyone else.
                    logger.warning(
                        "Not granting deployer admin to new user %s: could "
                        "not confirm Entra OID %s owns that email: %s",
                        sign_in.email,
                        sign_in.entra_oid,
                        exc.detail,
                    )
            else:
                roles = roles | {UserRoleEnum.ADMIN}
        user_data["roles"] = _role_values(roles)
        if sync_enabled:
            user_data["roles_checked_at"] = now
        return await self.user_repo.create_or_get_existing(user_data)

    async def _recheck_roles(
        self, user: UserModel, sign_in: _SignIn, now: datetime.datetime
    ) -> UserModel:
        """Returns the existing user, rechecking their roles when due.

        With role sync on, roles are rechecked against Entra groups at most
        once per ENTRA_ROLE_SYNC_TTL_SECONDS. If Graph fails, privileged roles
        are removed, except that the deployer keeps admin. The check time is
        saved either way, so Graph is retried after one TTL rather than on
        every request. A pending object ID link is saved here too.
        """
        link = {"entra_oid": sign_in.entra_oid} if sign_in.needs_link else {}
        if not config_service.ENTRA_ROLE_SYNC_ENABLED or not _roles_check_due(
            user, now
        ):
            if link:
                return await self.user_repo.update(user.id, link) or user
            return user

        updates: dict[str, Any] = {"roles_checked_at": now, **link}
        lookup_ref = sign_in.entra_oid or user.entra_oid or user.email
        entra_roles = await self._fetch_entra_roles(lookup_ref, user.email)
        target = self._apply_deployer_admin_safeguard(
            user.email,
            entra_roles if entra_roles is not None else {UserRoleEnum.USER},
        )
        current = {UserRoleEnum(r) for r in user.roles}
        if target != current:
            updates["roles"] = _role_values(target)
            logger.info(
                "Entra role sync for %s: %s -> %s",
                user.email,
                _role_values(current),
                updates["roles"],
            )
        return await self.user_repo.update(user.id, updates) or user

    async def _resolve_oid_profile_via_graph(
        self, entra_oid: str
    ) -> tuple[str, str | None, set[str]]:
        """Returns the user's email, display name and all emails from Graph.

        Used when the sign-in token has no email. Refuses sign-in with 401 if
        Graph is not configured, 403 if Graph does not know the user or has
        no email for them, and 503 if Graph can't be reached.
        """
        client = get_entra_graph_client()
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Unauthorized: User email could not be confirmed from "
                    "IAP token."
                ),
            )
        try:
            primary_email, display_name, all_emails = (
                await client.get_user_profile(entra_oid)
            )
        except EntraUserNotFoundError as exc:
            logger.warning(
                "Entra OID %s not found in Microsoft Graph: %s", entra_oid, exc
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: Entra user was not found in Microsoft Graph."
                ),
            ) from exc
        except EntraGraphError as exc:
            logger.error(
                "Failed to resolve email for Entra OID %s via Graph: %s",
                entra_oid,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Unable to verify user identity with Microsoft Graph; "
                    "please try again later."
                ),
            ) from exc
        if not primary_email:
            logger.warning(
                "Entra OID %s has no mail or userPrincipalName in Graph.",
                entra_oid,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: Entra user profile does not have a valid "
                    "email or userPrincipalName."
                ),
            )
        return primary_email, display_name, all_emails

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

    def _apply_deployer_admin_safeguard(
        self, user_email: str, target: set[UserRoleEnum]
    ) -> set[UserRoleEnum]:
        """Returns `target`, with admin added back if the user is the deployer.

        The deployer (ADMIN_USER_EMAIL) is the break-glass admin, so Entra
        groups can never remove their admin role.
        """
        if UserRoleEnum.ADMIN not in target and _is_deployer_admin(user_email):
            logger.warning(
                "Entra sync would remove admin from deployer %s; "
                "keeping the admin role (break-glass exemption).",
                user_email,
            )
            return target | {UserRoleEnum.ADMIN}
        return target

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
