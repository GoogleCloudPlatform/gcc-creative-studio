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
"""SQLAlchemy database models for timeline and clips in workbench."""

from sqlalchemy import Float, ForeignKey, String, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base


class Timeline(Base):
    __tablename__ = "timelines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    storyboard_id: Mapped[int | None] = mapped_column(
        ForeignKey("storyboards.id"), nullable=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)

    transition_in_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    transition_in_duration: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    transition_out_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    transition_out_duration: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    project: Mapped["Project"] = relationship(
        "Project", back_populates="timelines"
    )
    storyboard: Mapped["Storyboard"] = relationship(
        "Storyboard", back_populates="timeline"
    )
    video_clips: Mapped[list["VideoClip"]] = relationship(
        back_populates="timeline", cascade="all, delete-orphan"
    )
    audio_clips: Mapped[list["AudioClip"]] = relationship(
        back_populates="timeline", cascade="all, delete-orphan"
    )

    @property
    def workspace_id(self) -> int | None:
        if hasattr(self, "_workspace_id") and self._workspace_id is not None:
            return self._workspace_id
        insp = inspect(self)
        if insp is not None and "project" in insp.unloaded:
            return None
        return self.project.workspace_id if self.project else None

    @workspace_id.setter
    def workspace_id(self, value):
        self._workspace_id = value


class VideoClip(Base):
    __tablename__ = "video_clips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timeline_id: Mapped[int] = mapped_column(
        ForeignKey("timelines.id"), nullable=False
    )
    clip_index: Mapped[int] = mapped_column(default=0, nullable=False)

    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    trim_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    trim_duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    volume: Mapped[float] = mapped_column(Float, default=1.0)
    speed: Mapped[float] = mapped_column(Float, default=1.0)

    first_frame_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    first_frame_source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    last_frame_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    last_frame_source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    placeholder: Mapped[str | None] = mapped_column(String, nullable=True)

    transition_to_next_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    transition_to_next_duration: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    timeline: Mapped["Timeline"] = relationship(back_populates="video_clips")

    @property
    def presigned_url(self) -> str | None:
        return getattr(self, "_presigned_url", None)

    @presigned_url.setter
    def presigned_url(self, value: str | None):
        self._presigned_url = value


class AudioClip(Base):
    __tablename__ = "audio_clips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timeline_id: Mapped[int] = mapped_column(
        ForeignKey("timelines.id"), nullable=False
    )
    clip_index: Mapped[int] = mapped_column(default=0, nullable=False)

    placement_video_clip_index: Mapped[int] = mapped_column(
        default=0, nullable=False
    )
    placement_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    trim_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    trim_duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    volume: Mapped[float] = mapped_column(Float, default=1.0)
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    fade_in_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    fade_out_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    placeholder: Mapped[str | None] = mapped_column(String, nullable=True)

    timeline: Mapped["Timeline"] = relationship(back_populates="audio_clips")

    @property
    def presigned_url(self) -> str | None:
        return getattr(self, "_presigned_url", None)

    @presigned_url.setter
    def presigned_url(self, value: str | None):
        self._presigned_url = value
