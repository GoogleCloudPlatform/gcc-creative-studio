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
"""Authorization for projects (owner-only)."""

from fastapi import Depends, HTTPException, status

from src.projects.dto.project_dto import ProjectResponse
from src.projects.project_repository import ProjectRepository
from src.users.user_model import UserModel
from src.workspaces.workspace_auth_guard import WorkspaceAuth


class ProjectAuth:
    """A dependency that centralizes project authorization.

    Projects are owner-only, even inside a shared or public workspace. The
    owner must also still have access to the project's workspace: losing
    membership of a private workspace revokes access to the projects in it.
    The method is named ``authorize`` (like ``WorkspaceAuth``), never
    ``assert_*``: tests replace these classes with mocks, and
    ``unittest.mock`` rejects attributes whose names start with ``assert``.
    """

    def __init__(
        self,
        project_repo: ProjectRepository = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
    ):
        self.project_repo = project_repo
        self.workspace_auth = workspace_auth

    async def authorize(
        self, project_id: int, user: UserModel
    ) -> ProjectResponse:
        """Returns the project if ``user`` owns it; raises 404/403 otherwise."""
        project = await self.project_repo.get_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID '{project_id}' not found.",
            )
        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this project.",
            )
        await self.workspace_auth.authorize(
            workspace_id=project.workspace_id, user=user
        )
        return project
