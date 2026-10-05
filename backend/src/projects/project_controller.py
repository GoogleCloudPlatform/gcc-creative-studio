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

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from src.auth.auth_guard import get_current_user
from src.common.request_context import is_agent_request
from src.users.user_model import UserModel
from src.agents.agent_service import AgentService
from src.projects.project_service import ProjectService
from src.projects.dto.project_dto import (
    StoryboardCreate,
    StoryboardUpdate,
    StoryboardResponse,
    StoryboardCreateResponse,
    StoryboardUpdateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/storyboards",
    tags=["Storyboards"],
)


@router.post(
    "/",
    response_model=StoryboardCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_storyboard(
    storyboard_create: StoryboardCreate,
    current_user: UserModel = Depends(get_current_user),
    project_service: ProjectService = Depends(),
):
    storyboard = await project_service.create_storyboard(
        storyboard_create,
        current_user.id,
        reuse_session_record=is_agent_request.get(),
    )
    return storyboard


@router.get("/{storyboard_id}", response_model=StoryboardResponse)
async def get_storyboard(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    project_service: ProjectService = Depends(),
):
    storyboard = await project_service.get_storyboard(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to access this storyboard"
        )

    return storyboard


@router.get("", response_model=list[StoryboardResponse])
async def list_storyboards(
    workspace_id: int,
    session_id: str | None = None,
    current_user: UserModel = Depends(get_current_user),
    project_service: ProjectService = Depends(),
):
    storyboards = await project_service.list_storyboards(
        workspace_id, session_id
    )
    return storyboards


@router.put("/{storyboard_id}", response_model=StoryboardUpdateResponse)
async def update_storyboard(
    storyboard_id: int,
    storyboard_update: StoryboardUpdate,
    current_user: UserModel = Depends(get_current_user),
    project_service: ProjectService = Depends(),
    agent_service: AgentService = Depends(),
):
    storyboard = await project_service.get_storyboard(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to modify this storyboard"
        )

    updated_storyboard = await project_service.update_storyboard(
        storyboard_id, storyboard_update
    )
    if not updated_storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    response = StoryboardUpdateResponse.model_validate(
        updated_storyboard, from_attributes=True
    )
    # A human edit must reach the agent's session state, or the next
    # generation pass renders from the storyboard the user just changed.
    # The agent's own saves are the state and are not mirrored back.
    if not is_agent_request.get():
        response.agent_sync = await agent_service.sync_storyboard_to_session(
            current_user, response
        )
        await _persist_agent_scene_ids(project_service, response)
    return response


async def _persist_agent_scene_ids(
    project_service: ProjectService, response: StoryboardUpdateResponse
) -> None:
    """Writes the identities the sync resolved back onto the scene rows.

    Rows the agent saved carry no ``scene_id`` (Izumi does not send it), so
    the first human edit matches them on evidence (frame / topic / position).
    Persisting the resolved ids makes every later edit match by identity, so
    a reorder can never again be mistaken for a frame replacement. Best
    effort: the record and the session are already consistent.
    """
    sync = response.agent_sync or {}
    if sync.get("status") != "synced":
        return
    scene_ids = sync.get("scene_ids") or []
    if not scene_ids:
        return
    try:
        await project_service.assign_scene_ids(
            response.id, response.scenes, [str(s) for s in scene_ids]
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "[Storyboard sync] storyboard_id=%s: scene ids were not persisted: %s",
            response.id,
            e,
        )


@router.delete("/{storyboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storyboard(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    project_service: ProjectService = Depends(),
):
    storyboard = await project_service.get_storyboard(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this storyboard"
        )

    await project_service.delete_storyboard(storyboard_id)
    return None
