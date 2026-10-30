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
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db

from src.agents.agent_session_model import AgentSession
from src.projects.schema.project_model import (
    DEFAULT_PROJECT_NAME,
    Project,
    Storyboard,
    Scene,
)
from src.workbench.schema.timeline_model import Timeline, VideoClip, AudioClip
from src.projects.dto.project_dto import (
    ProjectResponse,
    StoryboardResponse,
    StoryboardCreateResponse,
    SceneDTO,
)


class ProjectRepository(BaseRepository[Project, ProjectResponse]):
    """Handles database operations for Project objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=Project, schema=ProjectResponse, db=db)

    def _summary_query(self):
        """Projects with their chat count, latest chat and latest manual cut.

        Correlated scalar subqueries keep it to a single round trip.
        """
        session_count = (
            select(func.count(AgentSession.id))
            .where(AgentSession.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        latest_session_id = (
            select(AgentSession.session_id)
            .where(AgentSession.project_id == Project.id)
            .order_by(
                AgentSession.last_used_at.desc().nulls_last(),
                AgentSession.created_at.desc(),
                AgentSession.id.desc(),
            )
            .limit(1)
            .correlate(Project)
            .scalar_subquery()
        )
        latest_timeline_id = (
            select(func.max(Timeline.id))
            .where(
                Timeline.project_id == Project.id,
                Timeline.storyboard_id.is_(None),
            )
            .correlate(Project)
            .scalar_subquery()
        )
        return select(
            Project, session_count, latest_session_id, latest_timeline_id
        )

    @staticmethod
    def _to_response(row) -> ProjectResponse:
        project, session_count, latest_session_id, latest_timeline_id = row
        response = ProjectResponse.model_validate(project)
        response.session_count = int(session_count or 0)
        response.latest_session_id = latest_session_id
        response.latest_timeline_id = latest_timeline_id
        return response

    async def list_for_owner(
        self, workspace_id: int, owner_id: int
    ) -> list[ProjectResponse]:
        """A user's projects in a workspace: the default first, then by name."""
        query = (
            self._summary_query()
            .where(
                Project.workspace_id == workspace_id,
                Project.owner_id == owner_id,
            )
            .order_by(
                Project.is_default.desc(), func.lower(Project.name), Project.id
            )
        )
        result = await self.db.execute(query)
        return [self._to_response(row) for row in result.all()]

    async def get_summary(self, project_id: int) -> ProjectResponse | None:
        result = await self.db.execute(
            self._summary_query().where(Project.id == project_id)
        )
        row = result.first()
        return self._to_response(row) if row else None

    async def create_project(
        self, workspace_id: int, owner_id: int, name: str
    ) -> ProjectResponse:
        project = Project(
            workspace_id=workspace_id,
            owner_id=owner_id,
            name=name,
            is_default=False,
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return ProjectResponse.model_validate(project)

    async def ensure_default(
        self, workspace_id: int, owner_id: int
    ) -> ProjectResponse:
        """The user's default project in a workspace, created on first use.

        Race-safe: concurrent callers (two tabs, an agent save) all end up on
        the single row allowed by ``uq_projects_default_per_owner``.
        """
        existing = await self._find_default(workspace_id, owner_id)
        if existing is not None:
            return ProjectResponse.model_validate(existing)
        await self.db.execute(
            pg_insert(Project)
            .values(
                workspace_id=workspace_id,
                owner_id=owner_id,
                name=DEFAULT_PROJECT_NAME,
                is_default=True,
            )
            .on_conflict_do_nothing()
        )
        await self.db.commit()
        created = await self._find_default(workspace_id, owner_id)
        if created is None:  # pragma: no cover - guaranteed by the index
            raise RuntimeError("Default project could not be created")
        return ProjectResponse.model_validate(created)

    async def _find_default(
        self, workspace_id: int, owner_id: int
    ) -> Project | None:
        result = await self.db.execute(
            select(Project).where(
                Project.workspace_id == workspace_id,
                Project.owner_id == owner_id,
                Project.is_default.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_timeline_project(
        self, timeline_id: int
    ) -> tuple[bool, int | None]:
        """``(exists, project_id)`` of a timeline (resolves deep links)."""
        result = await self.db.execute(
            select(Timeline.project_id).where(Timeline.id == timeline_id)
        )
        row = result.first()
        return (row is not None, row[0] if row else None)


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
        self,
        workspace_id: int,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> list[StoryboardResponse]:
        """Finds storyboards for a given workspace, optionally filtered by session.

        Newest first: callers that take ``[0]`` as "the" storyboard of a
        session must get the live one, not whichever row the planner
        happened to return first. ``user_id`` restricts the list to that
        owner's storyboards: callers acting for a user always pass it.
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
        if user_id is not None:
            query = query.where(self.model.user_id == user_id)
        result = await self.db.execute(query)
        items = result.scalars().all()
        return [self.schema.model_validate(item) for item in items]

    async def get_owner_and_project(
        self, storyboard_id: int
    ) -> tuple[int, int] | None:
        """``(user_id, project_id)`` of a storyboard, without loading children.

        ``get_by_id`` validates into ``StoryboardResponse``, which reads the
        ``scenes`` relationship, and that lazy load fails under async.
        """
        result = await self.db.execute(
            select(self.model.user_id, self.model.project_id).where(
                self.model.id == storyboard_id
            )
        )
        row = result.first()
        return (row[0], row[1]) if row else None

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

    async def session_ids_with_storyboards(
        self, user_id: int, session_ids: list[str]
    ) -> set[str]:
        """The given chats that own at least one of the user's storyboards."""
        if not session_ids:
            return set()
        result = await self.db.execute(
            select(self.model.session_id)
            .where(
                self.model.user_id == user_id,
                self.model.session_id.in_(session_ids),
            )
            .distinct()
        )
        return set(result.scalars().all())

    async def reassign_session(
        self, old_session_id: str, new_session_id: str, user_id: int
    ) -> int:
        """Moves the user's storyboards of a chat to the chat's new session id.

        Used when an expired chat is restored with a re-created session.
        Returns the number of storyboards moved.
        """
        result = await self.db.execute(
            update(self.model)
            .where(
                self.model.session_id == old_session_id,
                self.model.user_id == user_id,
            )
            .values(session_id=new_session_id)
        )
        await self.db.commit()
        return result.rowcount

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
