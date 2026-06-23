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
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel

router = APIRouter(
    prefix="/api/agent",
    tags=["Agent"],
)

logger = logging.getLogger(__name__)

IZUMI_AGENT_URL = "http://izumi-agent:8080"
APP_NAME = "creative_toolbox"


@router.get("/sessions")
async def get_sessions(current_user: UserModel = Depends(get_current_user)):
    """List chat sessions for the current user from Izumi agent."""
    user_id = str(current_user.id)
    url = f"{IZUMI_AGENT_URL}/apps/{APP_NAME}/users/{user_id}/sessions"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Error fetching sessions from Izumi: {e}")
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.text
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions")
async def create_session(current_user: UserModel = Depends(get_current_user)):
    """Create a new chat session in Izumi agent."""
    user_id = str(current_user.id)
    url = f"{IZUMI_AGENT_URL}/apps/{APP_NAME}/users/{user_id}/sessions"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Error creating session in Izumi: {e}")
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.text
        )
    except Exception as e:
        logger.error(f"Unexpected error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session_messages(
    session_id: str, current_user: UserModel = Depends(get_current_user)
):
    """Get messages for a specific session from Izumi agent."""
    user_id = str(current_user.id)
    url = f"{IZUMI_AGENT_URL}/apps/{APP_NAME}/users/{user_id}/sessions/{session_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Error fetching messages from Izumi: {e}")
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.text
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str, current_user: UserModel = Depends(get_current_user)
):
    """Deletes a specific session from Izumi agent."""
    user_id = str(current_user.id)
    url = f"{IZUMI_AGENT_URL}/apps/{APP_NAME}/users/{user_id}/sessions/{session_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Error deleting session from Izumi: {e}")
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.text
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat(
    request: Request, current_user: UserModel = Depends(get_current_user)
):
    """Send a message to Izumi agent and stream the response."""
    user_id = str(current_user.id)
    url = f"{IZUMI_AGENT_URL}/run_sse"

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Enforce correct userId and appName
    body["userId"] = user_id
    body["appName"] = APP_NAME

    async def generate():
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST", url, json=body, timeout=60.0
                ) as response:
                    if response.status_code != 200:
                        logger.error(
                            f"Izumi agent returned error: {response.status_code}"
                        )
                        yield f'data: {{"error": "Izumi agent error: {response.status_code}"}}\n\n'
                        return
                    async for line in response.aiter_lines():
                        if line:
                            yield f"{line}\n"
                        else:
                            yield "\n"
        except Exception as e:
            logger.error(f"Error streaming from Izumi: {e}")
            yield f'data: {{"error": "Internal error streaming from agent"}}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")
