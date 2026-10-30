# Copyright 2026 Google LLC
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

"""ProjectAuth: projects are owner-only and need workspace access."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.projects.dto.project_dto import ProjectResponse
from src.projects.project_auth_guard import ProjectAuth
from src.users.user_model import UserModel, UserRoleEnum


def _user(user_id=1, roles=None):
    return UserModel(
        id=user_id,
        email=f"u{user_id}@example.com",
        roles=roles or [UserRoleEnum.USER],
        name="User",
    )


def _project(owner_id=1, workspace_id=10):
    return ProjectResponse(
        id=5, workspace_id=workspace_id, owner_id=owner_id, name="Campaign"
    )


@pytest.fixture(name="repo")
def fixture_repo():
    return AsyncMock()


@pytest.fixture(name="workspace_auth")
def fixture_workspace_auth():
    return AsyncMock()


@pytest.fixture(name="guard")
def fixture_guard(repo, workspace_auth):
    return ProjectAuth(project_repo=repo, workspace_auth=workspace_auth)


class TestProjectAuth:
    """Owner-only access, plus access to the project's workspace."""

    @pytest.mark.anyio
    async def test_owner_is_authorized_and_workspace_checked(
        self, guard, repo, workspace_auth
    ):
        repo.get_by_id.return_value = _project(owner_id=1, workspace_id=10)
        user = _user(1)

        project = await guard.authorize(5, user)

        assert project.id == 5
        workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=user
        )

    @pytest.mark.anyio
    async def test_missing_project_is_404(self, guard, repo):
        repo.get_by_id.return_value = None

        with pytest.raises(HTTPException) as exc:
            await guard.authorize(5, _user(1))

        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_non_owner_is_403_even_for_admins(
        self, guard, repo, workspace_auth
    ):
        repo.get_by_id.return_value = _project(owner_id=1)

        with pytest.raises(HTTPException) as exc:
            await guard.authorize(5, _user(2, [UserRoleEnum.ADMIN]))

        assert exc.value.status_code == 403
        workspace_auth.authorize.assert_not_awaited()

    @pytest.mark.anyio
    async def test_owner_who_lost_the_workspace_is_refused(
        self, guard, repo, workspace_auth
    ):
        repo.get_by_id.return_value = _project(owner_id=1)
        workspace_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="no access"
        )

        with pytest.raises(HTTPException) as exc:
            await guard.authorize(5, _user(1))

        assert exc.value.status_code == 403
