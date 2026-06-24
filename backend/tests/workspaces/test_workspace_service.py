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
"""Tests for Workspace Service."""


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto
from src.workspaces.dto.invite_user_dto import InviteUserDto
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
)
from src.workspaces.workspace_service import WorkspaceService


@pytest.fixture(name="mock_workspace_repo")
def fixture_mock_workspace_repo():
    return AsyncMock()


@pytest.fixture(name="mock_user_repo")
def fixture_mock_user_repo():
    return AsyncMock()


@pytest.fixture(name="mock_email_service")
def fixture_mock_email_service():
    return MagicMock()  # Synchronous service usually


@pytest.fixture(name="workspace_service")
def fixture_workspace_service(
    mock_workspace_repo, mock_user_repo, mock_email_service
):
    return WorkspaceService(
        workspace_repo=mock_workspace_repo,
        user_repo=mock_user_repo,
        email_service=mock_email_service,
    )


class TestCreateWorkspace:
    """Tests for WorkspaceService.create_workspace."""

    @pytest.mark.anyio
    async def test_create_workspace_success(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user,
    ):
        create_dto = CreateWorkspaceDto(name="New Workspace")

        # Mock repo to return the created workspace
        mock_workspace = WorkspaceModel(
            id=1,
            name="New Workspace",
            owner_id=mock_user.id,
        )
        mock_workspace_repo.create.return_value = mock_workspace

        result = await workspace_service.create_workspace(mock_user, create_dto)

        assert result == mock_workspace
        mock_workspace_repo.create.assert_called_once()

        # Verify initial_members was passed correctly
        called_args = mock_workspace_repo.create.call_args[1]
        initial_members = called_args.get("initial_members")
        assert len(initial_members) == 1
        assert initial_members[0].user_id == mock_user.id
        assert initial_members[0].role == WorkspaceRoleEnum.OWNER


class TestInviteUserToWorkspace:
    """Tests for WorkspaceService.invite_user_to_workspace."""

    @pytest.mark.anyio
    async def test_workspace_not_found(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user,
    ):
        mock_workspace_repo.get_by_id.return_value = None
        invite_dto = InviteUserDto(
            email="guest@example.com",
            role=WorkspaceRoleEnum.VIEWER,
        )

        with pytest.raises(HTTPException) as exc_info:
            await workspace_service.invite_user_to_workspace(
                999, invite_dto, mock_user
            )

        assert exc_info.value.status_code == 404
        assert "Workspace not found" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_forbidden_not_owner_or_admin(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user,
    ):
        # Workspace owned by someone else (ID 99)
        workspace = WorkspaceModel(id=1, name="Test", owner_id=99)
        mock_workspace_repo.get_by_id.return_value = workspace
        invite_dto = InviteUserDto(
            email="guest@example.com",
            role=WorkspaceRoleEnum.VIEWER,
        )

        with pytest.raises(HTTPException) as exc_info:
            await workspace_service.invite_user_to_workspace(
                1, invite_dto, mock_user
            )

        assert exc_info.value.status_code == 403
        assert "Only the workspace owner" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_user_not_found(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user_repo,
        mock_user,
    ):
        # Owner is current user
        workspace = WorkspaceModel(id=1, name="Test", owner_id=mock_user.id)
        mock_workspace_repo.get_by_id.return_value = workspace

        # Mock user repo to return None (user not found by email)
        mock_user_repo.get_by_email.return_value = None
        invite_dto = InviteUserDto(
            email="unknown@example.com",
            role=WorkspaceRoleEnum.VIEWER,
        )

        result = await workspace_service.invite_user_to_workspace(
            1,
            invite_dto,
            mock_user,
        )

        assert result is None
        mock_user_repo.get_by_email.assert_called_once_with(
            "unknown@example.com"
        )

    @pytest.mark.anyio
    async def test_success_invite(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user_repo,
        mock_email_service,
        mock_user,
    ):
        workspace = WorkspaceModel(id=1, name="Test", owner_id=mock_user.id)
        mock_workspace_repo.get_by_id.return_value = workspace

        # Mock invited user
        from src.users.user_model import UserModel

        invited_user = UserModel(
            id=2,
            email="guest@example.com",
            roles=[],
            name="Guest",
        )
        mock_user_repo.get_by_email.return_value = invited_user

        updated_workspace = WorkspaceModel(
            id=1, name="Test", owner_id=mock_user.id
        )
        mock_workspace_repo.add_member_to_workspace.return_value = (
            updated_workspace
        )

        invite_dto = InviteUserDto(
            email="guest@example.com",
            role=WorkspaceRoleEnum.VIEWER,
        )

        result = await workspace_service.invite_user_to_workspace(
            1,
            invite_dto,
            mock_user,
        )

        assert result == updated_workspace
        mock_workspace_repo.add_member_to_workspace.assert_called_once()
        mock_email_service.send_workspace_invitation_email.assert_called_once()


class TestListWorkspacesForUser:
    """Tests for WorkspaceService.list_workspaces_for_user."""

    @pytest.mark.anyio
    async def test_list_workspaces_combine_lists(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user,
    ):
        w1 = WorkspaceModel(id=1, name="Private 1", owner_id=mock_user.id)
        w2 = WorkspaceModel(
            id=2,
            name="Public 1",
            owner_id=99,
        )  # Public, owned by someone else

        mock_workspace_repo.find_by_member_id.return_value = [w1]
        mock_workspace_repo.get_all_public_workspaces.return_value = [w2]

        result = await workspace_service.list_workspaces_for_user(mock_user)

        assert len(result) == 2
        ids = [w.id for w in result]
        assert 1 in ids
        assert 2 in ids

    @pytest.mark.anyio
    async def test_list_workspaces_auto_create_default(
        self,
        workspace_service,
        mock_workspace_repo,
        mock_user,
    ):
        mock_workspace_repo.find_by_member_id.return_value = []
        mock_workspace_repo.get_all_public_workspaces.return_value = []
        new_w = WorkspaceModel(
            id=10, name="My Workspace", owner_id=mock_user.id
        )
        mock_workspace_repo.create.return_value = new_w

        result = await workspace_service.list_workspaces_for_user(mock_user)

        assert len(result) == 1
        assert result[0].id == 10
        assert result[0].name == "My Workspace"
        mock_workspace_repo.create.assert_called_once()
