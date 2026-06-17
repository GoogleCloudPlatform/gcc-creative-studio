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

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import vertexai
from vertexai.preview import reasoning_engines
from google.cloud import aiplatform_v1beta1 as aip_types
from src.auth.auth_guard import RoleChecker, get_current_user
from src.database import get_db
from src.users.user_model import UserModel
from src.workspaces.workspace_service import WorkspaceService
from src.config.config_service import config_service
from src.agents.agent_chat_event_model import AgentChatEvent
from src.agents.agent_dtos import (
    ChatRequestDto,
    ChatResponseDto,
    PollEventsResponseDto,
    SessionResponseDto,
    SessionDetailResponseDto,
)
from src.projects.project_repository import StoryboardRepository
from src.images.repository.media_item_repository import MediaRepository
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.projects.project_service import ProjectService
from src.workspaces.workspace_auth_guard import WorkspaceAuth

router = APIRouter(
    prefix="/api/agent",
    tags=["Agent"],
)

logger = logging.getLogger(__name__)

# Initialize Vertex AI SDK
vertexai.init(
    project=config_service.PROJECT_ID,
    location=config_service.WORKFLOWS_LOCATION,
)

AGENT_REASONING_ENGINES = {
    "ads_x_template": {
        "resource_name": config_service.AGENT_ENGINE_RESOURCE_NAME,
        "token_key": config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY,
    }
}


def _get_agent_config(appName: str) -> dict:
    default_config = {
        "resource_name": config_service.AGENT_ENGINE_RESOURCE_NAME,
        "token_key": config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY,
    }
    return AGENT_REASONING_ENGINES.get(appName, default_config)


IZUMI_AGENT_URL = config_service.IZUMI_AGENT_URL
APP_NAME = "ads_x_template"


@router.get("/sessions", response_model=List[SessionResponseDto])
async def get_sessions(
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
):
    """List chat sessions for the current user from Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    try:
        agent_config = _get_agent_config(appName)
        remote_agent = reasoning_engines.ReasoningEngine(
            agent_config["resource_name"]
        )

        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        state = {}
        if workspace_id is not None:
            state["workspace_id"] = str(workspace_id)
        if token:
            state[agent_config["token_key"]] = token

        # sessions_data = remote_agent.list_sessions(user_id=user_id, state=state)
        sessions_data = remote_agent.list_sessions(user_id=user_id)

        sessions_list = []
        if isinstance(sessions_data, dict):
            sessions_list = sessions_data.get("sessions", [])
        elif isinstance(sessions_data, list):
            sessions_list = sessions_data

        res_sessions = []
        for s in sessions_list:
            s_dict = s if isinstance(s, dict) else {}
            res_sessions.append(
                SessionResponseDto(
                    id=s_dict.get("id")
                    or s_dict.get("name", "").split("/")[-1],
                    appName=appName,
                    userId=user_id,
                    state=s_dict.get("state", {}),
                    lastUpdateTime=s_dict.get("lastUpdateTime"),
                    events=s_dict.get("events", []),
                )
            )
        return res_sessions
    except Exception as e:
        logger.error(f"Unexpected error fetching sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions", response_model=SessionResponseDto)
async def create_session(
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
):
    """Create a new chat session in Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    try:
        agent_config = _get_agent_config(appName)
        remote_agent = reasoning_engines.ReasoningEngine(
            agent_config["resource_name"]
        )

        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        state = {}
        if workspace_id is not None:
            state["workspace_id"] = str(workspace_id)
        if token:
            state[agent_config["token_key"]] = token

        # session = remote_agent.create_session(user_id=user_id, state=state)
        session = remote_agent.create_session(user_id=user_id)

        session_dict = session if isinstance(session, dict) else {}
        return SessionResponseDto(
            id=session_dict.get("id"),
            appName=appName,
            userId=user_id,
            state=session_dict.get("state", {}),
        )
    except Exception as e:
        logger.error(f"Unexpected error creating session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/detail", response_model=SessionDetailResponseDto)
