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
"""Authorization for Workbench timelines (through their project)."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

from src.projects.project_auth_guard import ProjectAuth
from src.users.user_model import UserModel, UserRoleEnum
from src.workbench.repository.timeline_repository import TimelineRepository


@dataclass(frozen=True)
class TimelineAccess:
    """What an authorized caller may rely on about a timeline."""

    timeline_id: int
    project_id: int | None
    storyboard_id: int | None
    user_id: str | None
    # Workspace of the owning project (None for legacy, unattributed rows).
    workspace_id: int | None


class TimelineAuth:
    """A dependency that guards every timeline-by-id endpoint.

    A timeline belongs to a project and inherits that project's owner-only
    rule (see ``ProjectAuth``). The Izumi agent passes the check too: it
    calls with the end user's token (``X-User-Authorization``). Legacy rows
    the projects migration could not attribute (``project_id`` NULL) are
    admin-only.
    """

    def __init__(
        self,
        timeline_repo: TimelineRepository = Depends(),
        project_auth: ProjectAuth = Depends(),
    ):
        self.timeline_repo = timeline_repo
        self.project_auth = project_auth

    async def authorize(
        self, timeline_id: int, user: UserModel
    ) -> TimelineAccess:
        info = await self.timeline_repo.get_access_info(timeline_id)
        if info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Timeline not found",
            )
        project_id, storyboard_id, owner_id = info
        if project_id is None:
            if UserRoleEnum.ADMIN in user.roles:
                return TimelineAccess(
                    timeline_id, None, storyboard_id, owner_id, None
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this timeline",
            )
        project = await self.project_auth.authorize(project_id, user)
        return TimelineAccess(
            timeline_id,
            project_id,
            storyboard_id,
            owner_id,
            project.workspace_id,
        )
