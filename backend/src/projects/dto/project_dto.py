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

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List


# Scene DTO
class SceneDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    topic: Optional[str] = None
    duration_seconds: Optional[float] = None
    first_frame_description: Optional[str] = None
    first_frame_media_item_id: Optional[int] = None
    first_frame_source_asset_id: Optional[int] = None
    first_frame_generated_url: Optional[str] = None
    video_description: Optional[str] = None
    video_duration_seconds: Optional[float] = None
    video_media_item_id: Optional[int] = None
    video_source_asset_id: Optional[int] = None
    video_generated_url: Optional[str] = None
    voiceover_text: Optional[str] = None
    voiceover_gender: Optional[str] = None
    voiceover_description: Optional[str] = None
    voiceover_media_item_id: Optional[int] = None
    voiceover_source_asset_id: Optional[int] = None
    transition_type: Optional[str] = None
    transition_duration: Optional[float] = None
    audio_ambient_description: Optional[str] = None
    audio_sfx_description: Optional[str] = None


# Storyboard DTO
class StoryboardDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    session_id: Optional[str] = None
    template_name: Optional[str] = None
    bg_music_description: Optional[str] = None
    bg_music_asset_id: Optional[int] = None
    scenes: List[SceneDTO] = []


# Clip DTOs


# Canvas DTO
class CanvasDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str] = None
    html_content: Optional[str] = None


class StoryboardCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    workspace_id: int
    session_id: Optional[str] = None
    template_name: Optional[str] = None
    bg_music_description: Optional[str] = None
    bg_music_asset_id: Optional[int] = None


class StoryboardUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    template_name: Optional[str] = None
    bg_music_description: Optional[str] = None
    bg_music_asset_id: Optional[int] = None
    scenes: Optional[List[dict]] = None  # Simplified updates
    timeline_data: Optional[dict] = None  # Simplified updates
    storyboard: Optional[dict] = None


class StoryboardCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    workspace_id: int
    session_id: Optional[str] = None
    template_name: Optional[str] = None
    bg_music_description: Optional[str] = None
    bg_music_asset_id: Optional[int] = None


class StoryboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    workspace_id: int
    session_id: Optional[str] = None
    template_name: Optional[str] = None
    bg_music_description: Optional[str] = None
    bg_music_asset_id: Optional[int] = None

    scenes: List[SceneDTO] = []
    timeline_id: Optional[int] = None
