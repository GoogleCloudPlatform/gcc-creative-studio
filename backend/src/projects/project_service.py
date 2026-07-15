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
from fastapi import Depends
from src.projects.project_repository import StoryboardRepository
from src.images.repository.media_item_repository import MediaRepository
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.projects.dto.project_dto import (
    StoryboardResponse,
    StoryboardCreateResponse,
    StoryboardCreate,
    StoryboardUpdate,
    SceneDTO,
)


class ProjectService:
    def __init__(
        self,
        storyboard_repo: StoryboardRepository = Depends(),
        media_repo: MediaRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
    ):
        self.storyboard_repo = storyboard_repo
        self.media_repo = media_repo
        self.iam_signer_credentials = iam_signer_credentials

    async def _enrich_storyboard(self, storyboard: StoryboardResponse):
        """Enriches a storyboard with presigned URLs."""
        for scene in storyboard.scenes:
            if scene.first_frame_media_item_id:
                media_item = await self.media_repo.get_by_id(
                    scene.first_frame_media_item_id
                )
                if media_item and media_item.gcs_uris:
                    gcs_uri = media_item.gcs_uris[0]
                    presigned_url = await asyncio.to_thread(
                        self.iam_signer_credentials.generate_presigned_url,
                        gcs_uri,
                    )
                    scene.first_frame_generated_url = presigned_url

    async def create_storyboard(
        self, storyboard_create: StoryboardCreate, user_id: int
    ) -> StoryboardCreateResponse:
        data = storyboard_create.model_dump()
        data["user_id"] = user_id
        return await self.storyboard_repo.create(data)

    async def get_storyboard(
        self, storyboard_id: int
    ) -> StoryboardResponse | None:
        storyboard = await self.storyboard_repo.get_by_id_with_details(
            storyboard_id
        )
        if storyboard:
            await self._enrich_storyboard(storyboard)
        return storyboard

    async def list_storyboards(
        self, workspace_id: int, session_id: str | None = None
    ) -> list[StoryboardResponse]:
        storyboards = await self.storyboard_repo.find_by_workspace(
            workspace_id, session_id
        )
        for sb in storyboards:
            await self._enrich_storyboard(sb)
        return storyboards

    async def update_storyboard(
        self, storyboard_id: int, storyboard_update: StoryboardUpdate
    ) -> StoryboardResponse | None:
        storyboard = await self.storyboard_repo.get_by_id_with_details(
            storyboard_id
        )
        if not storyboard:
            return None

        if storyboard_update.template_name is not None:
            await self.storyboard_repo.update(
                storyboard_id,
                {"template_name": storyboard_update.template_name},
            )

        if storyboard_update.bg_music_asset_id is not None:
            await self.storyboard_repo.update(
                storyboard_id,
                {"bg_music_asset_id": storyboard_update.bg_music_asset_id},
            )

        scenes_data = storyboard_update.scenes

        if storyboard_update.storyboard is not None:
            if scenes_data is None:
                scenes_data = storyboard_update.storyboard.get("scenes")

        if (
            scenes_data is not None
            or storyboard_update.bg_music_description is not None
        ):
            scenes_dto = None
            if scenes_data is not None:
                scenes_dto = []
                for scene_data in scenes_data:
                    first_frame_media_item_id = scene_data.get(
                        "first_frame_prompt", {}
                    ).get("media_item_id", None) or scene_data.get(
                        "first_frame_prompt", {}
                    ).get(
                        "asset_id"
                    )

                    video_media_item_id = scene_data.get(
                        "video_prompt", {}
                    ).get("media_item_id", None) or scene_data.get(
                        "video_prompt", {}
                    ).get(
                        "asset_id"
                    )

                    voiceover_media_item_id = scene_data.get(
                        "voiceover_prompt", {}
                    ).get("media_item_id", None) or scene_data.get(
                        "voiceover_prompt", {}
                    ).get(
                        "asset_id"
                    )

                    scenes_dto.append(
                        SceneDTO(
                            topic=scene_data.get("topic"),
                            duration_seconds=scene_data.get("duration_seconds"),
                            first_frame_description=scene_data.get(
                                "first_frame_prompt", {}
                            ).get("description"),
                            first_frame_media_item_id=first_frame_media_item_id,
                            first_frame_source_asset_id=scene_data.get(
                                "first_frame_prompt", {}
                            ).get("source_asset_id"),
                            video_description=scene_data.get(
                                "video_prompt", {}
                            ).get("description"),
                            video_duration_seconds=scene_data.get(
                                "video_prompt", {}
                            ).get("duration_seconds"),
                            video_media_item_id=video_media_item_id,
                            video_source_asset_id=scene_data.get(
                                "video_prompt", {}
                            ).get("source_asset_id"),
                            video_generated_url=scene_data.get(
                                "video_prompt", {}
                            ).get("generated_url"),
                            voiceover_text=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("text"),
                            voiceover_gender=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("gender"),
                            voiceover_description=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("description"),
                            voiceover_media_item_id=voiceover_media_item_id,
                            voiceover_source_asset_id=scene_data.get(
                                "voiceover_prompt", {}
                            ).get("source_asset_id"),
                            transition_type=scene_data.get(
                                "transition_hints", {}
                            ).get("type"),
                            transition_duration=scene_data.get(
                                "transition_hints", {}
                            ).get("duration"),
                            audio_ambient_description=scene_data.get(
                                "audio_hints", {}
                            ).get("ambient_sound"),
                            audio_sfx_description=scene_data.get(
                                "audio_hints", {}
                            ).get("sfx"),
                        )
                    )

            updated_storyboard = (
                await self.storyboard_repo.update_storyboard_data(
                    storyboard_id=storyboard_id,
                    bg_music_description=storyboard_update.bg_music_description,
                    scenes=scenes_dto,
                )
            )
            return updated_storyboard

        return await self.storyboard_repo.get_by_id_with_details(storyboard_id)

    async def delete_storyboard(self, storyboard_id: int):
        await self.storyboard_repo.delete(storyboard_id)
