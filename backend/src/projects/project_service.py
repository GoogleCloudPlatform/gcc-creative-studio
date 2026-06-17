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
    TimelineDTO,
    VideoClipDTO,
    AudioClipDTO,
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

        if storyboard.timeline:
            for clip in storyboard.timeline.video_clips:
                if clip.media_item_id:
                    media_item = await self.media_repo.get_by_id(
                        clip.media_item_id
                    )
                    if media_item and media_item.gcs_uris:
                        gcs_uri = media_item.gcs_uris[0]
                        presigned_url = await asyncio.to_thread(
                            self.iam_signer_credentials.generate_presigned_url,
                            gcs_uri,
                        )
                        clip.presigned_url = presigned_url

                        if media_item.thumbnail_uris:
                            thumb_gcs_uri = media_item.thumbnail_uris[0]
                            presigned_thumb_url = await asyncio.to_thread(
                                self.iam_signer_credentials.generate_presigned_url,
                                thumb_gcs_uri,
                            )
                            clip.presigned_thumbnail_url = presigned_thumb_url

            for clip in storyboard.timeline.audio_clips:
                if clip.media_item_id:
                    media_item = await self.media_repo.get_by_id(
                        clip.media_item_id
                    )
                    if media_item and media_item.gcs_uris:
                        gcs_uri = media_item.gcs_uris[0]
                        presigned_url = await asyncio.to_thread(
                            self.iam_signer_credentials.generate_presigned_url,
                            gcs_uri,
                        )
                        clip.presigned_url = presigned_url

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
        timeline_data = storyboard_update.timeline_data

        if storyboard_update.storyboard is not None:
            if scenes_data is None:
                scenes_data = storyboard_update.storyboard.get("scenes")
            if timeline_data is None:
                timeline_data = storyboard_update.storyboard.get("timeline")

        if (
            scenes_data is not None
            or storyboard_update.bg_music_description is not None
            or timeline_data is not None
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

            timeline_dto = None
            if timeline_data is not None:
                video_clips = []
                for clip_data in timeline_data.get("video_clips", []):
                    media_item_id = clip_data.get(
                        "media_item_id"
                    ) or clip_data.get("asset", {}).get("id")
                    trim_data = clip_data.get("trim") or {}
                    trim_offset = trim_data.get("offset") or trim_data.get(
                        "offset_seconds", 0
                    )
                    trim_duration = trim_data.get("duration") or trim_data.get(
                        "duration_seconds"
                    )
                    video_clips.append(
                        VideoClipDTO(
                            media_item_id=media_item_id,
                            source_asset_id=clip_data.get("source_asset_id"),
                            trim_offset=trim_offset,
                            trim_duration=trim_duration,
                            volume=clip_data.get("volume", 1.0),
                            speed=clip_data.get("speed", 1.0),
                        )
                    )

                audio_clips = []
                for clip_data in timeline_data.get("audio_clips", []):
                    media_item_id = clip_data.get(
                        "media_item_id"
                    ) or clip_data.get("asset", {}).get("id")
                    trim_data = clip_data.get("trim") or {}
                    trim_offset = trim_data.get("offset") or trim_data.get(
                        "offset_seconds", 0
                    )
                    trim_duration = trim_data.get("duration") or trim_data.get(
                        "duration_seconds"
                    )
                    start_at_data = clip_data.get("start_at") or {}
                    start_offset = clip_data.get(
                        "start_offset"
                    ) or start_at_data.get("offset_seconds", 0)
                    audio_clips.append(
                        AudioClipDTO(
                            media_item_id=media_item_id,
                            source_asset_id=clip_data.get("source_asset_id"),
                            start_offset=start_offset,
                            trim_offset=trim_offset,
                            trim_duration=trim_duration,
                            volume=clip_data.get("volume", 1.0),
                        )
                    )

                timeline_dto = TimelineDTO(
                    title=timeline_data.get("title"),
                    video_clips=video_clips,
                    audio_clips=audio_clips,
                )

            updated_storyboard = (
                await self.storyboard_repo.update_storyboard_data(
                    storyboard_id=storyboard_id,
                    bg_music_description=storyboard_update.bg_music_description,
                    scenes=scenes_dto,
                    timeline=timeline_dto,
                )
            )
            return updated_storyboard

        return await self.storyboard_repo.get_by_id_with_details(storyboard_id)

    async def delete_storyboard(self, storyboard_id: int):
        await self.storyboard_repo.delete(storyboard_id)
