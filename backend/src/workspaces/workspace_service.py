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
"""Business logic for workspace lifecycle, personal workspaces, and invites."""

from fastapi import Depends, HTTPException, status

from src.common.email_service import EmailService
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto
from src.workspaces.dto.invite_user_dto import InviteUserDto
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    WorkspaceMember,
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import (
    is_workspace_manager,
    resolve_effective_role,
)


class WorkspaceService:
    """Handles the business logic for workspace management."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository = Depends(),
        user_repo: UserRepository = Depends(),
        email_service: EmailService = Depends(),
    ):
        self.workspace_repo = workspace_repo
        self.user_repo = user_repo
        self.email_service = email_service

    async def create_workspace(
        self,
        user: UserModel,
        create_dto: CreateWorkspaceDto,
    ) -> WorkspaceModel:
        """Creates a new private workspace with the creator as the owner."""
        owner_as_member = WorkspaceMember(
            user_id=user.id,
            email=user.email,
            role=WorkspaceRoleEnum.OWNER,
        )
        new_workspace = WorkspaceModel(
            name=create_dto.name,
            owner_id=user.id,
        )
        created = await self.workspace_repo.create(
            new_workspace,
            initial_members=[owner_as_member],
        )
        created.current_user_role = WorkspaceRoleEnum.OWNER
        return created

    async def ensure_personal_workspace(
        self,
        user: UserModel,
        commit_on_create: bool = True,
    ) -> WorkspaceModel:
        """Returns the user's personal workspace, creating it JIT if missing."""
        return await self.workspace_repo.ensure_personal_workspace(
            user, commit_on_create=commit_on_create
        )

    async def invite_user_to_workspace(
        self,
        workspace_id: int,
        invite_dto: InviteUserDto,
        current_user: UserModel,
    ) -> WorkspaceModel | None:
        """Invites a user to a private workspace.

        Restricted to the workspace owner, a private workspace admin, or a
        system admin.
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )

        if workspace.scope == WorkspaceScopeEnum.PERSONAL:
            if current_user.id != workspace.owner_id:
                raise HTTPException(
                    403,
                    detail="Only the personal workspace owner can manage this workspace.",
                )
            raise HTTPException(
                400, detail="Cannot invite users to your personal workspace."
            )
        if workspace.scope == WorkspaceScopeEnum.PUBLIC:
            raise HTTPException(
                400, detail="Cannot invite users to a public workspace."
            )
        if invite_dto.role == WorkspaceRoleEnum.OWNER:
            raise HTTPException(
                400, detail="Cannot assign the owner role through invitations."
            )

        is_sys_admin = UserRoleEnum.ADMIN in (current_user.roles or [])
        needs_role = (
            not is_sys_admin
            and current_user.id != workspace.owner_id
            and workspace.current_user_role is None
        )
        fetched_role = (
            await self.workspace_repo.get_member_role(
                workspace_id, current_user.id
            )
            if needs_role
            else None
        )
        workspace.current_user_role = resolve_effective_role(
            workspace, current_user, fetched_role=fetched_role
        )
        if not is_workspace_manager(current_user, workspace):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the workspace owner, a workspace admin, or a system admin can invite users.",
            )

        invited_user = await self.user_repo.get_by_email(invite_dto.email)
        if not invited_user:
            return None

        new_member = WorkspaceMember(
            user_id=invited_user.id,
            email=invited_user.email,
            role=invite_dto.role,
        )
        updated_workspace = await self.workspace_repo.add_member_to_workspace(
            workspace_id,
            new_member,
            invited_user.id,
        )
        if updated_workspace:
            updated_workspace.current_user_role = workspace.current_user_role
            self.email_service.send_workspace_invitation_email(
                recipient_email=invited_user.email,
                inviter_name=current_user.name,
                workspace_name=updated_workspace.name,
                workspace_id=workspace_id,
            )
        return updated_workspace

    async def list_workspaces_for_user(
        self, user: UserModel
    ) -> list[WorkspaceModel]:
        """Retrieves all workspaces a user can access, ordered
        ``[personal, ...private, ...public]`` with ``current_user_role`` set.
        """
        personal_ws = await self.ensure_personal_workspace(user)
        member_workspaces = await self.workspace_repo.find_by_member_id(user.id)
        public_workspaces = (
            await self.workspace_repo.get_all_public_workspaces()
        )

        all_ws: dict[int, WorkspaceModel] = {}
        if personal_ws.id is not None:
            all_ws[personal_ws.id] = personal_ws
        for w in member_workspaces:
            if (
                w.id is not None
                and w.id not in all_ws
                and (
                    w.scope != WorkspaceScopeEnum.PERSONAL
                    or w.owner_id == user.id
                )
            ):
                all_ws[w.id] = w
        for w in public_workspaces:
            if w.id is not None:
                all_ws[w.id] = w

        is_sys_admin = UserRoleEnum.ADMIN in (user.roles or [])
        for ws in all_ws.values():
            role = None
            if (
                ws.scope == WorkspaceScopeEnum.PRIVATE
                and ws.owner_id != user.id
                and not is_sys_admin
                and ws.current_user_role is None
                and ws.id is not None
            ):
                role = await self.workspace_repo.get_member_role(ws.id, user.id)
            ws.current_user_role = resolve_effective_role(
                ws, user, fetched_role=role
            )

        return sorted(
            all_ws.values(),
            key=lambda w: (
                0
                if w.scope == WorkspaceScopeEnum.PERSONAL
                else 1 if w.scope == WorkspaceScopeEnum.PRIVATE else 2
            ),
        )
