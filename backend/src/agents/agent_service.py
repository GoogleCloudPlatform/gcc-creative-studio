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
"""Service for proxying requests to the Izumi GenMedia Agent."""

import asyncio
import logging
from typing import Any, List

from fastapi import Depends, HTTPException, Request

import vertexai
from vertexai import agent_engines

from src.config.config_service import config_service
from src.users.user_model import UserModel
from src.workspaces.workspace_service import WorkspaceService
from src.projects.project_repository import StoryboardRepository
from src.projects.project_service import ProjectService
from src.workspaces.workspace_auth_guard import WorkspaceAuth
from src.agents.agent_repository import AgentRepository
from src.agents.agent_dtos import (
    ChatRequestDto,
    SessionResponseDto,
    SessionDetailResponseDto,
    PollEventsResponseDto,
)
from src.database import async_session_local

logger = logging.getLogger(__name__)

# Initialize Vertex AI SDK
vertexai.init(
    project=config_service.PROJECT_ID,
    location=config_service.WORKFLOWS_LOCATION,
    api_transport="grpc",  # Options: "grpc" or "rest"
)

AGENT_REASONING_ENGINES = {
    "ads_x": {
        "resource_name": config_service.AGENT_ENGINE_RESOURCE_NAME,
        "token_key": config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY,
    }
}

APP_NAME = "ads_x"


def safe_cast(val, to_type, default=None):
    try:
        return to_type(val)
    except (ValueError, TypeError):
        return default


