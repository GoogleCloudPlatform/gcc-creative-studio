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

"""TimelineAuth: timelines inherit their project's owner-only rule."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.projects.dto.project_dto import ProjectResponse
from src.users.user_model import UserModel, UserRoleEnum
from src.workbench.timeline_auth_guard import TimelineAccess, TimelineAuth


def _user(user_id=1, roles=None):
    return UserModel(
        id=user_id,
        email=f"u{user_id}@example.com",
        roles=roles or [UserRoleEnum.USER],
        name="User",
    )


@pytest.fixture(name="timeline_repo")
def fixture_timeline_repo():
    return AsyncMock()


@pytest.fixture(name="project_auth")
def fixture_project_auth():
    return AsyncMock()


@pytest.fixture(name="guard")
def fixture_guard(timeline_repo, project_auth):
    return TimelineAuth(timeline_repo=timeline_repo, project_auth=project_auth)


class TestTimelineAuth:
    """Timelines inherit their project's rule; NULL projects are admin-only."""

    @pytest.mark.anyio
    async def test_owner_of_the_project_is_authorized(
        self, guard, timeline_repo, project_auth
    ):
        timeline_repo.get_access_info.return_value = (5, 7, "1")
        project_auth.authorize.return_value = ProjectResponse(
            id=5, workspace_id=10, owner_id=1, name="P"
        )
        user = _user(1)

        access = await guard.authorize(42, user)

        assert access == TimelineAccess(42, 5, 7, "1", 10)
        project_auth.authorize.assert_awaited_once_with(5, user)

    @pytest.mark.anyio
    async def test_missing_timeline_is_404(self, guard, timeline_repo):
        timeline_repo.get_access_info.return_value = None

        with pytest.raises(HTTPException) as exc:
            await guard.authorize(42, _user(1))

        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_project_refusal_propagates(
        self, guard, timeline_repo, project_auth
    ):
        timeline_repo.get_access_info.return_value = (5, None, None)
        project_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="not yours"
        )

        with pytest.raises(HTTPException) as exc:
            await guard.authorize(42, _user(2))

        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_unattributed_legacy_timeline_is_admin_only(
        self, guard, timeline_repo, project_auth
    ):
        timeline_repo.get_access_info.return_value = (None, None, None)

        with pytest.raises(HTTPException) as exc:
            await guard.authorize(42, _user(1))
        assert exc.value.status_code == 403

        access = await guard.authorize(42, _user(2, [UserRoleEnum.ADMIN]))
        assert access.project_id is None
        assert access.workspace_id is None
        project_auth.authorize.assert_not_awaited()
