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
        self,
        storyboard_create: StoryboardCreate,
        user_id: int,
        reuse_session_record: bool = False,
    ) -> StoryboardCreateResponse:
        """Creates a storyboard record.

        With ``reuse_session_record`` (the agent's create path) a session that
        already owns a storyboard gets that record back, with the scalar
        fields refreshed, instead of a second one: Izumi re-creates its
        storyboard on every pipeline restart and would otherwise leave the
        Workbench pointing at a stale record.
        """
        data = storyboard_create.model_dump()
        data["user_id"] = user_id
        session_id = storyboard_create.session_id
        if reuse_session_record and session_id:
            existing = await self.storyboard_repo.find_latest_by_session(
                storyboard_create.workspace_id, session_id, user_id
            )
            if existing:
                scalar_updates = {
                    key: data[key]
                    for key in (
                        "template_name",
                        "bg_music_description",
                        "bg_music_asset_id",
                    )
                    if data.get(key) is not None
                }
                if scalar_updates:
                    await self.storyboard_repo.update(
                        existing.id, scalar_updates
                    )
                    existing = existing.model_copy(update=scalar_updates)
                return existing
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
                for idx, scene_data in enumerate(scenes_data):
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

                    raw_scene_id = scene_data.get("scene_id")
                    scenes_dto.append(
                        SceneDTO(
                            scene_id=(
                                str(raw_scene_id)
                                if raw_scene_id not in (None, "")
                                else None
                            ),
                            order=idx,
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
            if updated_storyboard:
                await self._enrich_storyboard(updated_storyboard)
            return updated_storyboard

        refreshed = await self.storyboard_repo.get_by_id_with_details(
            storyboard_id
        )
        if refreshed:
            await self._enrich_storyboard(refreshed)
        return refreshed

    async def assign_scene_ids(
        self,
        storyboard_id: int,
        scenes: list[SceneDTO],
        scene_ids: list[str],
    ) -> dict[int, str]:
        """Stamps the agent's stable identities onto freshly saved scene rows.

        ``scene_ids`` is what the session sync resolved, one per scene in
        display order. Rows that already carry their id are left alone; the
        others are written and the DTOs patched in place, so the response
        the Workbench adopts carries them and the next edit matches by
        identity. Returns ``{row_id: scene_id}`` of what was written.
        """
        if len(scene_ids) != len(scenes):
            return {}
        assignments: dict[int, str] = {}
        for scene, scene_id in zip(scenes, scene_ids):
            if scene.id is None or not scene_id or scene.scene_id == scene_id:
                continue
            assignments[scene.id] = scene_id
        if not assignments:
            return {}
        await self.storyboard_repo.set_scene_ids(storyboard_id, assignments)
        for scene in scenes:
            if scene.id in assignments:
                scene.scene_id = assignments[scene.id]
        return assignments

    async def delete_storyboard(self, storyboard_id: int):
        await self.storyboard_repo.delete(storyboard_id)
