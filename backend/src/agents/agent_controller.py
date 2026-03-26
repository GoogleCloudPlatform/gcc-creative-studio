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
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.auth_guard import RoleChecker, get_current_user
from src.database import get_db
from src.users.user_model import UserModel
from src.workspaces.workspace_service import WorkspaceService
from src.agents.agent_chat_event_model import AgentChatEvent

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
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Start generation task for the Izumi agent."""
    user_id = str(current_user.id)
    url = f"{IZUMI_AGENT_URL}/run_sse"

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Enforce correct userId and appName
    body["userId"] = user_id
    body["appName"] = APP_NAME

    # Fetch fallback workspace if not passed
    if "workspaceId" not in body or body["workspaceId"] is None:
        workspaces = await workspace_service.list_workspaces_for_user(
            current_user
        )
        if workspaces:
            body["workspaceId"] = workspaces[0].id

    workspace_id_final = body.get("workspaceId")
    if workspace_id_final:
        # Prompt Injection to make model aware of Workspace ID
        if "newMessage" in body:
            new_msg = body["newMessage"]
            if "parts" in new_msg and new_msg["parts"]:
                part = new_msg["parts"][0]
                if isinstance(part, dict) and "text" in part:
                    part[
                        "text"
                    ] += f"\n\n[System Note: Use Workspace ID {workspace_id_final} for any tool calls that require a workspace_id]"

    session_id = body.get("sessionId")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing sessionId")

    headers = {
        "Authorization": request.headers.get("Authorization") or "",
        "Content-Type": "application/json",
    }

    # Internal background task function
    async def process_stream():
        import json
        from src.database import async_session_local

        async with async_session_local() as db_session:
            try:
                # Add a 10-minute timeout for the stream to account for long media generation
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST", url, json=body, headers=headers, timeout=600.0
                    ) as response:
                        if response.status_code != 200:
                            logger.error(
                                f"Izumi agent returned error: {response.status_code}"
                            )
                            evt = AgentChatEvent(
                                user_id=user_id,
                                session_id=session_id,
                                payload={
                                    "raw": f'data: {{"error": "Izumi agent error: {response.status_code}"}}\n\n'
                                },
                            )
                            db_session.add(evt)
                            await db_session.commit()
                            return

                        async for line in response.aiter_lines():
                            evt = AgentChatEvent(
                                user_id=user_id,
                                session_id=session_id,
                                payload=(
                                    {"raw": f"{line}\n"}
                                    if line
                                    else {"raw": "\n"}
                                ),
                            )
                            db_session.add(evt)
                            await db_session.commit()

            except httpx.ReadTimeout:
                logger.error("Timeout streaming from Izumi")
                evt = AgentChatEvent(
                    user_id=user_id,
                    session_id=session_id,
                    payload={
                        "raw": f'data: {{"error": "Timeout generating media"}}\n\n'
                    },
                )
                db_session.add(evt)
                await db_session.commit()
            except Exception as e:
                logger.error(f"Error streaming from Izumi: {e}")
                evt = AgentChatEvent(
                    user_id=user_id,
                    session_id=session_id,
                    payload={
                        "raw": f'data: {{"error": "Internal error streaming from agent"}}\n\n'
                    },
                )
                db_session.add(evt)
                await db_session.commit()

    # Trigger background task and return immediately
    import asyncio

    asyncio.create_task(process_stream())

    return {"status": "processing"}


@router.get("/sessions/{session_id}/poll")
async def poll_session_events(
    session_id: str,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all pending stream chunks for a chat session queue and mark them as consumed."""
    from sqlalchemy import select, delete

    user_id = str(current_user.id)

    # Select all pending events chronologically
    stmt = (
        select(AgentChatEvent)
        .where(
            AgentChatEvent.session_id == session_id,
            AgentChatEvent.user_id == user_id,
        )
        .order_by(AgentChatEvent.id.asc())
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    if not events:
        return {"events": []}

    extracted_events = [evt.payload["raw"] for evt in events]

    # Delete the fetched events cleanly from the queue
    event_ids = [evt.id for evt in events]
    delete_stmt = delete(AgentChatEvent).where(AgentChatEvent.id.in_(event_ids))
    await db.execute(delete_stmt)
    await db.commit()

    return {"events": extracted_events}