async def get_session_detail(
    workspace_id: int,
    request: Request,
    session_id: str | None = None,
    storyboard_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends(),
    workspace_auth: WorkspaceAuth = Depends(),
    project_service: ProjectService = Depends(),
):
    """Retrieve session messages (from Vertex AI) and associated storyboard (from DB) in a single request."""
    user_id = str(current_user.id)
    storyboard = None
    resolved_session_id = session_id

    await workspace_auth.authorize(
        workspace_id=workspace_id,
        user=current_user,
    )

    # 1. Retrieve and enrich storyboard if storyboard_id is provided
    if storyboard_id is not None:
        try:
            storyboard = await project_service.get_storyboard(storyboard_id)
        except Exception as e:
            logger.error(f"Error retrieving storyboard {storyboard_id}: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid storyboard ID: {storyboard_id}. The value is out of range for the database integer type.",
            )
        if not storyboard:
            raise HTTPException(status_code=404, detail="Storyboard not found")
        if storyboard.user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to access this storyboard",
            )
        if storyboard.session_id:
            resolved_session_id = storyboard.session_id

    # 2. Retrieve storyboard by workspace & session_id if storyboard_id was not provided
    elif resolved_session_id is not None:
        storyboards = await project_service.list_storyboards(
            workspace_id=workspace_id, session_id=resolved_session_id
        )
        if storyboards:
            storyboard = storyboards[0]

    # 3. Retrieve session messages from Vertex AI if we have a session_id
    session_dto = None
    if resolved_session_id is not None:
        try:
            agent_config = _get_agent_config(appName)
            remote_agent = reasoning_engines.ReasoningEngine(
                agent_config["resource_name"]
            )

            auth_header = request.headers.get("Authorization")
            token = None
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

            state = {}
            if workspace_id is not None:
                state["workspace_id"] = str(workspace_id)
            if token:
                state[agent_config["token_key"]] = token

            try:
                # session = remote_agent.get_session(
                #     session_id=resolved_session_id, user_id=user_id, state=state
                # )
                session = remote_agent.get_session(
                    session_id=resolved_session_id, user_id=user_id
                )
            except Exception as inner_e:
                if "Session not found" in str(inner_e):
                    logger.warning(
                        f"Session {resolved_session_id} not found on Vertex AI. Re-creating dynamic session."
                    )
                    # session = remote_agent.create_session(
                    #     user_id=user_id, state=state
                    # )
                    session = remote_agent.create_session(user_id=user_id)
                    new_session_id = (
                        session.get("id") if isinstance(session, dict) else None
                    )
                    if storyboard and new_session_id:
                        await storyboard_repo.update(
                            storyboard.id, {"session_id": new_session_id}
                        )
                        storyboard.session_id = new_session_id
                else:
                    raise inner_e

            session_dict = session if isinstance(session, dict) else {}
            session_dto = SessionResponseDto(
                id=session_dict.get("id"),
                appName=appName,
                userId=user_id,
                lastUpdateTime=session_dict.get("lastUpdateTime"),
                state=session_dict.get("state", {}),
                events=session_dict.get("events", []),
            )
        except Exception as e:
            logger.error(
                f"Unexpected error fetching session {resolved_session_id} details: {e}",
                exc_info=True,
            )

    if storyboard is None and resolved_session_id is None:
        raise HTTPException(
            status_code=400,
            detail="Either session_id or storyboard_id must be provided to query details.",
        )

    return SessionDetailResponseDto(session=session_dto, storyboard=storyboard)


@router.get("/sessions/{session_id}", response_model=SessionResponseDto)
async def get_session_messages(
    session_id: str,
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
):
    """Get messages for a specific session from Vertex AI Agent Engines."""
    user_id = str(current_user.id)
    try:
        agent_config = _get_agent_config(appName)
        remote_agent = reasoning_engines.ReasoningEngine(
            agent_config["resource_name"]
        )

        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        state = {}
        if workspace_id is not None:
            state["workspace_id"] = str(workspace_id)
        if token:
            state[agent_config["token_key"]] = token

        # session = remote_agent.get_session(
        #     session_id=session_id, user_id=user_id, state=state
        # )
        session = remote_agent.get_session(
            session_id=session_id, user_id=user_id
        )

        session_dict = session if isinstance(session, dict) else {}
        return SessionResponseDto(
            id=session_dict.get("id"),
            appName=appName,
            userId=user_id,
            lastUpdateTime=session_dict.get("lastUpdateTime"),
            state=session_dict.get("state", {}),
            events=session_dict.get("events", []),
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}", response_model=Any)
async def delete_session(
    session_id: str,
    request: Request,
    workspace_id: int | None = None,
    appName: str = APP_NAME,
    current_user: UserModel = Depends(get_current_user),
):
    """Deletes a specific session from Vertex AI Agent Engines."""
    user_id = str(current_user.id)

    try:
        agent_config = _get_agent_config(appName)
        remote_agent = reasoning_engines.ReasoningEngine(
            agent_config["resource_name"]
        )

        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        state = {}
        if workspace_id is not None:
            state["workspace_id"] = str(workspace_id)
        if token:
            state[agent_config["token_key"]] = token

        # remote_agent.delete_session(
        #     session_id=session_id, user_id=user_id, state=state
        # )
        remote_agent.delete_session(session_id=session_id, user_id=user_id)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Unexpected error deleting session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", response_model=ChatResponseDto)
