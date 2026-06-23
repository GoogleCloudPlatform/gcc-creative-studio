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
"""Controller for proxying requests to the Izumi GenMedia Agent."""

import logging
from typing import Any, List

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.agents.agent_service import AgentService
from src.agents.agent_dtos import (
    ChatRequestDto,
    ChatResponseDto,
    PollEventsResponseDto,
    SessionResponseDto,
    SessionDetailResponseDto,
)

router = APIRouter(
    prefix="/api/agent",
    tags=["Agent"],
)

logger = logging.getLogger(__name__)

APP_NAME = "ads_x"
security = HTTPBearer()


@router.get("/sessions", response_model=List[SessionResponseDto])
async def get_sessions(
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """List chat sessions for the current user from Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    return await agent_service.list_sessions(
        current_user=current_user,
        user_id=user_id,
        request=request,
        workspace_id=workspace_id,
        appName=appName,
    )


@router.post("/sessions", response_model=SessionResponseDto)
async def create_session(
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Create a new chat session in Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    return await agent_service.create_session(
        current_user=current_user,
        user_id=user_id,
        request=request,
        workspace_id=workspace_id,
        appName=appName,
    )


@router.get("/sessions/detail", response_model=SessionDetailResponseDto)
async def get_session_detail(
    workspace_id: int,
    request: Request,
    session_id: str | None = None,
    storyboard_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Retrieve session messages (from Vertex AI) and associated storyboard (from DB) in a single request."""
    return await agent_service.get_session_detail(
        current_user=current_user,
        workspace_id=workspace_id,
        request=request,
        session_id=session_id,
        storyboard_id=storyboard_id,
        appName=appName,
    )


@router.get("/sessions/{session_id}", response_model=SessionResponseDto)
async def get_session_messages(
    session_id: str,
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Get messages for a specific session from Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    return await agent_service.get_session_messages(
        current_user=current_user,
        session_id=session_id,
        user_id=user_id,
        request=request,
        workspace_id=workspace_id,
        appName=appName,
    )


@router.delete("/sessions/{session_id}", response_model=Any)
async def delete_session(
    session_id: str,
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Deletes a specific session from Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    return await agent_service.delete_session(
        current_user=current_user,
        session_id=session_id,
        user_id=user_id,
        request=request,
        workspace_id=workspace_id,
        appName=appName,
    )


@router.post("/chat", response_model=ChatResponseDto)
async def chat(
    payload: ChatRequestDto,
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Start generation task for the Izumi agent."""
    user_id = str(current_user.id)
    return await agent_service.chat(
        current_user=current_user,
        user_id=user_id,
        payload=payload,
        request=request,
    )


@router.get("/sessions/{session_id}/poll", response_model=PollEventsResponseDto)
async def poll_session_events(
    session_id: str,
    current_user: UserModel = Depends(get_current_user),
    agent_service: AgentService = Depends(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Retrieve all pending stream chunks for a chat session queue and mark them as consumed."""
    return await agent_service.poll_session_events(
        session_id=session_id, current_user=current_user
    )
