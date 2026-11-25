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
"""Workspace access checks and effective-role / manager policy helpers."""

from collections.abc import Iterable

from fastapi import Depends, HTTPException
from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
    coerce_workspace_role,
)

_WRITER_ROLES = frozenset(
    {WorkspaceRoleEnum.OWNER, WorkspaceRoleEnum.ADMIN, WorkspaceRoleEnum.EDITOR}
)
_MANAGER_ROLES = frozenset({WorkspaceRoleEnum.OWNER, WorkspaceRoleEnum.ADMIN})


def resolve_effective_role(
    workspace: WorkspaceModel, user: UserModel, *, fetched_role: object = None
) -> WorkspaceRoleEnum:
    """Single source of truth for a caller's effective role in a workspace."""
    is_admin = UserRoleEnum.ADMIN in (user.roles or [])
    if workspace.scope == WorkspaceScopeEnum.PERSONAL:
        return (
            WorkspaceRoleEnum.OWNER
            if workspace.owner_id == user.id
            else WorkspaceRoleEnum.VIEWER
        )
    if workspace.scope == WorkspaceScopeEnum.PUBLIC:
        return WorkspaceRoleEnum.ADMIN if is_admin else WorkspaceRoleEnum.EDITOR
    if workspace.owner_id == user.id:
        return WorkspaceRoleEnum.OWNER
    if is_admin:
        return WorkspaceRoleEnum.ADMIN
    role = coerce_workspace_role(fetched_role) or coerce_workspace_role(
        workspace.current_user_role
    )
    return role or WorkspaceRoleEnum.VIEWER


def is_workspace_manager(user: UserModel, workspace: WorkspaceModel) -> bool:
    """True for PERSONAL owner, global ADMIN on shared, or PRIVATE OWNER/ADMIN."""
    if workspace.scope == WorkspaceScopeEnum.PERSONAL:
        return workspace.owner_id == user.id
    if UserRoleEnum.ADMIN in (user.roles or []):
        return True
    if workspace.scope == WorkspaceScopeEnum.PRIVATE:
        return (
            workspace.owner_id == user.id
            or coerce_workspace_role(workspace.current_user_role)
            in _MANAGER_ROLES
        )
    return False


def accessible_shared_workspace_clause(user: UserModel) -> ColumnElement[bool]:
    """SQL predicate matching non-PERSONAL workspaces ``user`` may read."""
    base_clause: ColumnElement[bool] = (
        Workspace.scope != WorkspaceScopeEnum.PERSONAL.value
    )
    if UserRoleEnum.ADMIN in (user.roles or []):
        return base_clause
    member_exists = exists(
        select(1).where(
            WorkspaceMemberAssociation.workspace_id == Workspace.id,
            WorkspaceMemberAssociation.user_id == user.id,
        )
    )
    return and_(
        base_clause,
        or_(
            Workspace.scope == WorkspaceScopeEnum.PUBLIC.value,
            Workspace.owner_id == user.id,
            member_exists,
        ),
    )


async def get_accessible_shared_workspace_ids(
    db: AsyncSession,
    workspace_ids: Iterable[int],
    user: UserModel,
) -> set[int]:
    """Filters ``workspace_ids`` to non-PERSONAL workspaces ``user`` may read."""
    candidate_ids = sorted(
        {
            wid
            for wid in workspace_ids
            if isinstance(wid, int) and not isinstance(wid, bool) and wid > 0
        }
    )
    if not candidate_ids:
        return set()
    stmt = select(Workspace.id).where(
        Workspace.id.in_(candidate_ids),
        accessible_shared_workspace_clause(user),
    )
    return set((await db.execute(stmt)).scalars().all())


class WorkspaceAuth:
    """Centralizes fail-closed workspace read and write authorization."""

    def __init__(self, workspace_repo: WorkspaceRepository = Depends()):
        self.workspace_repo = workspace_repo

    async def authorize(
        self, workspace_id: int, user: UserModel
    ) -> WorkspaceModel:
        """Checks read access to a workspace and sets ``current_user_role``."""
        scope = await self.workspace_repo.get_scope(workspace_id)
        if scope is None:
            raise HTTPException(
                404, detail=f"Workspace with ID '{workspace_id}' not found."
            )

        scope_val = (
            scope.value if isinstance(scope, WorkspaceScopeEnum) else str(scope)
        )
        is_admin = UserRoleEnum.ADMIN in (user.roles or [])

        if (
            scope_val == WorkspaceScopeEnum.PRIVATE.value
            and not is_admin
            and not await self.workspace_repo.is_member(workspace_id, user.id)
        ):
            raise HTTPException(
                403,
                detail="You do not have permission to access this workspace.",
            )

        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace:
            raise HTTPException(
                404, detail=f"Workspace with ID '{workspace_id}' not found."
            )

        if (
            scope_val == WorkspaceScopeEnum.PERSONAL.value
            and workspace.owner_id != user.id
        ):
            raise HTTPException(
                403,
                detail="You do not have permission to access this workspace.",
            )

        fetched_role = (
            await self.workspace_repo.get_member_role(workspace_id, user.id)
            if workspace.scope == WorkspaceScopeEnum.PRIVATE
            and workspace.owner_id != user.id
            and not is_admin
            else None
        )
        workspace.current_user_role = resolve_effective_role(
            workspace, user, fetched_role=fetched_role
        )
        return workspace

    async def authorize_write(
        self, workspace_id: int, user: UserModel
    ) -> WorkspaceModel:
        """Checks write/publish access, rejecting PRIVATE VIEWERs with 403."""
        workspace = await self.authorize(workspace_id, user)
        if workspace.scope == WorkspaceScopeEnum.PRIVATE:
            role = (
                coerce_workspace_role(workspace.current_user_role)
                or WorkspaceRoleEnum.VIEWER
            )
            if role not in _WRITER_ROLES:
                raise HTTPException(
                    403,
                    detail="Viewer role has read-only access to this workspace.",
                )
        return workspace
