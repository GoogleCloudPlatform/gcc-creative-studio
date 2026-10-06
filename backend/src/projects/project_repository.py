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
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db

from src.projects.schema.project_model import Storyboard, Scene
from src.workbench.schema.timeline_model import Timeline, VideoClip, AudioClip
from src.projects.dto.project_dto import (
    StoryboardResponse,
    StoryboardCreateResponse,
    SceneDTO,
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
                selectinload(self.model.timeline),
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
        """Finds storyboards for a given workspace, optionally filtered by session.

        Newest first: callers that take ``[0]`` as "the" storyboard of a
        session must get the live one, not whichever row the planner
        happened to return first.
        """
        query = (
            select(self.model)
            .where(self.model.workspace_id == workspace_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline),
            )
            .order_by(self.model.id.desc())
        )
        if session_id:
            query = query.where(self.model.session_id == session_id)
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]

    async def find_latest_by_session(
        self, workspace_id: int, session_id: str, user_id: int
    ) -> StoryboardCreateResponse | None:
        """The newest storyboard record a user's agent session already owns."""
        query = (
            select(self.model)
            .where(
                self.model.workspace_id == workspace_id,
                self.model.session_id == session_id,
                self.model.user_id == user_id,
            )
            .order_by(self.model.id.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return StoryboardCreateResponse.model_validate(item)

    async def update_storyboard_data(
        self,
        storyboard_id: int,
        bg_music_description: str | None = None,
        scenes: list[SceneDTO] | None = None,
    ) -> StoryboardResponse | None:
        """Updates or creates related data for a storyboard."""
        query = (
            select(self.model)
            .where(self.model.id == storyboard_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline),
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

        await self.db.commit()
        return await self.get_by_id_with_details(storyboard_id)

    async def set_scene_ids(
        self, storyboard_id: int, assignments: dict[int, str]
    ) -> None:
        """Writes the agent's stable ``scene_id`` onto existing scene rows.

        ``assignments`` maps a scene row id to its identity. The rows are
        pinned to ``storyboard_id`` so a stale client cannot relabel another
        storyboard's scenes.
        """
        if not assignments:
            return
        for row_id, scene_id in assignments.items():
            await self.db.execute(
                update(Scene)
                .where(Scene.id == row_id, Scene.storyboard_id == storyboard_id)
                .values(scene_id=scene_id)
            )
        await self.db.commit()
