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
"""API endpoints for workbench."""

import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.auth_guard import get_current_user
from src.common.request_context import is_agent_request
from src.users.user_model import UserModel
from src.workbench.dto.workbench_dto import (
    TimelineRequest,
    TimelineCreate,
    TimelineUpdate,
    TimelineResponse,
    RenderTimelineRequest,
)
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.projects.project_service import ProjectService
from src.workbench.timeline_auth_guard import TimelineAuth
from src.workbench.workbench_service import WorkbenchService

router = APIRouter(
    prefix="/api/workbench",
    tags=["workbench"],
)

logger = logging.getLogger(__name__)
security = HTTPBearer()


def _as_int(value) -> int | None:
    """Parses an id the DTO types as ``str | int`` (Izumi sends either)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post(
    "/timelines/{timeline_id}/render",
    response_model=MediaItemResponse,
)
async def render_timeline_by_id(
    timeline_id: int,
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    timeline_auth: TimelineAuth = Depends(),
):
    await timeline_auth.authorize(timeline_id, current_user)
    executor = request.app.state.executor
    result = await service.render_timeline_by_id(
        timeline_id, current_user, executor
    )
    if not result:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return result


@router.post("/render", response_model=MediaItemResponse)
async def render_timeline(
    req: RenderTimelineRequest,
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    timeline_auth: TimelineAuth = Depends(),
):
    if not req.timeline_id:
        raise HTTPException(status_code=400, detail="timeline_id is required")
    await timeline_auth.authorize(req.timeline_id, current_user)
    executor = request.app.state.executor
    result = await service.render_timeline_by_id(
        req.timeline_id, current_user, executor
    )
    if not result:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return result


@router.post(
    "/timelines",
    response_model=TimelineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_timeline(
    timeline_create: TimelineCreate,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    project_service: ProjectService = Depends(),
):
    # The project comes from the storyboard, an explicit hint, the chat or
    # the user's default project. Owner, project and workspace are
    # server-side facts: client values are ignored.
    project = await project_service.resolve_project_for_write(
        current_user,
        _as_int(timeline_create.workspace_id),
        project_id=timeline_create.project_id,
        storyboard_id=_as_int(timeline_create.storyboard_id),
        session_id=timeline_create.session_id,
    )
    timeline_create.project_id = project.id
    timeline_create.user_id = str(current_user.id)
    timeline_create.workspace_id = str(project.workspace_id)
    # The agent re-creates the timeline on every stitch; replace the
    # storyboard's existing cut in place so the Workbench follows the live one.
    return await service.create_timeline(
        timeline_create, reuse_for_storyboard=is_agent_request.get()
    )


@router.get("/timelines/{timeline_id}", response_model=TimelineResponse)
async def get_timeline(
    timeline_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    timeline_auth: TimelineAuth = Depends(),
):
    await timeline_auth.authorize(timeline_id, current_user)
    timeline = await service.get_timeline(timeline_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return timeline


@router.get("/timelines", response_model=list[TimelineResponse])
async def list_timelines(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    project_service: ProjectService = Depends(),
):
    await project_service.authorize_storyboard(current_user, storyboard_id)
    return await service.list_timelines(storyboard_id)


@router.put("/timelines/{timeline_id}", response_model=TimelineResponse)
async def update_timeline(
    timeline_id: int,
    timeline_update: TimelineUpdate,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    timeline_auth: TimelineAuth = Depends(),
    project_service: ProjectService = Depends(),
):
    access = await timeline_auth.authorize(timeline_id, current_user)
    # A timeline may only be re-linked to a storyboard of its own project.
    target_project_id = None
    target_workspace_id = None
    new_storyboard_id = _as_int(timeline_update.storyboard_id)
    if (
        new_storyboard_id is not None
        and new_storyboard_id != access.storyboard_id
    ):
        target = await project_service.authorize_storyboard(
            current_user, new_storyboard_id
        )
        if access.project_id is not None and target.id != access.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The storyboard belongs to another project.",
            )
        target_project_id = target.id
        target_workspace_id = target.workspace_id
    timeline_update.project_id = access.project_id or target_project_id
    timeline_update.user_id = access.user_id or str(current_user.id)
    # The workspace follows the owning project: a legacy row claimed through
    # the storyboard takes its project's workspace. Only a row that stays
    # unattributed keeps the payload's value (no project to follow).
    project_workspace_id = access.workspace_id or target_workspace_id
    if project_workspace_id is not None:
        timeline_update.workspace_id = str(project_workspace_id)
    timeline = await service.update_timeline(timeline_id, timeline_update)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return timeline


@router.delete(
    "/timelines/{timeline_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_timeline(
    timeline_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    timeline_auth: TimelineAuth = Depends(),
):
    await timeline_auth.authorize(timeline_id, current_user)
    success = await service.delete_timeline(timeline_id)
    if not success:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return None
