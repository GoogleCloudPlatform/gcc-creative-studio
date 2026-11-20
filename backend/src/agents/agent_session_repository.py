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
"""Repository for Creative Studio's registry of agent chat sessions."""

import datetime
from typing import Iterable, Mapping

from fastapi import Depends
from sqlalchemy import DateTime, case, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.agent_session_model import AgentSession
from src.database import get_db

DEFAULT_APP_NAME = "ads_x"


class AgentSessionRepository:
    """Reads and writes ``agent_sessions``, the session -> project map.

    Rows are returned as ORM objects. The session factory uses
    ``expire_on_commit=False``, so they stay readable after a commit.
    """

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def get(self, session_id: str) -> AgentSession | None:
        result = await self.db.execute(
            select(AgentSession).where(AgentSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def register(
        self,
        session_id: str,
        project_id: int,
        user_id: int,
        workspace_id: int,
        app_name: str = DEFAULT_APP_NAME,
        restored: bool = False,
    ) -> AgentSession | None:
        """Records a freshly created chat in ``project_id``.

        Idempotent: an id that is already registered keeps its row (a session
        id never moves between projects implicitly). ``restored`` marks a
        re-created session of an expired chat (see ``restored_at``).
        """
        stmt = (
            pg_insert(AgentSession)
            .values(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                app_name=app_name or DEFAULT_APP_NAME,
                last_used_at=func.now(),
                restored_at=func.now() if restored else None,
            )
            .on_conflict_do_nothing(index_elements=["session_id"])
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return await self.get(session_id)

    async def adopt(
        self,
        session_ids: Iterable[str],
        project_id: int,
        user_id: int,
        workspace_id: int,
        app_name: str = DEFAULT_APP_NAME,
        last_used: Mapping[str, datetime.datetime] | None = None,
    ) -> None:
        """Registers chats Creative Studio has never seen, in one insert.

        These are chats created before projects existed, or through the ADK
        dev UI. Ids that are already registered are left untouched.
        ``last_used`` holds each chat's last activity as the agent backend
        reports it, so ``latest_session_id`` ranks adopted chats by recency.
        """
        unique_ids = list(dict.fromkeys(sid for sid in session_ids if sid))
        if not unique_ids:
            return
        activity = last_used or {}
        stmt = (
            pg_insert(AgentSession)
            .values(
                [
                    {
                        "session_id": sid,
                        "project_id": project_id,
                        "user_id": user_id,
                        "workspace_id": workspace_id,
                        "app_name": app_name or DEFAULT_APP_NAME,
                        "last_used_at": activity.get(sid),
                    }
                    for sid in unique_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["session_id"])
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def map_for_user_workspace(
        self, user_id: int, workspace_id: int
    ) -> dict[str, AgentSession]:
        """All of a user's registered chats in a workspace, keyed by id."""
        result = await self.db.execute(
            select(AgentSession).where(
                AgentSession.user_id == user_id,
                AgentSession.workspace_id == workspace_id,
            )
        )
        return {row.session_id: row for row in result.scalars().all()}

    async def app_names_for_project(self, project_id: int) -> dict[str, str]:
        """The project's chats as ``{session_id: app_name}``.

        Each chat lives in the agent it was created with, so deleting it
        needs that agent's name, not a default one.
        """
        result = await self.db.execute(
            select(AgentSession.session_id, AgentSession.app_name).where(
                AgentSession.project_id == project_id
            )
        )
        return {session_id: app_name for session_id, app_name in result.all()}

    async def update_metadata(
        self,
        session_id: str,
        title: str | None = None,
        summary: str | None = None,
    ) -> AgentSession | None:
        """Sets the chat title/summary; ``None`` leaves a field unchanged."""
        values: dict = {}
        if title is not None:
            values["title"] = title
        if summary is not None:
            values["summary"] = summary
        if values:
            await self.db.execute(
                update(AgentSession)
                .where(AgentSession.session_id == session_id)
                .values(**values)
            )
            await self.db.commit()
        row = await self.get(session_id)
        if row is not None and values:
            # A bulk UPDATE does not refresh an identity-mapped instance.
            await self.db.refresh(row)
        return row

    async def replace_session_id(
        self,
        old_session_id: str,
        new_session_id: str,
        user_id: int,
        restored: bool = True,
    ) -> bool:
        """Moves a registry row to a re-created session id (keeps the title).

        Only an expired chat gets a re-created session; with ``restored`` the
        row is marked restored (``restored_at``), and an earlier mark is
        never cleared. Returns False when ``old_session_id`` was not
        registered for the user.
        """
        values = {"session_id": new_session_id, "last_used_at": func.now()}
        if restored:
            values["restored_at"] = func.now()
        result = await self.db.execute(
            update(AgentSession)
            .where(
                AgentSession.session_id == old_session_id,
                AgentSession.user_id == user_id,
            )
            .values(**values)
        )
        await self.db.commit()
        return bool(result.rowcount)

    async def touch(self, session_id: str, user_id: int) -> None:
        """Marks chat activity (orders a project's chats; see the model).

        Scoped to the owner: callers run before the agent has validated the
        session id, so another user's chat must never be touched.
        """
        await self.db.execute(
            update(AgentSession)
            .where(
                AgentSession.session_id == session_id,
                AgentSession.user_id == user_id,
            )
            .values(last_used_at=func.now())
        )
        await self.db.commit()

    async def seed_last_used(
        self, user_id: int, last_used: Mapping[str, datetime.datetime]
    ) -> None:
        """Fills a missing ``last_used_at`` from the agent backend's activity.

        Rows the projects migration backfilled, or that were adopted without
        a time, have no recorded activity, so ``latest_session_id`` ranked
        them arbitrarily and could pick a chat that no longer exists. Only
        the user's own rows are written, and a recorded activity (``touch``,
        ``register``) is never overwritten.
        """
        if not last_used:
            return
        await self.db.execute(
            update(AgentSession)
            .where(
                AgentSession.user_id == user_id,
                AgentSession.session_id.in_(list(last_used)),
                AgentSession.last_used_at.is_(None),
            )
            .values(
                # Cast: Postgres cannot type bare CASE parameters as
                # timestamptz on its own.
                last_used_at=case(
                    {
                        session_id: cast(used_at, DateTime(timezone=True))
                        for session_id, used_at in last_used.items()
                    },
                    value=AgentSession.session_id,
                )
            )
            # Identity-mapped rows keep their loaded value: expiring them
            # would turn the next attribute read into implicit async IO.
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()

    async def delete(self, session_id: str) -> None:
        await self.db.execute(
            delete(AgentSession).where(AgentSession.session_id == session_id)
        )
        await self.db.commit()