class AgentService:
    def __init__(
        self,
        agent_repo: AgentRepository = Depends(),
        workspace_service: WorkspaceService = Depends(),
        storyboard_repo: StoryboardRepository = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
        project_service: ProjectService = Depends(),
    ):
        self.agent_repo = agent_repo
        self.workspace_service = workspace_service
        self.storyboard_repo = storyboard_repo
        self.workspace_auth = workspace_auth
        self.project_service = project_service
        self.client = vertexai.Client(
            project=config_service.PROJECT_ID,
            location=config_service.WORKFLOWS_LOCATION,
        )

    def _get_agent_config(self, appName: str) -> dict:
        default_config = {
            "resource_name": config_service.AGENT_ENGINE_RESOURCE_NAME,
            "token_key": config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY,
        }
        return AGENT_REASONING_ENGINES.get(appName, default_config)

    def _get_remote_agent(self, appName: str = APP_NAME) -> Any:
        agent_config = self._get_agent_config(appName)
        agent_name = agent_config.get("resource_name")
        return agent_engines.get(agent_name)

    def _map_session_to_dto(
        self,
        session: Any,
        appName: str = APP_NAME,
        fallback_user_id: str | None = None,
        events: List[Any] | None = None,
    ) -> SessionResponseDto:

        def sanitize_serializable(data: Any) -> Any:
            if isinstance(data, dict):
                return {k: sanitize_serializable(v) for k, v in data.items()}
            elif isinstance(data, list):
                return [sanitize_serializable(x) for x in data]
            elif isinstance(data, bytes):
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return data.decode("latin-1")
            return data

        s_events = events if events is not None else []
        if not s_events and not isinstance(session, dict):
            s_events = getattr(session, "events", [])
        elif not s_events and isinstance(session, dict):
            s_events = session.get("events", [])

        s_events = s_events if isinstance(s_events, list) else []

        mapped_events = []
        for e in s_events:
            if hasattr(e, "model_dump"):
                try:
                    mapped_events.append(sanitize_serializable(e.model_dump()))
                except Exception:
                    mapped_events.append(str(e))
            elif hasattr(e, "to_dict"):
                try:
                    mapped_events.append(sanitize_serializable(e.to_dict()))
                except Exception:
                    mapped_events.append(str(e))
            elif isinstance(e, dict):
                mapped_events.append(sanitize_serializable(e))
            else:
                mapped_events.append(str(e))

        if isinstance(session, dict):
            s_state = session.get("session_state") or session.get("state", {})
            s_time = (
                session.get("update_time")
                or session.get("last_update_time")
                or session.get("lastUpdateTime")
            )
            if hasattr(s_time, "timestamp"):
                s_time = s_time.timestamp()
            return SessionResponseDto(
                id=str(
                    session.get("id")
                    or session.get("name", "").split("/")[-1]
                    or "s_1"
                ),
                appName=str(
                    session.get("app_name") or session.get("appName") or appName
                ),
                userId=str(
                    session.get("user_id")
                    or session.get("userId")
                    or fallback_user_id
                    or ""
                ),
                state=s_state if isinstance(s_state, dict) else {},
                lastUpdateTime=(
                    s_time if isinstance(s_time, (int, float)) else None
                ),
                events=mapped_events,
            )

        s_name = getattr(session, "name", None) or getattr(session, "id", None)
        s_id = (
            s_name.split("/")[-1]
            if isinstance(s_name, str)
            else str(s_name or "session_1")
        )

        s_app = getattr(session, "app_name", None) or getattr(
            session, "appName", None
        )
        s_app = str(s_app) if isinstance(s_app, str) else appName

        s_user = getattr(session, "user_id", None) or getattr(
            session, "userId", None
        )
        s_user = (
            str(s_user)
            if isinstance(s_user, (str, int))
            else (fallback_user_id or "")
        )

        s_state = getattr(session, "session_state", None) or getattr(
            session, "state", {}
        )
        s_state = s_state if isinstance(s_state, dict) else {}

        s_time = getattr(session, "update_time", None) or getattr(
            session, "last_update_time", None
        )
        if hasattr(s_time, "timestamp"):
            s_time = s_time.timestamp()

        return SessionResponseDto(
            id=s_id,
            appName=s_app,
            userId=s_user,
            state=s_state,
            lastUpdateTime=s_time if isinstance(s_time, (int, float)) else None,
            events=mapped_events,
        )

    async def list_sessions(
        self,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
    ) -> List[SessionResponseDto]:
        try:
            agent_config = self._get_agent_config(appName)
            agent_name = agent_config.get("resource_name")

            raw_sessions = self.client.agent_engines.sessions.list(
                name=agent_name
            )

            return [
                self._map_session_to_dto(s, appName, user_id)
                for s in raw_sessions
            ]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error fetching sessions: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def create_session(
        self,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
    ) -> SessionResponseDto:
        try:
            agent_config = self._get_agent_config(appName)
            agent_name = agent_config.get("resource_name")
            auth_header = request.headers.get("Authorization", "")
            auth_key = agent_config.get("token_key", "user_auth_token")

            state_data = {
                "workspace_id": workspace_id,
                auth_key: auth_header,
            }
            op = self.client.agent_engines.sessions.create(
                name=agent_name,
                user_id=user_id,
                config={"session_state": state_data},
            )
            session = getattr(op, "response", None) or op
            return self._map_session_to_dto(session, appName, user_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error creating session: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def get_session_detail(
        self,
        current_user: UserModel,
        workspace_id: int,
        request: Request,
        session_id: str | None = None,
        storyboard_id: int | None = None,
        appName: str = APP_NAME,
    ) -> SessionDetailResponseDto:
        user_id = str(current_user.id)
        storyboard = None
        resolved_session_id = session_id

        await self.workspace_auth.authorize(
            workspace_id=workspace_id,
            user=current_user,
        )

        if storyboard_id is not None:
            try:
                storyboard = await self.project_service.get_storyboard(
                    storyboard_id
                )
            except Exception as e:
                logger.error(
                    f"Error retrieving storyboard {storyboard_id}: {e}"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid storyboard ID: {storyboard_id}. The value is out of range for the database integer type.",
                )
            if not storyboard:
                raise HTTPException(
                    status_code=404, detail="Storyboard not found"
                )
            if storyboard.user_id != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to access this storyboard",
                )
            if storyboard.session_id:
                resolved_session_id = storyboard.session_id

        elif resolved_session_id is not None:
            storyboards = await self.project_service.list_storyboards(
                workspace_id=workspace_id, session_id=resolved_session_id
            )
            if storyboards:
                storyboard = storyboards[0]

        session_dto = None
        if resolved_session_id is not None:
            try:
                agent_config = self._get_agent_config(appName)
                agent_name = agent_config.get("resource_name")
                full_session_name = (
                    f"{agent_name}/sessions/{resolved_session_id}"
                )
                try:
                    session = self.client.agent_engines.sessions.get(
                        name=full_session_name
                    )

                    if session is None:
                        raise ValueError("Session not found")
                except Exception as inner_e:
                    if "Session not found" in str(inner_e) or "404" in str(
                        inner_e
                    ):
                        logger.warning(
                            f"Session {resolved_session_id} not found. Re-creating dynamic session."
                        )
                        auth_header = request.headers.get("Authorization", "")
                        auth_key = agent_config.get(
                            "token_key", "user_auth_token"
                        )
                        state_data = {
                            "workspace_id": workspace_id,
                            auth_key: auth_header,
                        }
                        op = self.client.agent_engines.sessions.create(
                            name=agent_name,
                            user_id=user_id,
                            config={"session_state": state_data},
                        )
                        session = getattr(op, "response", None) or op
                        new_session_id = (
                            getattr(session, "id", None)
                            if not isinstance(session, dict)
                            else session.get("id")
                        )
                        if storyboard and new_session_id:
                            await self.storyboard_repo.update(
                                storyboard.id, {"session_id": new_session_id}
                            )
                            storyboard.session_id = new_session_id
                    else:
                        raise inner_e

                events_list = []
                try:
                    events_list = list(
                        self.client.agent_engines.sessions.events.list(
                            name=full_session_name
                        )
                    )
                except Exception as e_err:
                    logger.warning(
                        f"Could not list session events for detail: {e_err}"
                    )

                session_dto = self._map_session_to_dto(
                    session, appName, user_id, events=events_list
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

        return SessionDetailResponseDto(
            session=session_dto, storyboard=storyboard
        )

    async def get_session_messages(
        self,
        session_id: str,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
    ) -> SessionResponseDto:
        try:
            agent_config = self._get_agent_config(appName)
            agent_name = agent_config.get("resource_name")
            full_session_name = f"{agent_name}/sessions/{session_id}"
            session = self.client.agent_engines.sessions.get(
                name=full_session_name
            )
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            events_list = []
            try:
                events_list = list(
                    self.client.agent_engines.sessions.events.list(
                        name=full_session_name
                    )
                )
            except Exception as e_err:
                logger.warning(
                    f"Could not list session events for messages: {e_err}"
                )

            return self._map_session_to_dto(
                session, appName, user_id, events=events_list
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error fetching messages: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_session(
        self,
        session_id: str,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
    ) -> dict:
        try:
            agent_config = self._get_agent_config(appName)
            agent_name = agent_config.get("resource_name")
            full_session_name = f"{agent_name}/sessions/{session_id}"
            self.client.agent_engines.sessions.delete(name=full_session_name)
            return {"status": "success"}
        except Exception as e:
            logger.error(
                f"Unexpected error deleting session: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def chat(
        self, user_id: str, payload: ChatRequestDto, request: Request
    ) -> dict:
        body = payload.model_dump(exclude_unset=True)
        if "appName" not in body:
            body["appName"] = APP_NAME

        session_id = body.get("sessionId")
        workspace_id = body.get("workspaceId")

        if "newMessage" in body:
            new_msg = body["newMessage"]
            if "parts" in new_msg and new_msg["parts"]:
                sanitized_parts = []
                attached_assets = []
                for p in new_msg["parts"]:
                    if not isinstance(p, dict):
                        sanitized_parts.append(p)
                        continue
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
                if workspace_id:
                    injections.append(
                        f"Use Workspace ID {workspace_id} for any tool calls that require a workspace_id"
                    )
                if session_id:
                    injections.append(
                        f"Use Session ID {session_id} for any tool calls that require a session_id"
                    )
                if attached_assets:
                    asset_list = "\n".join(
                        [f"- {aid}" for aid in attached_assets]
                    )
                    injections.append(
                        f"The user has attached the following reference assets:\n{asset_list}\nUse the load_asset_and_save_as_artifact tool to load them if needed."
                    )

                if injections:
                    injection_str = (
                        "\n\n[System Note:\n" + "\n".join(injections) + "\n]"
                    )
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
            try:
                import datetime

                app_name = body.get("appName") or APP_NAME
                remote_agent = self._get_remote_agent(app_name)
                agent_config = self._get_agent_config(app_name)
                auth_header = request.headers.get("Authorization", "")
                auth_key = agent_config.get("token_key", "user_auth_token")

                if session_id and auth_header:
                    agent_name = agent_config.get("resource_name")
                    full_session_name = f"{agent_name}/sessions/{session_id}"
                    try:
                        self.client.agent_engines.sessions.events.append(
                            name=full_session_name,
                            author="system",
                            invocation_id="token_propagation",
                            timestamp=datetime.datetime.now(
                                datetime.timezone.utc
                            ),
                            config={
                                "actions": {
                                    "state_delta": {auth_key: auth_header}
                                }
                            },
                        )
                    except Exception as upd_err:
                        logger.warning(
                            f"Could not append state delta event: {upd_err}"
                        )

                msg_payload = body.get("newMessage")

                response_stream = remote_agent.stream_query(
                    user_id=user_id,
                    session_id=session_id,
                    message=msg_payload,
                )
                import json

                print("1111111111111111111", response_stream)
                for chunk in response_stream:
                    print("00000000000000000", type(chunk))
                    print("222222222222222222", chunk)
                    if isinstance(chunk, str):
                        chunk_text = chunk
                        print("33333333333333333333", chunk_text)
                        print("4444444444444444444", type(chunk_text))
                    elif isinstance(chunk, dict):
                        chunk_text = json.dumps(chunk)
                        print("55555555555555555555", chunk_text)
                        print("6666666666666666666", type(chunk_text))
                    else:
                        try:
                            if hasattr(chunk, "model_dump"):
                                chunk_text = json.dumps(chunk.model_dump())
                                print("777777777777777777777", chunk_text)
                                print("888888888888888888888", type(chunk_text))
                            elif hasattr(chunk, "to_dict"):
                                chunk_text = json.dumps(chunk.to_dict())
                                print("9999999999999999999999", chunk_text)
                                print(
                                    "101010101010101010101010", type(chunk_text)
                                )
                            else:
                                chunk_text = json.dumps(str(chunk))
                                print("121212121212121212121212", chunk_text)
                                print(
                                    "13131313131131313131331", type(chunk_text)
                                )
                        except Exception:
                            print(
                                "1414141414141444141", chunk, type(chunk_text)
                            )
                            chunk_text = json.dumps(str(chunk))
                            print("15151515155151515151551", chunk_text)

                    async with async_session_local() as db_session:
                        repo = AgentRepository(db_session)
                        await repo.add_chat_event(
                            user_id=user_id,
                            session_id=session_id,
                            payload={"raw": f"data: {chunk_text}\n\n"},
                        )

                async with async_session_local() as db_session:
                    repo = AgentRepository(db_session)
                    await repo.add_chat_event(
                        user_id=user_id,
                        session_id=session_id,
                        payload={"raw": "data: [DONE]\n\n"},
                    )

            except ValueError as ve:
                if "Can only parse array of JSON objects" in str(ve):
                    logger.warning(
                        f"Transient REST streaming ValueError encountered (clean termination chunk issue): {ve}. Closing stream gracefully."
                    )
                    async with async_session_local() as db_session:
                        repo = AgentRepository(db_session)
                        await repo.add_chat_event(
                            user_id=user_id,
                            session_id=session_id,
                            payload={"raw": "data: [DONE]\n\n"},
                        )
                else:
                    logger.error(
                        f"ValueError during streaming: {ve}", exc_info=True
                    )
                    async with async_session_local() as db_session:
                        repo = AgentRepository(db_session)
                        await repo.add_chat_event(
                            user_id=user_id,
                            session_id=session_id,
                            payload={
                                "raw": f'data: {{"error": "ValueError: {str(ve)}"}}\n\n'
                            },
                        )
            except Exception as e:
                logger.error(
                    f"Error streaming from Agent Engine: {e}", exc_info=True
                )
                async with async_session_local() as db_session:
                    repo = AgentRepository(db_session)
                    await repo.add_chat_event(
                        user_id=user_id,
                        session_id=session_id,
                        payload={
                            "raw": f'data: {{"error": "Internal error streaming from agent: {str(e)}"}}\n\n'
                        },
                    )

        asyncio.create_task(process_stream())

        return {"status": "processing"}

    async def poll_session_events(
        self, session_id: str, current_user: UserModel
    ) -> PollEventsResponseDto:
        user_id = str(current_user.id)
        events = await self.agent_repo.get_pending_events(
            session_id=session_id, user_id=user_id
        )

        if not events:
            return PollEventsResponseDto(events=[])

        extracted_events = [evt.payload["raw"] for evt in events]
        event_ids = [evt.id for evt in events]

        await self.agent_repo.delete_events(event_ids=event_ids)

        return PollEventsResponseDto(events=extracted_events)
