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
from src.users.user_model import UserModel
from src.projects.project_service import ProjectService
from src.workbench.dto.workbench_dto import (
    TimelineRequest,
    TimelineCreate,
    TimelineUpdate,
    TimelineResponse,
    RenderTimelineRequest,
)
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.workbench.workbench_service import WorkbenchService

router = APIRouter(
    prefix="/api/workbench",
    tags=["workbench"],
)

logger = logging.getLogger(__name__)
security = HTTPBearer()


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
):
    timeline = await service.get_timeline(timeline_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    if str(timeline.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to access this timeline"
        )
    executor = request.app.state.executor
    result = await service.render_timeline(timeline, current_user, executor)
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
):
    if not req.timeline_id:
        raise HTTPException(status_code=400, detail="timeline_id is required")
    timeline = await service.get_timeline(req.timeline_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    if str(timeline.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to access this timeline"
        )
    executor = request.app.state.executor
    result = await service.render_timeline(timeline, current_user, executor)
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
):
    timeline_create.user_id = str(current_user.id)
    return await service.create_timeline(timeline_create)


@router.get("/timelines/{timeline_id}", response_model=TimelineResponse)
async def get_timeline(
    timeline_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    timeline = await service.get_timeline(timeline_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    if str(timeline.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to access this timeline"
        )
    return timeline


@router.get("/timelines", response_model=list[TimelineResponse])
async def list_timelines(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    project_service: ProjectService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    storyboard = await project_service.get_storyboard(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if str(storyboard.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to access these timelines"
        )
    return await service.list_timelines(storyboard_id)


@router.put("/timelines/{timeline_id}", response_model=TimelineResponse)
async def update_timeline(
    timeline_id: int,
    timeline_update: TimelineUpdate,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    timeline = await service.get_timeline(timeline_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    if str(timeline.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to modify this timeline"
        )
    updated_timeline = await service.update_timeline(
        timeline_id, timeline_update
    )
    if not updated_timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return updated_timeline


@router.delete(
    "/timelines/{timeline_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_timeline(
    timeline_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    timeline = await service.get_timeline(timeline_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    if str(timeline.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this timeline"
        )
    success = await service.delete_timeline(timeline_id)
    if not success:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return None
