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

from fastapi import Depends, HTTPException, status
from src.users.user_model import UserModel
from src.projects.project_repository import ProjectRepository
from src.projects.dto.project_dto import ProjectResponse


class ProjectAuth:
    """A dependency class that centralizes project authorization logic."""

    def __init__(self, project_repo: ProjectRepository = Depends()):
        self.project_repo = project_repo

    async def authorize(
        self,
        project_id: int,
        user: UserModel,
    ) -> ProjectResponse:
        """Checks if a user has rights to a project.

        Only the owner of the project has access.
        """
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

        return project
