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
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db

from src.projects.schema.project_model import (
    Project,
    Storyboard,
    Scene,
    Session,
)
from src.workbench.schema.timeline_model import Timeline, VideoClip, AudioClip
from src.projects.dto.project_dto import (
    ProjectResponse,
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
                selectinload(self.model.project),
            )
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self.schema.model_validate(item)

    async def find_by_workspace(
        self,
        workspace_id: int,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> list[StoryboardResponse]:
        """Finds storyboards for a given workspace, optionally filtered by session."""
        query = (
            select(self.model)
            .join(Project)
            .where(Project.workspace_id == workspace_id)
            .options(
                selectinload(self.model.scenes),
                selectinload(self.model.timeline),
                selectinload(self.model.project),
            )
        )
        if session_id:
            query = query.join(Session).where(Session.session_id == session_id)
        if user_id is not None:
            query = query.where(self.model.user_id == user_id)
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]

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


class ProjectRepository(BaseRepository[Project, ProjectResponse]):
    """Handles database operations for Project objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Project, schema=ProjectResponse, db=db)

    async def get_by_id(
        self,
        item_id: int,
        include_deleted: bool = False,
    ) -> ProjectResponse | None:
        """Retrieves a single project by its ID, with storyboard and timeline loaded."""
        query = (
            select(self.model)
            .where(self.model.id == item_id)
            .options(
                selectinload(self.model.storyboard),
                selectinload(self.model.timeline),
            )
            .execution_options(include_deleted=include_deleted)
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self.schema.model_validate(item)

    async def get_project_by_params(
        self,
        project_id: int | None = None,
        session_id: str | None = None,
        storyboard_id: int | None = None,
        timeline_id: int | None = None,
        include_deleted: bool = False,
    ) -> ProjectResponse | None:
        """Retrieves a single project by any of the 4 params: project_id, session_id, storyboard_id, or timeline_id."""
        query = (
            select(self.model)
            .options(
                selectinload(self.model.storyboard),
                selectinload(self.model.timeline),
                selectinload(self.model.sessions),
            )
            .execution_options(include_deleted=include_deleted)
        )

        conditions = []
        if project_id is not None:
            conditions.append(self.model.id == project_id)

        if session_id is not None:
            query = query.outerjoin(Session).outerjoin(Timeline)
            conditions.append(
                (Session.session_id == session_id)
                | (Timeline.session_id == session_id)
            )

        if storyboard_id is not None:
            query = query.join(Storyboard, isouter=True)
            conditions.append(Storyboard.id == storyboard_id)

        if timeline_id is not None:
            query = query.join(Timeline, isouter=True)
            conditions.append(Timeline.id == timeline_id)

        if not conditions:
            return None

        query = query.where(or_(*conditions))
        result = await self.db.execute(query)
        item = result.scalars().first()
        if not item:
            return None
        return self.schema.model_validate(item)

    async def find_by_workspace_and_owner(
        self, workspace_id: int, owner_id: int
    ) -> list[ProjectResponse]:
        """Retrieves all projects in a specific workspace belonging to the owner."""
        query = (
            select(self.model)
            .where(
                self.model.workspace_id == workspace_id,
                self.model.owner_id == owner_id,
            )
            .options(
                selectinload(self.model.storyboard),
                selectinload(self.model.timeline),
                selectinload(self.model.sessions),
            )
        )
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]
