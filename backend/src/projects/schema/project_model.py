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
from sqlalchemy import ForeignKey, String, DateTime, func, Table, Column, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base

# # Association table for project resources (MediaItems)
# project_media_items = Table(
#     "project_media_items",
#     Base.metadata,
#     Column("project_id", ForeignKey("projects.id"), primary_key=True),
#     Column("media_item_id", ForeignKey("media_items.id"), primary_key=True),
# )
#
# # Association table for project resources (SourceAssets)
# project_source_assets = Table(
#     "project_source_assets",
#     Base.metadata,
#     Column("project_id", ForeignKey("projects.id"), primary_key=True),
#     Column("source_asset_id", ForeignKey("source_assets.id"), primary_key=True),
# )

# class Project(Base):
#     __tablename__ = "projects"
#
#     id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
#     name: Mapped[str] = mapped_column(String, nullable=False)
#     user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
#     workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
#     created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
#     updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
#
#     # Relationships
#     storyboard: Mapped["Storyboard"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
#     canvas: Mapped["Canvas"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
#     timeline: Mapped["Timeline"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
#
#     # Resources
#     media_items: Mapped[list["MediaItem"]] = relationship(secondary=project_media_items)
#     source_assets: Mapped[list["SourceAsset"]] = relationship(secondary=project_source_assets)


class Storyboard(Base):
    __tablename__ = "storyboards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
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

    # project: Mapped["Project"] = relationship(back_populates="storyboard")
    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="storyboard", cascade="all, delete-orphan"
    )
    timeline: Mapped["Timeline"] = relationship(
        back_populates="storyboard", uselist=False, cascade="all, delete-orphan"
    )


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    storyboard_id: Mapped[int] = mapped_column(
        ForeignKey("storyboards.id"), nullable=False
    )
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


class Timeline(Base):
    __tablename__ = "timelines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    storyboard_id: Mapped[int] = mapped_column(
        ForeignKey("storyboards.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)

    storyboard: Mapped["Storyboard"] = relationship(back_populates="timeline")
    video_clips: Mapped[list["VideoClip"]] = relationship(
        back_populates="timeline", cascade="all, delete-orphan"
    )
    audio_clips: Mapped[list["AudioClip"]] = relationship(
        back_populates="timeline", cascade="all, delete-orphan"
    )


class VideoClip(Base):
    __tablename__ = "video_clips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timeline_id: Mapped[int] = mapped_column(
        ForeignKey("timelines.id"), nullable=False
    )
    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    trim_offset: Mapped[float] = mapped_column(Float, default=0.0)
    trim_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float] = mapped_column(Float, default=1.0)
    speed: Mapped[float] = mapped_column(Float, default=1.0)

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
    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id"), nullable=True
    )
    start_offset: Mapped[float] = mapped_column(Float, default=0.0)
    trim_offset: Mapped[float] = mapped_column(Float, default=0.0)
    trim_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float] = mapped_column(Float, default=1.0)

    timeline: Mapped["Timeline"] = relationship(back_populates="audio_clips")
