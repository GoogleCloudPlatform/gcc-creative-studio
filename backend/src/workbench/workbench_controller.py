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

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.workbench.dto.workbench_dto import (
    TimelineRequest,
    TimelineCreate,
    TimelineUpdate,
    TimelineResponse,
)
from src.workbench.workbench_service import WorkbenchService

router = APIRouter(
    prefix="/api/workbench",
    tags=["workbench"],
)

logger = logging.getLogger(__name__)
security = HTTPBearer()


def cleanup_temp_dir(path: str):
    try:
        shutil.rmtree(path)
        logger.info("Cleaned up temp dir: %s", path)
    except Exception as e:
        logger.error("Failed to cleanup temp dir %s: %s", path, e)


@router.post("/render")
async def render_timeline(
    request: TimelineRequest,
    service: WorkbenchService = Depends(),
):
    video_path, temp_dir = await service.render_timeline(request)

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename="export.mp4",
        background=BackgroundTask(cleanup_temp_dir, temp_dir),
    )


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
    return timeline


@router.get("/timelines", response_model=list[TimelineResponse])
async def list_timelines(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
):
    return await service.list_timelines(storyboard_id)


@router.put("/timelines/{timeline_id}", response_model=TimelineResponse)
async def update_timeline(
    timeline_id: int,
    timeline_update: TimelineUpdate,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
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
):
    success = await service.delete_timeline(timeline_id)
    if not success:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return None
