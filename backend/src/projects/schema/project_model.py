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

from datetime import datetime
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    DateTime,
    false,
    func,
    text,
    Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base

# Name of the project the backend creates on demand (see
# ``ProjectRepository.ensure_default``) and the migration backfills into.
DEFAULT_PROJECT_NAME = "Default project"


class Project(Base):
    """A user's container for Workbench work inside a workspace.

    A project groups its owner's agent chats (``agent_sessions``),
    storyboards and timelines, and only the owner can see it (see
    ``ProjectAuth``). There are deliberately no ORM relationships here:
    children are read with explicit queries, which avoids async lazy loads,
    and are removed by the database's ``ON DELETE CASCADE``.
    """

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_workspace_owner", "workspace_id", "owner_id"),
        # At most one default project per (workspace, owner). This keeps
        # "ensure the Default project" idempotent and race-safe.
        Index(
            "uq_projects_default_per_owner",
            "workspace_id",
            "owner_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Storyboard(Base):
    __tablename__ = "storyboards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    template_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Background Music Prompt
    bg_music_description: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    bg_music_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )

    # Ordered by the persisted position, then by id so legacy rows (all
    # written with ``order = 0``) still come back in insertion order.
    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="storyboard",
        cascade="all, delete-orphan",
        order_by="[Scene.order, Scene.id]",
    )
    timeline: Mapped["Timeline"] = relationship(
        back_populates="storyboard", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def timeline_id(self) -> int | None:
        return self.timeline.id if self.timeline else None


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    storyboard_id: Mapped[int] = mapped_column(
        ForeignKey("storyboards.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(default=0, nullable=False)
    # Izumi's stable scene identity (survives reorder); nullable for rows
    # written before the column existed or by clients that do not send it.
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # First Frame Prompt
    first_frame_description: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    first_frame_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    first_frame_source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    first_frame_generated_url: Mapped[str | None] = mapped_column(
        String, nullable=True
    )

    # Video Prompt
    video_description: Mapped[str | None] = mapped_column(String, nullable=True)
    video_duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    video_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    video_source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    video_generated_url: Mapped[str | None] = mapped_column(
        String, nullable=True
    )

    # Voiceover Prompt
    voiceover_text: Mapped[str | None] = mapped_column(String, nullable=True)
    voiceover_gender: Mapped[str | None] = mapped_column(String, nullable=True)
    voiceover_description: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    voiceover_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    voiceover_source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )

    # Hints
    transition_type: Mapped[str | None] = mapped_column(String, nullable=True)
    transition_duration: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    audio_ambient_description: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    audio_sfx_description: Mapped[str | None] = mapped_column(
        String, nullable=True
    )

    storyboard: Mapped["Storyboard"] = relationship(back_populates="scenes")
