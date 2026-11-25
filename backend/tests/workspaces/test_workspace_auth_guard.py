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
"""Tests for Workspace Auth Guard."""


from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import (
    WorkspaceAuth,
    is_workspace_manager,
    resolve_effective_role,
)


@pytest.fixture(name="mock_workspace_repo_auth")
def fixture_mock_workspace_repo_auth():
    return AsyncMock()


@pytest.fixture(name="workspace_auth")
def fixture_workspace_auth(mock_workspace_repo_auth):
    return WorkspaceAuth(workspace_repo=mock_workspace_repo_auth)


class TestWorkspaceAuthAuthorize:
    """Tests for WorkspaceAuth.authorize."""

    @pytest.mark.anyio
    async def test_authorize_not_found(
        self,
        workspace_auth,
        mock_workspace_repo_auth,
        mock_user,
    ):
        mock_workspace_repo_auth.get_scope.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await workspace_auth.authorize(999, mock_user)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_authorize_admin_access(
        self,
        workspace_auth,
        mock_workspace_repo_auth,
        mock_admin,
    ):
        # Private workspace, but user is ADMIN
        mock_workspace_repo_auth.get_scope.return_value = (
            WorkspaceScopeEnum.PRIVATE
        )

        mock_workspace = WorkspaceModel(id=1, name="Private", owner_id=99)
        mock_workspace_repo_auth.get_by_id.return_value = mock_workspace

        result = await workspace_auth.authorize(1, mock_admin)

        assert result == mock_workspace
        mock_workspace_repo_auth.is_member.assert_not_called()

    @pytest.mark.anyio
    async def test_authorize_public_workspace(
        self,
        workspace_auth,
        mock_workspace_repo_auth,
        mock_user,
    ):
        # Public workspace, user is regular user
        mock_workspace_repo_auth.get_scope.return_value = (
            WorkspaceScopeEnum.PUBLIC
        )

        mock_workspace = WorkspaceModel(id=1, name="Public", owner_id=99)
        mock_workspace_repo_auth.get_by_id.return_value = mock_workspace

        result = await workspace_auth.authorize(1, mock_user)

        assert result == mock_workspace
        mock_workspace_repo_auth.is_member.assert_not_called()

    @pytest.mark.anyio
    async def test_authorize_private_member(
        self,
        workspace_auth,
        mock_workspace_repo_auth,
        mock_user,
    ):
        # Private workspace, user is regular user, but IS a member
        mock_workspace_repo_auth.get_scope.return_value = (
            WorkspaceScopeEnum.PRIVATE
        )
        mock_workspace_repo_auth.is_member.return_value = True

        mock_workspace = WorkspaceModel(id=1, name="Private", owner_id=99)
        mock_workspace_repo_auth.get_by_id.return_value = mock_workspace

        result = await workspace_auth.authorize(1, mock_user)

        assert result == mock_workspace
        mock_workspace_repo_auth.is_member.assert_called_once_with(
            1, mock_user.id
        )

    @pytest.mark.anyio
    async def test_authorize_private_not_member(
        self,
        workspace_auth,
        mock_workspace_repo_auth,
        mock_user,
    ):
        # Private workspace, user is regular user, NOT a member
        mock_workspace_repo_auth.get_scope.return_value = (
            WorkspaceScopeEnum.PRIVATE
        )
        mock_workspace_repo_auth.is_member.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await workspace_auth.authorize(1, mock_user)

        assert exc_info.value.status_code == 403
        assert "do not have permission" in exc_info.value.detail
        mock_workspace_repo_auth.is_member.assert_called_once_with(
            1, mock_user.id
        )

    @pytest.mark.anyio
    async def test_authorize_personal_rejects_foreign_users_and_global_admin(
        self, workspace_auth, mock_workspace_repo_auth, mock_user, mock_admin
    ):
        mock_workspace_repo_auth.get_scope.return_value = (
            WorkspaceScopeEnum.PERSONAL
        )
        personal = WorkspaceModel(
            id=11,
            name="My Workspace",
            owner_id=mock_user.id,
            scope=WorkspaceScopeEnum.PERSONAL,
        )
        mock_workspace_repo_auth.get_by_id.return_value = personal

        owner_ws = await workspace_auth.authorize(11, mock_user)
        assert owner_ws.current_user_role == WorkspaceRoleEnum.OWNER

        other = UserModel(
            id=55,
            email="other@test.com",
            name="Other",
            roles=[UserRoleEnum.USER],
        )
        for caller in (other, mock_admin):
            with pytest.raises(HTTPException) as exc:
                await workspace_auth.authorize(11, caller)
            assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_authorize_write_blocks_private_viewer_and_allows_editor(
        self, workspace_auth, mock_workspace_repo_auth, mock_user
    ):
        mock_workspace_repo_auth.get_scope.return_value = (
            WorkspaceScopeEnum.PRIVATE
        )
        mock_workspace_repo_auth.is_member.return_value = True
        mock_workspace_repo_auth.get_by_id.return_value = WorkspaceModel(
            id=5, name="Shared", owner_id=99, scope=WorkspaceScopeEnum.PRIVATE
        )

        mock_workspace_repo_auth.get_member_role.return_value = (
            WorkspaceRoleEnum.VIEWER
        )
        with pytest.raises(HTTPException) as exc:
            await workspace_auth.authorize_write(5, mock_user)
        assert exc.value.status_code == 403

        mock_workspace_repo_auth.get_member_role.return_value = (
            WorkspaceRoleEnum.EDITOR
        )
        allowed = await workspace_auth.authorize_write(5, mock_user)
        assert allowed.current_user_role == WorkspaceRoleEnum.EDITOR


def test_is_workspace_manager_and_resolve_effective_role(mock_user, mock_admin):
    personal = WorkspaceModel(
        id=1, name="P", owner_id=mock_user.id, scope=WorkspaceScopeEnum.PERSONAL
    )
    public_ws = WorkspaceModel(
        id=2, name="Pub", owner_id=99, scope=WorkspaceScopeEnum.PUBLIC
    )
    private_admin = WorkspaceModel(
        id=3,
        name="Priv",
        owner_id=99,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.ADMIN,
    )
    private_editor = WorkspaceModel(
        id=4,
        name="Priv2",
        owner_id=99,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )

    assert is_workspace_manager(mock_user, personal) is True
    assert is_workspace_manager(mock_admin, personal) is False
    assert is_workspace_manager(mock_user, public_ws) is False
    assert is_workspace_manager(mock_admin, public_ws) is True
    assert is_workspace_manager(mock_user, private_admin) is True
    assert is_workspace_manager(mock_user, private_editor) is False

    assert (
        resolve_effective_role(personal, mock_user) == WorkspaceRoleEnum.OWNER
    )
    assert (
        resolve_effective_role(personal, mock_admin) == WorkspaceRoleEnum.VIEWER
    )
    assert (
        resolve_effective_role(public_ws, mock_user) == WorkspaceRoleEnum.EDITOR
    )
    assert (
        resolve_effective_role(public_ws, mock_admin) == WorkspaceRoleEnum.ADMIN
    )
    assert (
        resolve_effective_role(
            WorkspaceModel(
                id=5, name="Priv", owner_id=99, scope=WorkspaceScopeEnum.PRIVATE
            ),
            mock_user,
            fetched_role="admin",
        )
        == WorkspaceRoleEnum.ADMIN
    )
