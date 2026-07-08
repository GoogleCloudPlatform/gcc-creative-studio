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

from fastapi import APIRouter, Depends, HTTPException, status
from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.projects.project_service import ProjectService
from src.projects.dto.project_dto import (
    StoryboardCreate,
    StoryboardUpdate,
    StoryboardResponse,
    StoryboardCreateResponse,
)

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
        storyboard_create, current_user.id
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


@router.put("/{storyboard_id}", response_model=StoryboardResponse)
async def update_storyboard(
    storyboard_id: int,
    storyboard_update: StoryboardUpdate,
    current_user: UserModel = Depends(get_current_user),
    project_service: ProjectService = Depends(),
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
    return updated_storyboard


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
