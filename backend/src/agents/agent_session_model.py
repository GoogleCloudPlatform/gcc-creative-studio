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
"""SQLAlchemy model for Creative Studio's registry of agent chat sessions."""

import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class AgentSession(Base):
    """Maps an agent chat session to its project and stores the chat title.

    The conversation itself lives in Vertex AI Agent Engine (or in the local
    Izumi container). This row is Creative Studio's own record of it:

    - It places the chat in a project. ``ProjectService`` uses it to find the
      project of the storyboards and timelines Izumi saves, because Izumi only
      ever sends ``session_id``.
    - It holds the server-side chat title, which used to live in the
      browser's ``izumi_topics`` localStorage.

    Izumi never reads it. The class is named ``AgentSession`` so it is never
    confused with SQLAlchemy's ``Session``.
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_agent_sessions_session_id"),
        Index("ix_agent_sessions_user_workspace", "user_id", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    app_name: Mapped[str] = mapped_column(
        String, nullable=False, default="ads_x", server_default="ads_x"
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Last chat activity, set by ``AgentService.chat``. It picks the chat a
    # project resumes when it is entered.
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the chat's expired agent session was re-created ("restored").
    # Izumi has no memory of the conversation, so ``AgentService.chat``
    # refuses to run it there and the agent never reuses its storyboard.
    restored_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
