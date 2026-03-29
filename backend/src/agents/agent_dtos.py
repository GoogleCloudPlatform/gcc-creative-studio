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

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


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
    text: Optional[str] = None
    inlineData: Optional[InlineDataRecord] = None
    fileData: Optional[FileDataRecord] = None
    # For communicating specific source assets to the UI
    sourceAssetId: Optional[int] = None
    sourceMediaItem: Optional[SourceMediaItemLinkDto] = None


class ChatMessage(BaseModel):
    role: str
    parts: List[ChatMessagePart]


# --- POST /chat ---
class ChatRequestDto(BaseModel):
    """Payload for starting an agent chat interaction."""

    sessionId: str
    appName: Optional[str] = "creative_toolbox"
    workspaceId: Optional[int] = None
    newMessage: Optional[ChatMessage] = None
    streaming: Optional[bool] = False
    userId: Optional[str] = None


class ChatResponseDto(BaseModel):
    status: str


# --- GET /sessions/poll ---
class PollEventsResponseDto(BaseModel):
    """Response containing an array of raw SSE string chunks."""

    events: List[str]


# --- Session Responses ---
class SessionResponseDto(BaseModel):
    id: str
    appName: str
    userId: str
    lastUpdateTime: Optional[float] = None
    state: Optional[Dict[str, Any]] = None
    events: Optional[List[Any]] = None


# --- Any dynamic structure fallback (for passthrough) ---
# When proxying directly from Izumi Agent without strict deserialization
# but enforcing a standard response shape.
class ProxyResponseDto(BaseModel):
    status: Optional[str] = None
    details: Optional[Any] = None
