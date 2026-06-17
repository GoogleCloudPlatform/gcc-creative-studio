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

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db

from src.projects.schema.project_model import (
    Storyboard,
    Timeline,
    Scene,
    VideoClip,
    AudioClip,
)
from src.projects.dto.project_dto import (
    StoryboardResponse,
    StoryboardCreateResponse,
    SceneDTO,
    TimelineDTO,
)


class StoryboardRepository(BaseRepository[Storyboard, StoryboardResponse]):
    """Handles database operations for Storyboard objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Storyboard, schema=StoryboardResponse, db=db)

    async def create(self, data: dict) -> StoryboardCreateResponse:
        """Overwrites create to use StoryboardCreateResponse and avoid lazy loading issues."""
        db_item = self.model(**data)
        self.db.add(db_item)
        await self.db.commit()
        await self.db.refresh(db_item)
        return StoryboardCreateResponse.model_validate(db_item)

    async def update(
        self,
        item_id: int,
        update_data: dict,
    ) -> StoryboardResponse | None:
        """Overrides update to avoid lazy loading issues."""
        query = select(self.model).where(self.model.id == item_id)
        result = await self.db.execute(query)
        db_item = result.scalar_one_or_none()
        if not db_item:
            return None

        for key, value in update_data.items():
            if hasattr(db_item, key):
                setattr(db_item, key, value)

        if hasattr(db_item, "updated_at"):
            import datetime

            db_item.updated_at = datetime.datetime.now(datetime.UTC)

        await self.db.commit()
        return await self.get_by_id_with_details(item_id)

    async def get_by_id_with_details(
        self, storyboard_id: int
    ) -> StoryboardResponse | None:
        """Retrieves a storyboard by ID with all its related data loaded."""
        query = (
            select(self.model)
            .where(self.model.id == storyboard_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline).selectinload(
                    Timeline.video_clips
                ),
                selectinload(self.model.timeline).selectinload(
                    Timeline.audio_clips
                ),
            )
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self.schema.model_validate(item)

    async def find_by_workspace(
        self, workspace_id: int, session_id: str | None = None
    ) -> list[StoryboardResponse]:
        """Finds storyboards for a given workspace, optionally filtered by session."""
        query = (
            select(self.model)
            .where(self.model.workspace_id == workspace_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline).selectinload(
                    Timeline.video_clips
                ),
                selectinload(self.model.timeline).selectinload(
                    Timeline.audio_clips
                ),
            )
        )
        if session_id:
            query = query.where(self.model.session_id == session_id)
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]

    async def update_storyboard_data(
        self,
        storyboard_id: int,
        bg_music_description: str | None = None,
        scenes: list[SceneDTO] | None = None,
        timeline: TimelineDTO | None = None,
    ) -> StoryboardResponse | None:
        """Updates or creates related data for a storyboard."""
        query = (
            select(self.model)
            .where(self.model.id == storyboard_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline).selectinload(
                    Timeline.video_clips
                ),
                selectinload(self.model.timeline).selectinload(
                    Timeline.audio_clips
                ),
            )
        )
        result = await self.db.execute(query)
        storyboard = result.scalar_one_or_none()
        if not storyboard:
            return None

        if bg_music_description is not None:
            storyboard.bg_music_description = bg_music_description

        if scenes is not None:
            # Clear existing scenes
            storyboard.scenes.clear()

            for scene_dto in scenes:
                new_scene = Scene(
                    **scene_dto.model_dump(exclude={"id"}, exclude_none=True)
                )
                storyboard.scenes.append(new_scene)

        if timeline is not None:
            if not storyboard.timeline:
                storyboard.timeline = Timeline()
            storyboard.timeline.title = timeline.title

            storyboard.timeline.video_clips.clear()
            for clip_dto in timeline.video_clips:
                new_clip = VideoClip(
                    **clip_dto.model_dump(
                        exclude={
                            "id",
                            "presigned_url",
                            "presigned_thumbnail_url",
                        },
                        exclude_none=True,
                    )
                )
                storyboard.timeline.video_clips.append(new_clip)

            storyboard.timeline.audio_clips.clear()
            for clip_dto in timeline.audio_clips:
                new_clip = AudioClip(
                    **clip_dto.model_dump(
                        exclude={"id", "presigned_url"}, exclude_none=True
                    )
                )
                storyboard.timeline.audio_clips.append(new_clip)

        await self.db.commit()
        return await self.get_by_id_with_details(storyboard_id)
