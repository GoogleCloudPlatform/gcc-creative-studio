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
"""Repository for interacting with AgentChatEvent models."""

import logging
from typing import List, Sequence
from fastapi import Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.agents.agent_chat_event_model import AgentChatEvent

logger = logging.getLogger(__name__)


class AgentRepository:
    """Repository for handling AgentChatEvent database operations."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add_chat_event(
        self, user_id: str, session_id: str, payload: dict
    ) -> AgentChatEvent:
        """Add a new chat event to the database."""
        event = AgentChatEvent(
            user_id=user_id,
            session_id=session_id,
            payload=payload,
        )
        self.db.add(event)
        await self.db.commit()
        return event

    async def get_pending_events(
        self, session_id: str, user_id: str
    ) -> Sequence[AgentChatEvent]:
        """Get all pending events for a session and user, ordered by ID."""
        stmt = (
            select(AgentChatEvent)
            .where(
                AgentChatEvent.session_id == session_id,
                AgentChatEvent.user_id == user_id,
            )
            .order_by(AgentChatEvent.id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def delete_events(self, event_ids: List[int]) -> None:
        """Delete multiple events by their IDs."""
        if not event_ids:
            return
        delete_stmt = delete(AgentChatEvent).where(
            AgentChatEvent.id.in_(event_ids)
        )
        await self.db.execute(delete_stmt)
        await self.db.commit()
