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
from src.workbench.workbench_service import WorkbenchService
from src.workspaces.workspace_auth_guard import WorkspaceAuth

router = APIRouter(
    prefix="/api/workbench",
    tags=["workbench"],
)

logger = logging.getLogger(__name__)
security = HTTPBearer()


def _require_workspace_id(raw: object, *, status_code: int) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if isinstance(raw, str) and (s := raw.strip()).isdigit() and int(s) > 0:
        return int(s)
    raise HTTPException(
        status_code, detail="A valid positive integer workspace_id is required."
    )


async def _load_authorized_timeline(
    timeline_id: int,
    user: UserModel,
    service: WorkbenchService,
    ws_auth: WorkspaceAuth,
    *,
    write: bool = False,
):
    timeline = await service.get_timeline(timeline_id, enrich=False)
    if not timeline:
        raise HTTPException(404, detail="Timeline not found")
    ws_id = _require_workspace_id(timeline.workspace_id, status_code=403)
    fn = ws_auth.authorize_write if write else ws_auth.authorize
    await fn(workspace_id=ws_id, user=user)
    return timeline, ws_id


@router.post(
    "/timelines/{timeline_id}/render",
    response_model=MediaItemResponse,
)
async def render_timeline_by_id(
    timeline_id: int,
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    timeline, _ = await _load_authorized_timeline(
        timeline_id, current_user, service, workspace_auth, write=True
    )
    executor = request.app.state.executor
    result = await service.render_timeline_by_id(
        timeline_id, current_user, executor, timeline=timeline
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
    workspace_auth: WorkspaceAuth = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not req.timeline_id:
        raise HTTPException(status_code=400, detail="timeline_id is required")
    timeline, _ = await _load_authorized_timeline(
        req.timeline_id, current_user, service, workspace_auth, write=True
    )
    executor = request.app.state.executor
    result = await service.render_timeline_by_id(
        req.timeline_id, current_user, executor, timeline=timeline
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
    workspace_auth: WorkspaceAuth = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    ws_id = _require_workspace_id(
        timeline_create.workspace_id,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    await workspace_auth.authorize_write(workspace_id=ws_id, user=current_user)
    # The agent re-creates the timeline on every stitch; replace the
    # storyboard's existing cut in place so the Workbench follows the live one.
    return await service.create_timeline(
        timeline_create,
        reuse_for_storyboard=is_agent_request.get(),
        current_user=current_user,
    )


@router.get("/timelines/{timeline_id}", response_model=TimelineResponse)
async def get_timeline(
    timeline_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    timeline, _ = await _load_authorized_timeline(
        timeline_id, current_user, service, workspace_auth
    )
    await service.enrich_timeline(timeline)
    return timeline


@router.get("/timelines", response_model=list[TimelineResponse])
async def list_timelines(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
):
    timelines = await service.list_timelines(storyboard_id, enrich=False)
    checked_workspaces: set[int] = set()
    for timeline in timelines:
        ws_id = _require_workspace_id(
            timeline.workspace_id,
            status_code=status.HTTP_403_FORBIDDEN,
        )
        if ws_id not in checked_workspaces:
            await workspace_auth.authorize(
                workspace_id=ws_id, user=current_user
            )
            checked_workspaces.add(ws_id)
    for timeline in timelines:
        await service.enrich_timeline(timeline)
    return timelines


@router.put("/timelines/{timeline_id}", response_model=TimelineResponse)
async def update_timeline(
    timeline_id: int,
    timeline_update: TimelineUpdate,
    current_user: UserModel = Depends(get_current_user),
    service: WorkbenchService = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _, existing_ws_id = await _load_authorized_timeline(
        timeline_id, current_user, service, workspace_auth, write=True
    )
    target_ws_id = _require_workspace_id(
        timeline_update.workspace_id,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    if target_ws_id != existing_ws_id:
        await workspace_auth.authorize_write(
            workspace_id=target_ws_id, user=current_user
        )
    timeline = await service.update_timeline(
        timeline_id, timeline_update, current_user=current_user
    )
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
    workspace_auth: WorkspaceAuth = Depends(),
):
    await _load_authorized_timeline(
        timeline_id, current_user, service, workspace_auth, write=True
    )
    success = await service.delete_timeline(timeline_id)
    if not success:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return None
