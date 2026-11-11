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

"""Data Transfer Objects for Agent Controller Endpoints."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from src.projects.dto.project_dto import StoryboardResponse


# --- Sub-components for Chat ---
class InlineDataRecord(BaseModel):
    mimeType: str
    data: str


class FileDataRecord(BaseModel):
    mimeType: str
    fileUri: str


class SourceMediaItemLinkDto(BaseModel):
    mediaItemId: int
    mediaIndex: int
    role: str


class ChatMessagePart(BaseModel):
    model_config = {"extra": "allow"}

    text: Optional[str] = None
    inlineData: Optional[InlineDataRecord] = None
    fileData: Optional[FileDataRecord] = None
    # For communicating specific source assets to the UI
    sourceAssetId: Optional[int] = None
    sourceMediaItem: Optional[SourceMediaItemLinkDto] = None
    # Function calls / responses for approval gates and tools
    function_response: Optional[Dict[str, Any]] = None
    functionResponse: Optional[Dict[str, Any]] = None
    function_call: Optional[Dict[str, Any]] = None
    functionCall: Optional[Dict[str, Any]] = None


class ChatMessage(BaseModel):
    role: str
    parts: List[ChatMessagePart]


# --- POST /chat ---
class ChatRequestDto(BaseModel):
    """Payload for starting an agent chat interaction."""

    sessionId: str
    workspaceId: int
    appName: Optional[str] = "ads_x"
    newMessage: Optional[ChatMessage] = None
    streaming: Optional[bool] = False


class ChatResponseDto(BaseModel):
    status: str


# --- GET /sessions/poll ---
class PollEventsResponseDto(BaseModel):
    """Response containing an array of raw SSE string chunks."""

    events: List[str]


# --- Session Responses ---
class SessionResponseDto(BaseModel):
    """A chat as listed: its agent session plus Creative Studio's registry."""

    id: str
    appName: str
    userId: str
    lastUpdateTime: Optional[float] = None
    state: Optional[Dict[str, Any]] = None
    events: Optional[List[Any]] = None
    # From Creative Studio's session registry (``agent_sessions``), not from
    # Agent Engine: the chat's project and its server-side title.
    projectId: Optional[int] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    # A registered chat the agent backend no longer has (expired, or its
    # local store was reset): listed on request. It cannot be opened, only
    # restored when ``restorable``.
    expired: bool = False
    # An expired chat that still owns a storyboard: it can be restored.
    restorable: bool = False
    # A chat restored after it expired: Izumi does not remember it, so it
    # cannot run there (its storyboard and timeline are edited by hand).
    restored: bool = False


# --- PATCH /sessions/{session_id} ---
class UpdateSessionRequestDto(BaseModel):
    """Server-side chat title and summary (they replace localStorage topics)."""

    title: Optional[str] = Field(default=None, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=1000)


# --- Any dynamic structure fallback (for passthrough) ---
# When proxying directly from Izumi Agent without strict deserialization
# but enforcing a standard response shape.
class ProxyResponseDto(BaseModel):
    status: Optional[str] = None
    details: Optional[Any] = None


class SessionDetailResponseDto(BaseModel):
    session: Optional[SessionResponseDto] = None
    storyboard: Optional[StoryboardResponse] = None


# --- PUT / DELETE /sessions/{session_id}/character ---
class CharacterProfileDto(BaseModel):
    """Structured description of the campaign's on-screen character.

    Stored verbatim under ``virtual_creator_metadata.profile`` and compiled
    into the free-text fields the agent reads (see ``character_state.py``).
    """

    name: Optional[str] = None
    role: Optional[
        Literal["creator", "reviewer", "spokesperson", "product_user"]
    ] = None
    gender: Optional[str] = None
    ageRange: Optional[str] = None
    appearance: Optional[str] = None
    clothing: Optional[str] = None
    personality: Optional[str] = None

    def to_state(self) -> Dict[str, Any]:
        """snake_case keys, matching the rest of the agent's session state."""
        return {
            "name": self.name,
            "role": self.role,
            "gender": self.gender,
            "age_range": self.ageRange,
            "appearance": self.appearance,
            "clothing": self.clothing,
            "personality": self.personality,
        }


class CharacterAssetRefDto(BaseModel):
    """A Creative Studio image to use as the character's headshot."""

    id: int
    assetType: Literal["generated", "uploaded"]


class UpdateCharacterRequestDto(BaseModel):
    workspaceId: int
    appName: Optional[str] = "ads_x"
    profile: CharacterProfileDto = CharacterProfileDto()
    # Replaces the headshot when present; otherwise the current one is kept.
    assetRef: Optional[CharacterAssetRefDto] = None
    # The prompt the headshot was generated from (kept for provenance only).
    prompt: Optional[str] = None


class CharacterStateResponseDto(BaseModel):
    """The session-state keys rewritten by the request (a full replacement
    of each key, ready to be merged into the UI's campaign state)."""

    state: Dict[str, Any]
