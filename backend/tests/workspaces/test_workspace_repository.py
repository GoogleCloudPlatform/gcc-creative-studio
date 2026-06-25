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
"""Tests for Workspace Repository."""


from unittest.mock import MagicMock

import pytest

from src.workspaces.repository.workspace_repository import WorkspaceRepository


@pytest.fixture(name="workspace_repo")
def fixture_workspace_repo(db_session_mock):
    """Provides a WorkspaceRepository with mocked AsyncSession."""
    return WorkspaceRepository(db=db_session_mock)


class TestWorkspaceRepository:
    """Tests for WorkspaceRepository methods with mocked DB response."""

    @pytest.mark.anyio
    async def test_get_scope_found(self, workspace_repo, db_session_mock):
        # Mock result.scalar_one_or_none()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "private"
        db_session_mock.execute.return_value = mock_result

        result = await workspace_repo.get_scope(1)

        assert result == "private"
        db_session_mock.execute.assert_called_once()

    @pytest.mark.anyio
    async def test_get_scope_not_found(self, workspace_repo, db_session_mock):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db_session_mock.execute.return_value = mock_result

        result = await workspace_repo.get_scope(999)

        assert result is None

    @pytest.mark.anyio
    async def test_is_member_true(self, workspace_repo, db_session_mock):
        # Mock result.scalar()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        db_session_mock.execute.return_value = mock_result

        result = await workspace_repo.is_member(1, 10)

        assert result is True

    @pytest.mark.anyio
    async def test_is_member_false(self, workspace_repo, db_session_mock):
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        db_session_mock.execute.return_value = mock_result

        result = await workspace_repo.is_member(1, 10)

        assert result is False

    @pytest.mark.anyio
    async def test_get_public_workspace_success(
        self, workspace_repo, db_session_mock
    ):
        import datetime

        from src.workspaces.schema.workspace_model import Workspace

        now = datetime.datetime.now(datetime.UTC)
        mock_result = MagicMock()
        mock_asset = Workspace(
            id=1,
            name="Public",
            owner_id=1,
            scope="public",
            created_at=now,
            updated_at=now,
        )
        mock_result.scalar_one_or_none.return_value = mock_asset
        db_session_mock.execute.return_value = mock_result

        response = await workspace_repo.get_public_workspace()
        assert response.id == 1
        assert response.name == "Public"

    @pytest.mark.anyio
    async def test_get_all_public_workspaces_success(
        self,
        workspace_repo,
        db_session_mock,
    ):
        import datetime

        from src.workspaces.schema.workspace_model import Workspace

        now = datetime.datetime.now(datetime.UTC)
        mock_result = MagicMock()
        mock_asset = Workspace(
            id=2,
            name="Public 2",
            owner_id=1,
            scope="public",
            created_at=now,
            updated_at=now,
        )
        mock_result.scalars().all.return_value = [mock_asset]
        db_session_mock.execute.return_value = mock_result

        response = await workspace_repo.get_all_public_workspaces()
        assert len(response) == 1
        assert response[0].id == 2

    @pytest.mark.anyio
    async def test_find_by_member_id_success(
        self, workspace_repo, db_session_mock
    ):
        import datetime

        from src.workspaces.schema.workspace_model import Workspace

        now = datetime.datetime.now(datetime.UTC)
        mock_result = MagicMock()
        mock_asset = Workspace(
            id=3,
            name="Member workspace",
            owner_id=1,
            scope="private",
            created_at=now,
            updated_at=now,
        )
        mock_result.scalars().all.return_value = [mock_asset]
        db_session_mock.execute.return_value = mock_result

        response = await workspace_repo.find_by_member_id(user_id=10)
        assert len(response) == 1
        assert response[0].id == 3

    @pytest.mark.anyio
    async def test_create_with_members_success(
        self, workspace_repo, db_session_mock
    ):
        import datetime

        from src.workspaces.schema.workspace_model import (
            WorkspaceMember,
            WorkspaceModel,
        )

        now = datetime.datetime.now(datetime.UTC)
        mock_schema = WorkspaceModel(
            id=10,
            name="New Space",
            owner_id=1,
            scope="private",
            created_at=now,
            updated_at=now,
        )
        initial_members = [
            WorkspaceMember(user_id=2, role="editor", email="test@editor.com"),
        ]

        response = await workspace_repo.create(
            schema=mock_schema,
            initial_members=initial_members,
        )
        assert response is not None

    @pytest.mark.anyio
    async def test_add_member_to_workspace_success(
        self,
        workspace_repo,
        db_session_mock,
    ):
        import datetime

        from src.workspaces.schema.workspace_model import (
            Workspace,
            WorkspaceMember,
        )

        now = datetime.datetime.now(datetime.UTC)
        mock_result = MagicMock()
        mock_asset = Workspace(
            id=20,
            name="Space",
            owner_id=1,
            scope="private",
            created_at=now,
            updated_at=now,
        )
        mock_asset.members = []
        mock_result.scalar_one_or_none.return_value = mock_asset
        db_session_mock.execute.return_value = mock_result

        member_to_add = WorkspaceMember(
            user_id=5,
            role="viewer",
            email="test@viewer.com",
        )
        response = await workspace_repo.add_member_to_workspace(
            workspace_id=20,
            member=member_to_add,
            user_id=5,
        )

        assert response is not None
        assert len(mock_asset.members) == 1
        db_session_mock.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_add_member_to_workspace_already_member(
        self,
        workspace_repo,
        db_session_mock,
    ):
        import datetime

        from src.workspaces.schema.workspace_model import (
            Workspace,
            WorkspaceMember,
            WorkspaceMemberAssociation,
        )

        now = datetime.datetime.now(datetime.UTC)
        mock_result = MagicMock()
        mock_asset = Workspace(
            id=20,
            name="Space",
            owner_id=1,
            scope="private",
            created_at=now,
            updated_at=now,
        )
        existing_association = WorkspaceMemberAssociation(
            workspace_id=20,
            user_id=5,
            role="owner",
        )
        mock_asset.members = [existing_association]
        mock_result.scalar_one_or_none.return_value = mock_asset
        db_session_mock.execute.return_value = mock_result

        member_to_add = WorkspaceMember(
            user_id=5,
            role="viewer",
            email="test@viewer.com",
        )
        response = await workspace_repo.add_member_to_workspace(
            workspace_id=20,
            member=member_to_add,
            user_id=5,
        )

        assert response is not None
        assert len(mock_asset.members) == 1
        assert mock_asset.members[0].role == "owner"
        db_session_mock.commit.assert_not_called()
