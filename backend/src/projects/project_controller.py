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

import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.projects.project_repository import StoryboardRepository
from src.images.repository.media_item_repository import MediaRepository
from src.auth.iam_signer_credentials_service import IamSignerCredentials
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


async def _enrich_storyboard(
    storyboard: StoryboardResponse,
    media_repo: MediaRepository,
    iam_signer_credentials: IamSignerCredentials,
):
    """Enriches a storyboard with presigned URLs."""
    for scene in storyboard.scenes:
        if scene.first_frame_media_item_id:
            media_item = await media_repo.get_by_id(
                scene.first_frame_media_item_id
            )
            if media_item and media_item.gcs_uris:
                gcs_uri = media_item.gcs_uris[0]
                presigned_url = await asyncio.to_thread(
                    iam_signer_credentials.generate_presigned_url, gcs_uri
                )
                scene.first_frame_generated_url = presigned_url

    if storyboard.timeline:
        for clip in storyboard.timeline.video_clips:
            if clip.media_item_id:
                media_item = await media_repo.get_by_id(clip.media_item_id)
                if media_item and media_item.gcs_uris:
                    gcs_uri = media_item.gcs_uris[0]
                    presigned_url = await asyncio.to_thread(
                        iam_signer_credentials.generate_presigned_url, gcs_uri
                    )
                    clip.presigned_url = presigned_url

                    if media_item.thumbnail_uris:
                        thumb_gcs_uri = media_item.thumbnail_uris[0]
                        presigned_thumb_url = await asyncio.to_thread(
                            iam_signer_credentials.generate_presigned_url,
                            thumb_gcs_uri,
                        )
                        clip.presigned_thumbnail_url = presigned_thumb_url

        for clip in storyboard.timeline.audio_clips:
            if clip.media_item_id:
                media_item = await media_repo.get_by_id(clip.media_item_id)
                if media_item and media_item.gcs_uris:
                    gcs_uri = media_item.gcs_uris[0]
                    presigned_url = await asyncio.to_thread(
                        iam_signer_credentials.generate_presigned_url, gcs_uri
                    )
                    clip.presigned_url = presigned_url


@router.post(
    "/",
    response_model=StoryboardCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_storyboard(
    storyboard_create: StoryboardCreate,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends(),
):
    data = storyboard_create.model_dump()
    data["user_id"] = current_user.id

    storyboard = await storyboard_repo.create(data)
    return storyboard


@router.get("/{storyboard_id}", response_model=StoryboardResponse)
async def get_storyboard(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends(),
    media_repo: MediaRepository = Depends(),
    iam_signer_credentials: IamSignerCredentials = Depends(),
):
    storyboard = await storyboard_repo.get_by_id_with_details(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to access this storyboard"
        )

    await _enrich_storyboard(storyboard, media_repo, iam_signer_credentials)

    return storyboard


@router.get("", response_model=list[StoryboardResponse])
async def list_storyboards(
    workspace_id: int,
    session_id: str | None = None,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends(),
    media_repo: MediaRepository = Depends(),
    iam_signer_credentials: IamSignerCredentials = Depends(),
):
    storyboards = await storyboard_repo.find_by_workspace(
        workspace_id, session_id
    )
    for sb in storyboards:
        await _enrich_storyboard(sb, media_repo, iam_signer_credentials)
    return storyboards


@router.put("/{storyboard_id}", response_model=StoryboardResponse)
async def update_storyboard(
    storyboard_id: int,
    storyboard_update: StoryboardUpdate,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends(),
):
    storyboard = await storyboard_repo.get_by_id_with_details(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to modify this storyboard"
        )

    if storyboard_update.template_name is not None:
        await storyboard_repo.update(
            storyboard_id, {"template_name": storyboard_update.template_name}
        )

    if storyboard_update.bg_music_asset_id is not None:
        await storyboard_repo.update(
            storyboard_id,
            {"bg_music_asset_id": storyboard_update.bg_music_asset_id},
        )

    if (
        storyboard_update.scenes is not None
        or storyboard_update.bg_music_description is not None
        or storyboard_update.timeline_data is not None
    ):
        storyboard_data = {}
        if storyboard_update.scenes is not None:
            storyboard_data["scenes"] = storyboard_update.scenes
        if storyboard_update.bg_music_description is not None:
            storyboard_data["background_music_prompt"] = {
                "description": storyboard_update.bg_music_description
            }

        updated_storyboard = await storyboard_repo.update_storyboard_data(
            storyboard_id=storyboard_id,
            storyboard_data=storyboard_data if storyboard_data else None,
            timeline_data=storyboard_update.timeline_data,
        )
        return updated_storyboard

    return await storyboard_repo.get_by_id_with_details(storyboard_id)


@router.delete("/{storyboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storyboard(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends(),
):
    storyboard = await storyboard_repo.get_by_id(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this storyboard"
        )

    await storyboard_repo.delete(storyboard_id)
    return None
