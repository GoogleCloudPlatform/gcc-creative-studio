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
"""Pydantic schemas and DTOs for workbench and timelines."""

from enum import Enum
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Clip(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    asset_id: str
    url: str
    start_time: float
    duration: float
    offset: float
    track_index: int
    type: Literal["video", "audio"]


class TimelineRequest(BaseModel):
    clips: list[Clip]
    output_format: str = "mp4"
    width: int | None = 1920
    height: int | None = 1080
    hide_video: bool = False


class RenderTimelineRequest(BaseModel):
    timeline_id: int | None = None
    output_filename: str | None = None


class RenderTimelineResponse(BaseModel):
    asset_id: int | str
    gcs_uri: str
    timeline_id: int
    message: str = "Timeline rendered successfully"


# --- Video Timeline NLE Models (with Relative Placements) ---


class TransitionType(str, Enum):
    FADE = "fade"
    NONE = "none"
    WIPE_LEFT = "wipe_left"
    WIPE_RIGHT = "wipe_right"


class AssetRef(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int | str
    type: Literal["source_asset", "media_item"]


class Trim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offset_seconds: float = 0.0
    duration_seconds: Optional[float] = None


class Transition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: TransitionType
    duration_seconds: float


class VideoClip(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_ref: Optional[AssetRef] = None
    trim: Optional[Trim] = None
    volume: float = 1.0
    speed: float = 1.0
    first_frame_asset_ref: Optional[AssetRef] = None
    last_frame_asset_ref: Optional[AssetRef] = None
    placeholder: Optional[str] = None
    presigned_url: Optional[str] = None
    presigned_thumbnail_url: Optional[str] = None


class AudioPlacement(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    video_clip_index: int
    offset_seconds: float = 0.0


class AudioClip(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_at: AudioPlacement
    asset_ref: Optional[AssetRef] = None
    trim: Optional[Trim] = None
    volume: float = 1.0
    speed: float = 1.0
    fade_in_duration_seconds: float = 0.0
    fade_out_duration_seconds: float = 0.0
    placeholder: Optional[str] = None
    presigned_url: Optional[str] = None


class VideoTimeline(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timeline_id: Optional[str | int] = None
    storyboard_id: Optional[str | int] = None
    workspace_id: str | int
    user_id: Optional[str | int] = None
    session_id: Optional[str] = None
    title: str
    video_clips: List[VideoClip] = []
    transitions: List[Optional[Transition]] = []
    audio_clips: List[AudioClip] = []
    transition_in: Optional[Transition] = None
    transition_out: Optional[Transition] = None


# Backwards compatibility aliases for previous tests/conventions
TimelineCreate = VideoTimeline
TimelineUpdate = VideoTimeline
TimelineResponse = VideoTimeline
