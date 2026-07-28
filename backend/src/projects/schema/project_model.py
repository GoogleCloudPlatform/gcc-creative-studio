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
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, String, DateTime, func, Table, Column, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base

if TYPE_CHECKING:
    from src.workspaces.schema.workspace_model import Workspace
    from src.workbench.schema.timeline_model import Timeline


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    thumbnail_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    thumbnail_source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship(back_populates="projects")
    storyboard: Mapped["Storyboard"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    timeline: Mapped["Timeline"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def storyboard_id(self) -> int | None:
        if hasattr(self, "_storyboard_id") and self._storyboard_id is not None:
            return self._storyboard_id
        from sqlalchemy import inspect

        insp = inspect(self)
        if insp is not None and "storyboard" in insp.unloaded:
            return None
        return self.storyboard.id if self.storyboard else None

    @storyboard_id.setter
    def storyboard_id(self, value):
        self._storyboard_id = value

    @property
    def timeline_id(self) -> int | None:
        if hasattr(self, "_timeline_id") and self._timeline_id is not None:
            return self._timeline_id
        from sqlalchemy import inspect

        insp = inspect(self)
        if insp is not None and "timeline" in insp.unloaded:
            return None
        return self.timeline.id if self.timeline else None

    @timeline_id.setter
    def timeline_id(self, value):
        self._timeline_id = value

    @property
    def session_id(self) -> str | None:
        from sqlalchemy import inspect

        insp = inspect(self)
        if insp is not None and "sessions" in insp.unloaded:
            return None
        if not self.sessions:
            return None
        # Sort by id descending to get the newest session
        sorted_sessions = sorted(
            self.sessions, key=lambda s: s.id, reverse=True
        )
        return sorted_sessions[0].session_id


class Storyboard(Base):
    __tablename__ = "storyboards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    template_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Background Music Prompt
    bg_music_description: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    bg_music_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), unique=True, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="storyboard")
    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="storyboard", cascade="all, delete-orphan"
    )
    timeline: Mapped["Timeline"] = relationship(
        back_populates="storyboard", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def timeline_id(self) -> int | None:
        return self.timeline.id if self.timeline else None

    @property
    def workspace_id(self) -> int | None:
        if hasattr(self, "_workspace_id") and self._workspace_id is not None:
            return self._workspace_id
        from sqlalchemy import inspect

        insp = inspect(self)
        if insp is not None and "project" in insp.unloaded:
            return None
        return self.project.workspace_id if self.project else None

    @workspace_id.setter
    def workspace_id(self, value):
        self._workspace_id = value


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    storyboard_id: Mapped[int] = mapped_column(
        ForeignKey("storyboards.id"), nullable=False
    )
    order: Mapped[int] = mapped_column(default=0, nullable=False)
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


# class Canvas(Base):
#     __tablename__ = "canvases"
#
#     id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
#     project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
#     title: Mapped[str | None] = mapped_column(String, nullable=True)
#     html_content: Mapped[str | None] = mapped_column(String, nullable=True)
#
#     project: Mapped["Project"] = relationship(back_populates="canvas")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="sessions")