async def chat(
    payload: ChatRequestDto,
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Start generation task for the Izumi agent."""
    user_id = str(current_user.id)
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    url = f"{IZUMI_AGENT_URL}/run_sse"

    # Convert strict Pydantic DTO to dict, excluding unset values
    body = payload.model_dump(exclude_unset=True)

    # Enforce correct userId and allow dynamic appName
    body["userId"] = user_id
    if "appName" not in body:
        body["appName"] = APP_NAME

    # Fetch fallback workspace if not passed
    if "workspaceId" not in body or body["workspaceId"] is None:
        workspaces = await workspace_service.list_workspaces_for_user(
            current_user
        )
        if workspaces:
            body["workspaceId"] = workspaces[0].id

    session_id = body.get("sessionId")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing sessionId")

    if "newMessage" in body:
        new_msg = body["newMessage"]
        if "parts" in new_msg and new_msg["parts"]:
            sanitized_parts = []
            attached_assets = []
            for p in new_msg["parts"]:
                if not isinstance(p, dict):
                    sanitized_parts.append(p)
                    continue
                # Extract and remove UI-specific asset fields to prevent 422 errors
                s_asset_id = p.pop("sourceAssetId", None)
                s_media = p.pop("sourceMediaItem", None)
                if s_asset_id is not None:
                    attached_assets.append(f"source_asset:{s_asset_id}")
                if s_media is not None:
                    media_id = s_media.get("mediaItemId")
                    attached_assets.append(f"media_item:{media_id}")
                if p:
                    sanitized_parts.append(p)
            injections = []
            workspace_id_final = body.get("workspaceId")
            if workspace_id_final:
                injections.append(
                    f"Use Workspace ID {workspace_id_final} for any tool calls that require a workspace_id"
                )
            if session_id:
                injections.append(
                    f"Use Session ID {session_id} for any tool calls that require a session_id"
                )
            if attached_assets:
                asset_list = "\n".join([f"- {aid}" for aid in attached_assets])
                injections.append(
                    f"The user has attached the following reference assets:\n{asset_list}\nUse the load_asset_and_save_as_artifact tool to load them if needed."
                )
            if injections:
                injection_str = (
                    "\n\n[System Note:\n" + "\n".join(injections) + "\n]"
                )
                # Find the first text part, or add one
                text_part_found = False
                for p in sanitized_parts:
                    if "text" in p:
                        p["text"] += injection_str
                        text_part_found = True
                        break
                if not text_part_found:
                    sanitized_parts.append({"text": injection_str})
            new_msg["parts"] = sanitized_parts

    # Internal background task function
    async def process_stream():
        from src.database import async_session_local

        async with async_session_local() as db_session:
            try:
                agent_config = _get_agent_config(body.get("appName"))
                remote_agent = reasoning_engines.ReasoningEngine(
                    agent_config["resource_name"]
                )

                agent_input = {"message": body.get("newMessage")}

                # Build request payload without run_config since appName/workspaceId are not permitted
                request = aip_types.StreamQueryReasoningEngineRequest(
                    name=remote_agent.resource_name,
                    class_method="stream_query",
                    input=agent_input,
                )

                # Fetch stream from Vertex AI client
                response_stream = remote_agent.execution_api_client.stream_query_reasoning_engine(
                    request=request
                )

                while True:
                    # Fetch next chunk with None sentinel to avoid StopIteration thread issues
                    chunk = await asyncio.to_thread(next, response_stream, None)
                    if chunk is None:
                        break

                    if hasattr(chunk, "data") and chunk.data:
                        data_str = chunk.data.decode("utf-8")
                        evt = AgentChatEvent(
                            user_id=user_id,
                            session_id=session_id,
                            payload={"raw": f"data: {data_str}\n\n"},
                        )
                        db_session.add(evt)
                        await db_session.commit()

                # Signal the frontend that the stream is complete
                done_evt = AgentChatEvent(
                    user_id=user_id,
                    session_id=session_id,
                    payload={"raw": "data: [DONE]\n\n"},
                )
                db_session.add(done_evt)
                await db_session.commit()

            except Exception as e:
                logger.error(
                    f"Error streaming from Vertex AI: {e}", exc_info=True
                )
                evt = AgentChatEvent(
                    user_id=user_id,
                    session_id=session_id,
                    payload={
                        "raw": f'data: {{"error": "Internal error streaming from agent: {str(e)}"}}\n\n'
                    },
                )
                db_session.add(evt)
                await db_session.commit()

    # Trigger background task and return immediately
    import asyncio

    asyncio.create_task(process_stream())

    return {"status": "processing"}


@router.get("/sessions/{session_id}/poll", response_model=PollEventsResponseDto)
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
        return PollEventsResponseDto(events=[])

    extracted_events = [evt.payload["raw"] for evt in events]

    # Delete the fetched events cleanly from the queue
    event_ids = [evt.id for evt in events]
    delete_stmt = delete(AgentChatEvent).where(AgentChatEvent.id.in_(event_ids))
    await db.execute(delete_stmt)
    await db.commit()

    return PollEventsResponseDto(events=extracted_events)
