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

from fastapi import status
import asyncio
import datetime
import json
import logging
import time
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
from src.agents.agent_session_repository import AgentSessionRepository
from src.agents.local_adk_client import LocalAdkAgentClient
from src.agents.agent_dtos import (
    ChatRequestDto,
    CharacterStateResponseDto,
    SessionResponseDto,
    SessionDetailResponseDto,
    PollEventsResponseDto,
    UpdateCharacterRequestDto,
)
from src.agents.character_state import (
    CharacterStateError,
    build_character_delta,
    build_character_removal_delta,
)
from src.agents.gate_state import (
    find_pending_gate,
    fold_text_into_gate,
    plain_text_of,
)
from src.agents.storyboard_state import (
    StoryboardStateError,
    build_storyboard_delta,
)
from src.projects.dto.project_dto import StoryboardResponse
from src.database import async_session_local

logger = logging.getLogger(__name__)

# Initialize Vertex AI SDK
vertexai.init(
    project=config_service.PROJECT_ID,
    location=config_service.AGENT_LOCATION,
    api_transport="grpc",  # Options: "grpc" or "rest"
)

AGENT_REASONING_ENGINES = {
    "ads_x": {
        "resource_name": config_service.AGENT_ENGINE_RESOURCE_NAME,
        "token_key": config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY,
    }
}

APP_NAME = "ads_x"

# One agent run per session at a time. The Izumi session service uses
# optimistic concurrency: a second ``/run_sse`` on a session whose previous
# run is still executing makes the older run's next ``append_event`` fail with
# "The last_update_time provided in the session object is stale", and the root
# router treats the new message as a fresh brief (re-extracts parameters,
# re-casts the virtual creator, re-opens the strategy gate). The run is an
# asyncio task of this process, so the registry is per process; a run living
# on another instance still surfaces through ``is_concurrent_run_error``.
ACTIVE_RUN_TTL_SECONDS = 30 * 60
AGENT_BUSY_DETAIL = (
    "Izumi is still working on the previous step in this conversation. "
    "Wait for it to finish before sending another message."
)
RESTORED_CHAT_DETAIL = (
    "This chat was restored after it expired: Izumi does not remember the "
    "conversation and cannot continue it. Start a new chat to work with Izumi."
)
BUSY_CHAT_DELETE_DETAIL = (
    "Izumi is still working in this chat. Wait for it to finish before "
    "deleting the chat."
)
_active_runs: dict[str, float] = {}


def _is_run_active(session_id: str) -> bool:
    """True while a run started by this process is still executing.

    The TTL only guards against a task that vanished without reaching its
    ``finally`` (e.g. event loop teardown); normal completion always clears
    the entry.
    """
    started = _active_runs.get(session_id)
    if started is None:
        return False
    if time.monotonic() - started > ACTIVE_RUN_TTL_SECONDS:
        _active_runs.pop(session_id, None)
        return False
    return True


def _mark_run_started(session_id: str) -> None:
    _active_runs[session_id] = time.monotonic()


def _mark_run_finished(session_id: str) -> None:
    _active_runs.pop(session_id, None)


def is_concurrent_run_error(message: str) -> bool:
    """Recognises the ADK session-service optimistic-concurrency failure.

    Local Izumi (``FirestoreSessionService``) and Agent Engine both reject an
    ``append_event`` whose session snapshot is older than the stored one with
    a "stale" ``last_update_time`` message.
    """
    lowered = (message or "").lower()
    return "stale" in lowered and (
        "last_update_time" in lowered or "session" in lowered
    )


# Pseudo resource name used for sessions when the agent runs in the local
# Izumi container (there is no Agent Engine resource to point at).
LOCAL_AGENT_NAME_PREFIX = "local-izumi-agent"

APPROVAL_FUNCTIONS = {
    "await_strategy_approval",
    "await_storyboard_approval",
    "await_frame_approval",
    "await_final_cut_approval",
}


def to_dict_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    return getattr(obj, "__dict__", obj)


def safe_cast(val, to_type, default=None):
    try:
        return to_type(val)
    except (ValueError, TypeError):
        return default


# Session-state keys holding the end user's bearer token: ``create_session``
# and ``chat`` store it so the agent can call Creative Studio on the user's
# behalf. It must never travel back to a browser.
_SECRET_STATE_KEYS = frozenset(
    {"user_auth_token", config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY}
)


def _without_secrets(values: dict) -> dict:
    """``values`` minus the bearer-token keys."""
    return {k: v for k, v in values.items() if k not in _SECRET_STATE_KEYS}


def _redact_event(event: Any) -> Any:
    """Drops the bearer token from an event's ``state_delta``/``stateDelta``.

    It reaches the event log through the token-propagation deltas
    (``_append_state_delta``) and the local ADK state PATCH.
    """
    if not isinstance(event, dict):
        return event
    actions = event.get("actions")
    if not isinstance(actions, dict):
        return event
    redacted = {
        key: (
            _without_secrets(value)
            if key in ("state_delta", "stateDelta") and isinstance(value, dict)
            else value
        )
        for key, value in actions.items()
    }
    return {**event, "actions": redacted}


def _session_owner_id(session: Any) -> str | None:
    """The user id the agent backend files a session under, if it has one."""
    if isinstance(session, dict):
        owner = session.get("user_id") or session.get("userId")
    else:
        owner = getattr(session, "user_id", None) or getattr(
            session, "userId", None
        )
    if isinstance(owner, bool) or not isinstance(owner, (str, int)):
        return None
    return str(owner) or None


def _is_session_not_found(error: Exception) -> bool:
    """True for the agent backend's "this session does not exist" errors.

    The status code decides when the error carries one (``google.genai``'s
    ``APIError`` and ``google.api_core``'s ``NotFound`` expose an int
    ``code``); the message is only the fallback for errors without one.
    That fallback never matches a bare "404": the local ADK client returns,
    rather than raises, on a 404, so in a code-less error those digits are a
    port (``:4040``), an id or a trace. Matching them would take an outage
    for a deleted session.
    """
    code = getattr(error, "code", None)
    if isinstance(code, int) and not isinstance(code, bool):
        return code == 404
    message = str(error).lower()
    return "not found" in message


def _listed_activity(
    sessions: List[SessionResponseDto],
) -> dict[str, datetime.datetime]:
    """Each listed chat's last activity, as the agent backend reports it.

    ``lastUpdateTime`` is in seconds (see ``_map_session_to_dto``). An
    unusable value is skipped: it must never fail the listing.
    """
    activity: dict[str, datetime.datetime] = {}
    for dto in sessions:
        seconds = dto.lastUpdateTime
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            continue
        try:
            activity[dto.id] = datetime.datetime.fromtimestamp(
                seconds, tz=datetime.timezone.utc
            )
        except (OverflowError, OSError, ValueError):
            continue
    return activity


# A project delete removes its chats this many at a time.
_SESSION_DELETE_CONCURRENCY = 4


class ForeignSessionError(HTTPException):
    """A chat filed under another user: always answered with a 403.

    A subclass, so the best-effort session-detail path (which logs and
    swallows most errors) can re-raise it.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this chat.",
        )


class AgentService:
    def __init__(
        self,
        agent_repo: AgentRepository = Depends(),
        workspace_service: WorkspaceService = Depends(),
        storyboard_repo: StoryboardRepository = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
        project_service: ProjectService = Depends(),
        agent_session_repo: AgentSessionRepository = Depends(),
    ):
        self.agent_repo = agent_repo
        self.workspace_service = workspace_service
        self.storyboard_repo = storyboard_repo
        self.workspace_auth = workspace_auth
        self.project_service = project_service
        self.agent_session_repo = agent_session_repo
        # ENVIRONMENT=local (or USE_LOCAL_IZUMI_AGENT=true) routes the agent
        # chat to the Izumi container started from
        # genmedia-izumi-agent/demos/backend/ads_x/docker-compose.yml.
        self.use_local_agent = config_service.IS_LOCAL_IZUMI_AGENT
        self.local_client: LocalAdkAgentClient | None = None
        if self.use_local_agent:
            self.local_client = LocalAdkAgentClient(
                config_service.IZUMI_AGENT_URL
            )
            logger.info(
                "AgentService using local Izumi agent at %s",
                config_service.IZUMI_AGENT_URL,
            )
        self.client = vertexai.Client(
            project=config_service.PROJECT_ID,
            location=config_service.AGENT_LOCATION,
        )

    @staticmethod
    def detect_approval_function(evt: Any) -> str | None:
        data = to_dict_safe(evt)
        if isinstance(data, dict):
            if data.get("author") == "user" or data.get("role") == "user":
                return None
            content = data.get("content")
            if isinstance(content, dict) and (
                content.get("role") == "user" or content.get("author") == "user"
            ):
                return None

        def search(obj: Any) -> str | None:
            if isinstance(obj, dict):
                fc = (
                    obj.get("function_call")
                    or obj.get("functionCall")
                    or obj.get("tool_call")
                    or obj.get("toolCall")
                )
                if isinstance(fc, dict):
                    name = fc.get("name")
                    if name in APPROVAL_FUNCTIONS:
                        return name

                fr = (
                    obj.get("function_response")
                    or obj.get("functionResponse")
                    or obj.get("tool_response")
                    or obj.get("toolResponse")
                )
                if isinstance(fr, dict):
                    name = fr.get("name")
                    resp = fr.get("response") or {}
                    if isinstance(resp, str):
                        try:
                            resp = json.loads(resp)
                        except Exception:
                            pass
                    res_dict = resp
                    if isinstance(resp, dict):
                        inner = resp.get("result")
                        if isinstance(inner, str):
                            try:
                                inner = json.loads(inner)
                            except Exception:
                                pass
                        if isinstance(inner, dict):
                            res_dict = inner
                    if isinstance(res_dict, dict) and not res_dict.get(
                        "decision"
                    ):
                        status = res_dict.get("status")
                        if (
                            status
                            in ("awaiting_human_review", "pending_approval")
                            or res_dict.get("message")
                            or res_dict.get("expected_response")
                        ):
                            if name in APPROVAL_FUNCTIONS:
                                return name

                for v in obj.values():
                    res = search(v)
                    if res:
                        return res
            elif isinstance(obj, list):
                for item in obj:
                    res = search(item)
                    if res:
                        return res
            return None

        if isinstance(data, (dict, list)):
            found = search(data)
            if found:
                return found

        return None

    def _get_agent_config(self, appName: str) -> dict:
        default_config = {
            "resource_name": config_service.AGENT_ENGINE_RESOURCE_NAME,
            "token_key": config_service.AGENT_ENGINE_USER_AUTH_TOKEN_KEY,
        }
        return AGENT_REASONING_ENGINES.get(appName, default_config)

    def _get_validated_agent_name(self, appName: str) -> str:
        agent_config = self._get_agent_config(appName)
        agent_name = agent_config.get("resource_name")
        if not agent_name:
            if self.use_local_agent:
                # No Agent Engine resource exists for the local container; the
                # name is only used to label sessions in logs.
                return f"{LOCAL_AGENT_NAME_PREFIX}/{appName}"
            logger.error(
                "Agent resource name is not configured for app %s.", appName
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent Engine Resource Name is not configured in the backend environment.",
            )
        return agent_name

    def _get_remote_agent(self, appName: str = APP_NAME) -> Any:
        if self.use_local_agent:
            return self.local_client.remote_agent(appName)
        vertexai.init(
            project=config_service.PROJECT_ID,
            location=config_service.AGENT_LOCATION,
            api_transport="grpc",
        )
        agent_name = self._get_validated_agent_name(appName)
        return agent_engines.get(agent_name)

    # --- Session backend helpers -------------------------------------------
    # Each helper hides whether sessions live in Vertex AI Agent Engine (the
    # default) or in the local Izumi container (ENVIRONMENT=local). The Vertex
    # branches are the original inline calls, kept verbatim, except that
    # ``_sessions_delete`` runs in a worker thread: a project delete issues
    # one per chat, and the Vertex client is synchronous.

    async def _sessions_list(
        self, agent_name: str, app_name: str, user_id: str
    ) -> Any:
        if self.use_local_agent:
            return await self.local_client.list_sessions(app_name, user_id)
        return self.client.agent_engines.sessions.list(
            name=agent_name, config={"filter": f'user_id="{user_id}"'}
        )

    async def _sessions_create(
        self, agent_name: str, app_name: str, user_id: str, state: dict
    ) -> Any:
        if self.use_local_agent:
            return await self.local_client.create_session(
                app_name, user_id, state
            )
        return self.client.agent_engines.sessions.create(
            name=agent_name,
            user_id=user_id,
            config={"session_state": state},
        )

    async def _sessions_get(
        self, agent_name: str, app_name: str, user_id: str, session_id: str
    ) -> Any:
        if self.use_local_agent:
            return await self.local_client.get_session(
                app_name, user_id, session_id
            )
        return self.client.agent_engines.sessions.get(
            name=f"{agent_name}/sessions/{session_id}"
        )

    async def _sessions_delete(
        self, agent_name: str, app_name: str, user_id: str, session_id: str
    ) -> None:
        if self.use_local_agent:
            await self.local_client.delete_session(
                app_name, user_id, session_id
            )
            return
        await asyncio.to_thread(
            self.client.agent_engines.sessions.delete,
            name=f"{agent_name}/sessions/{session_id}",
        )

    async def _events_list(
        self,
        agent_name: str,
        app_name: str,
        user_id: str,
        session_id: str,
        session: Any = None,
    ) -> list:
        if self.use_local_agent:
            # The ADK session payload already embeds its events; only refetch
            # when the caller did not hand us a session dict.
            if isinstance(session, dict) and "events" in session:
                return list(session.get("events") or [])
            fetched = await self.local_client.get_session(
                app_name, user_id, session_id
            )
            return list((fetched or {}).get("events") or [])
        return list(
            self.client.agent_engines.sessions.events.list(
                name=f"{agent_name}/sessions/{session_id}"
            )
        )

    async def _append_state_delta(
        self,
        agent_name: str,
        app_name: str,
        user_id: str,
        session_id: str,
        state_delta: dict,
    ) -> None:
        if self.use_local_agent:
            await self.local_client.update_session_state(
                app_name, user_id, session_id, state_delta
            )
            return
        self.client.agent_engines.sessions.events.append(
            name=f"{agent_name}/sessions/{session_id}",
            author="system",
            invocation_id="token_propagation",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            config={"actions": {"state_delta": state_delta}},
        )

    @staticmethod
    def _ensure_session_owner(session: Any, user_id: str) -> None:
        """Refuses a session the agent backend files under another user.

        Agent Engine addresses sessions as ``{agent}/sessions/{id}`` with no
        user scoping, so whoever knew an id could read another user's chat
        (state, events, the stored bearer token) or write into it. The local
        ADK API is user-scoped, so this never fires there.
        """
        owner = _session_owner_id(session)
        if owner is not None and owner != user_id:
            raise ForeignSessionError()

    async def _get_session_or_none(
        self, agent_name: str, app_name: str, user_id: str, session_id: str
    ) -> Any:
        """The session, or ``None`` when the agent backend does not know it.

        Any other failure raises: no authorization decision is taken on a
        session that could not be read.
        """
        try:
            return await self._sessions_get(
                agent_name, app_name, user_id, session_id
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            if _is_session_not_found(e):
                return None
            logger.error("Could not read session %s: %s", session_id, e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not verify the chat. Try again.",
            ) from e

    async def _ensure_chat_owner(
        self, app_name: str, user_id: str, session_id: str
    ) -> Any:
        """Refuses (403) to run a chat filed under another user.

        ``chat()`` appends the caller's bearer token to the session before
        the agent validates the run's user, and Agent Engine addresses
        ``{agent}/sessions/{id}`` with no user scoping: without this check,
        a known id let a caller plant their token in someone else's chat.
        The registry answers for every chat created or listed here (one
        indexed lookup); only an unregistered chat costs a session read. An
        unknown session passes: the run itself then fails. Returns the
        chat's registry row, or None for an unregistered chat.
        """
        row = await self.agent_session_repo.get(session_id)
        if row is not None:
            if str(row.user_id) != user_id:
                raise ForeignSessionError()
            return row
        agent_name = self._get_validated_agent_name(app_name)
        session = await self._get_session_or_none(
            agent_name, app_name, user_id, session_id
        )
        if session is not None:
            self._ensure_session_owner(session, user_id)
        return None

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
        mapped_events = [_redact_event(e) for e in mapped_events]

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
                state=(
                    _without_secrets(s_state)
                    if isinstance(s_state, dict)
                    else {}
                ),
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
        s_state = _without_secrets(s_state) if isinstance(s_state, dict) else {}

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
        current_user: UserModel,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
        project_id: int | None = None,
        include_expired: bool = False,
    ) -> List[SessionResponseDto]:
        try:
            if project_id is not None:
                # Owner-only: authorizes the project (and its workspace).
                project = await self.project_service.get_project(
                    current_user, project_id
                )
                if workspace_id is None:
                    workspace_id = project.workspace_id
                elif project.workspace_id != workspace_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="The project belongs to another workspace.",
                    )
            if workspace_id is not None:
                await self.workspace_auth.authorize(
                    workspace_id=workspace_id,
                    user=current_user,
                )

            agent_name = self._get_validated_agent_name(appName)

            raw_sessions = await self._sessions_list(
                agent_name, appName, user_id
            )

            mapped_sessions = []
            for s in raw_sessions:
                s_state = getattr(s, "session_state", None)
                if isinstance(s, dict):
                    s_state = s.get("session_state") or s_state

                s_workspace_id = None
                if isinstance(s_state, dict):
                    s_workspace_id = s_state.get("workspace_id")

                # Exclude sessions where workspace_id from state is null/missing
                if s_workspace_id is not None:
                    if workspace_id is not None:
                        if str(s_workspace_id) == str(workspace_id):
                            mapped_sessions.append(
                                self._map_session_to_dto(s, appName, user_id)
                            )
                    else:
                        mapped_sessions.append(
                            self._map_session_to_dto(s, appName, user_id)
                        )

            if workspace_id is not None:
                mapped_sessions = await self._apply_session_registry(
                    current_user,
                    workspace_id,
                    mapped_sessions,
                    project_id,
                    include_expired=include_expired,
                    app_name=appName,
                )
            return mapped_sessions
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error fetching sessions: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def create_session(
        self,
        current_user: UserModel,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
        project_id: int | None = None,
    ) -> SessionResponseDto:
        try:
            if workspace_id is not None:
                await self.workspace_auth.authorize(
                    workspace_id=workspace_id,
                    user=current_user,
                )

            # Pick the chat's project before creating the agent session, so a
            # refused project never leaves an orphan session behind.
            project = None
            if project_id is not None and workspace_id is None:
                project = await self.project_service.get_project(
                    current_user, project_id
                )
                workspace_id = project.workspace_id
            elif workspace_id is not None:
                project = await self.project_service.resolve_project_for_write(
                    current_user, workspace_id, project_id=project_id
                )

            agent_name = self._get_validated_agent_name(appName)
            agent_config = self._get_agent_config(appName)
            auth_header = request.headers.get("Authorization", "")
            auth_key = agent_config.get("token_key", "user_auth_token")

            state_data = {
                "workspace_id": workspace_id,
                auth_key: auth_header,
            }
            op = await self._sessions_create(
                agent_name, appName, user_id, state_data
            )
            session = getattr(op, "response", None) or op
            dto = self._map_session_to_dto(session, appName, user_id)
            if project is not None:
                row = await self.agent_session_repo.register(
                    dto.id, project.id, current_user.id, workspace_id, appName
                )
                if row is not None:
                    self._apply_registry_row(dto, row)
            return dto
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
                workspace_id=workspace_id,
                session_id=resolved_session_id,
                user_id=current_user.id,
            )
            if storyboards:
                storyboard = storyboards[0]

        session_dto = None
        if resolved_session_id is not None:
            try:
                agent_name = self._get_validated_agent_name(appName)
                try:
                    session = await self._sessions_get(
                        agent_name, appName, user_id, resolved_session_id
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
                        agent_config = self._get_agent_config(appName)
                        auth_key = agent_config.get(
                            "token_key", "user_auth_token"
                        )
                        state_data = {
                            "workspace_id": workspace_id,
                            auth_key: auth_header,
                        }
                        op = await self._sessions_create(
                            agent_name, appName, user_id, state_data
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
                        if new_session_id:
                            await self._register_recreated_session(
                                current_user,
                                workspace_id,
                                resolved_session_id,
                                new_session_id,
                                storyboard,
                                appName,
                            )
                            resolved_session_id = new_session_id
                    else:
                        raise inner_e

                # Owner-only chats: Agent Engine reads sessions by id alone.
                self._ensure_session_owner(session, user_id)

                events_list = []
                try:
                    events_list = await self._events_list(
                        agent_name,
                        appName,
                        user_id,
                        resolved_session_id,
                        session,
                    )
                except Exception as e_err:
                    logger.warning(
                        f"Could not list session events for detail: {e_err}"
                    )

                session_dto = self._map_session_to_dto(
                    session, appName, user_id, events=events_list
                )
                await self._attach_session_registry(current_user, session_dto)
            except Exception as e:
                # Refusing another user's chat is not a best-effort failure.
                if isinstance(e, ForeignSessionError):
                    raise
                logger.error(
                    f"Unexpected error fetching session {resolved_session_id} details: {e}",
                    exc_info=True,
                )

        if storyboard_id is None and session_dto is not None:
            storyboard = await self._prefer_session_storyboard(
                session_dto.state, storyboard, current_user
            )

        if storyboard is None and resolved_session_id is None:
            raise HTTPException(
                status_code=400,
                detail="Either session_id or storyboard_id must be provided to query details.",
            )

        return SessionDetailResponseDto(
            session=session_dto, storyboard=storyboard
        )

    async def _prefer_session_storyboard(
        self,
        state: Any,
        storyboard: StoryboardResponse | None,
        current_user: UserModel,
    ) -> StoryboardResponse | None:
        """Swaps in the storyboard the agent's state calls current.

        A session that restarted its pipeline before the create-or-reuse path
        existed owns several records; the newest row is a good guess, but
        ``current_storyboard_id`` is the one the agent renders and saves to.
        Falls back to ``storyboard`` on any problem.
        """
        if not isinstance(state, dict):
            return storyboard
        current_id = safe_cast(state.get("current_storyboard_id"), int)
        if current_id is None or (storyboard and storyboard.id == current_id):
            return storyboard
        try:
            candidate = await self.project_service.get_storyboard(current_id)
        except Exception as e:
            logger.warning(
                f"Could not load current_storyboard_id={current_id}: {e}"
            )
            return storyboard
        if candidate is None or candidate.user_id != current_user.id:
            return storyboard
        return candidate

    async def get_session_messages(
        self,
        current_user: UserModel,
        session_id: str,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
    ) -> SessionResponseDto:
        try:
            if workspace_id is not None:
                await self.workspace_auth.authorize(
                    workspace_id=workspace_id,
                    user=current_user,
                )

            agent_name = self._get_validated_agent_name(appName)
            session = await self._sessions_get(
                agent_name, appName, user_id, session_id
            )
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            # Owner-only chats: Agent Engine reads sessions by id alone.
            self._ensure_session_owner(session, user_id)

            # Extract workspace_id from session state and authorize
            s_state = getattr(session, "session_state", None)
            if isinstance(session, dict):
                s_state = session.get("session_state") or s_state

            s_workspace_id = None
            if isinstance(s_state, dict):
                s_workspace_id = s_state.get("workspace_id")

            if s_workspace_id is not None:
                await self.workspace_auth.authorize(
                    workspace_id=int(s_workspace_id),
                    user=current_user,
                )

            events_list = []
            try:
                events_list = await self._events_list(
                    agent_name, appName, user_id, session_id, session
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
        current_user: UserModel,
        session_id: str,
        user_id: str,
        request: Request,
        workspace_id: int | None = None,
        appName: str = APP_NAME,
    ) -> dict:
        try:
            if workspace_id is not None:
                await self.workspace_auth.authorize(
                    workspace_id=workspace_id,
                    user=current_user,
                )

            agent_name = self._get_validated_agent_name(appName)

            # Chats are owner-only: the registry knows who created this one.
            registry_row = await self.agent_session_repo.get(session_id)
            if (
                registry_row is not None
                and registry_row.user_id != current_user.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete this chat.",
                )

            # The session itself is checked too, and nothing is deleted after
            # a failed read: Agent Engine addresses sessions by id alone, so a
            # chat the registry does not know yet has no other owner check.
            session = await self._get_session_or_none(
                agent_name, appName, user_id, session_id
            )
            if session is None:
                if registry_row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Session not found",
                    )
            else:
                self._ensure_session_owner(session, user_id)
                s_state = getattr(session, "session_state", None)
                if isinstance(session, dict):
                    s_state = session.get("session_state") or s_state
                s_workspace_id = (
                    s_state.get("workspace_id")
                    if isinstance(s_state, dict)
                    else None
                )
                if s_workspace_id is not None:
                    await self.workspace_auth.authorize(
                        workspace_id=int(s_workspace_id),
                        user=current_user,
                    )
                # Deleting the session under a live run kills it at its next
                # append_event. Checked after the owner and workspace checks,
                # so a foreign chat still answers 403, and with no await
                # before the delete, so no run can start in between.
                if _is_run_active(session_id):
                    logger.warning(
                        "[Projects] Refusing to delete chat %s: a run is "
                        "still active",
                        session_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=BUSY_CHAT_DELETE_DETAIL,
                    )
                await self._sessions_delete(
                    agent_name, appName, user_id, session_id
                )
            # A chat already gone from the agent backend only loses its row.
            if registry_row is not None:
                await self.agent_session_repo.delete(session_id)
            return {"status": "success"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error deleting session: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

    # --- Session registry (projects) ---------------------------------------
    # ``agent_sessions`` maps every chat to a project and stores its title.
    # Agent Engine stays the source of truth for the conversation itself.

    @staticmethod
    def _apply_registry_row(
        dto: SessionResponseDto, row: Any
    ) -> SessionResponseDto:
        dto.projectId = row.project_id
        dto.title = row.title
        dto.summary = row.summary
        dto.restored = row.restored_at is not None
        return dto

    async def _apply_session_registry(
        self,
        current_user: UserModel,
        workspace_id: int,
        sessions: List[SessionResponseDto],
        project_id: int | None = None,
        include_expired: bool = False,
        app_name: str = APP_NAME,
    ) -> List[SessionResponseDto]:
        """Places every listed chat in a project and attaches its metadata.

        Chats Creative Studio has never registered (created before projects
        existed, or through the ADK dev UI) are adopted into the user's
        default project. Registry rows whose chat is missing from the
        listing are kept: a partial Agent Engine listing must never erase
        titles or project membership. A registered chat without recorded
        activity takes the listing's update time: it orders
        ``latest_session_id``, which otherwise picked an arbitrary chat
        (possibly one that no longer exists). ``project_id`` then narrows
        the result. With ``include_expired``, the kept rows of ``app_name``
        are appended as expired chats (see ``_expired_session_dtos``).
        """
        registry = await self.agent_session_repo.map_for_user_workspace(
            current_user.id, workspace_id
        )
        listed_activity = _listed_activity(sessions)
        orphans = [s.id for s in sessions if s.id not in registry]
        if orphans:
            default_project = (
                await self.project_service.resolve_project_for_write(
                    current_user, workspace_id
                )
            )
            await self.agent_session_repo.adopt(
                orphans,
                default_project.id,
                current_user.id,
                workspace_id,
                last_used=listed_activity,
            )
            registry = await self.agent_session_repo.map_for_user_workspace(
                current_user.id, workspace_id
            )
        unseeded = {
            session_id: used_at
            for session_id, used_at in listed_activity.items()
            if session_id in registry
            and registry[session_id].last_used_at is None
        }
        if unseeded:
            await self.agent_session_repo.seed_last_used(
                current_user.id, unseeded
            )
        result: List[SessionResponseDto] = []
        for dto in sessions:
            row = registry.get(dto.id)
            if row is None:
                # Registered under another workspace: unfiltered lists only.
                if project_id is None:
                    result.append(dto)
                continue
            if project_id is not None and row.project_id != project_id:
                continue
            result.append(self._apply_registry_row(dto, row))
        if include_expired:
            expired = self._expired_session_dtos(
                registry, sessions, project_id, app_name
            )
            if expired:
                # Only a chat that still owns a storyboard can be restored.
                restorable = (
                    await self.storyboard_repo.session_ids_with_storyboards(
                        current_user.id, [dto.id for dto in expired]
                    )
                )
                for dto in expired:
                    dto.restorable = dto.id in restorable
            result.extend(expired)
        return result

    @staticmethod
    def _expired_session_dtos(
        registry: dict[str, Any],
        listed: List[SessionResponseDto],
        project_id: int | None,
        app_name: str,
    ) -> List[SessionResponseDto]:
        """The registered chats the agent backend no longer has, newest first.

        Agent Engine sessions expire and a local Izumi store can be reset,
        while the chat's registry row (project, title, activity) survives.
        Only rows with recorded activity count: Creative Studio saw those
        chats alive. Rows without any are the dead ids the projects backfill
        took from old storyboards (chats deleted before projects existed),
        which must not come back. A chat deleted outside the Workbench after
        it was listed cannot be told apart and shows as expired too. Rows of
        another agent app belong to that app's listing.
        """
        listed_ids = {dto.id for dto in listed}
        rows = [
            row
            for session_id, row in registry.items()
            if session_id not in listed_ids
            and row.last_used_at is not None
            and (row.app_name or APP_NAME) == app_name
            and (project_id is None or row.project_id == project_id)
        ]
        rows.sort(key=lambda row: row.last_used_at, reverse=True)
        return [
            SessionResponseDto(
                id=row.session_id,
                appName=row.app_name or app_name,
                userId=str(row.user_id),
                lastUpdateTime=row.last_used_at.timestamp(),
                projectId=row.project_id,
                title=row.title,
                summary=row.summary,
                expired=True,
                restored=row.restored_at is not None,
            )
            for row in rows
        ]

    async def _attach_session_registry(
        self, current_user: UserModel, dto: SessionResponseDto
    ) -> None:
        """Best effort: the session detail must not fail over its metadata."""
        try:
            row = await self.agent_session_repo.get(dto.id)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[Projects] Could not read the registry for session %s: %s",
                dto.id,
                e,
            )
            return
        if row is not None and row.user_id == current_user.id:
            self._apply_registry_row(dto, row)

    async def _register_recreated_session(
        self,
        current_user: UserModel,
        workspace_id: int,
        old_session_id: str | None,
        new_session_id: str,
        storyboard: StoryboardResponse | None,
        app_name: str,
    ) -> None:
        """Keeps a chat the detail endpoint re-created in its project.

        A chat that comes back with a storyboard is marked restored: the new
        session has no memory of it, and an agent run would reuse, and
        overwrite, that storyboard. Without one there is nothing to protect.
        Best effort, like the recovery path that calls it.
        """
        restored = storyboard is not None
        try:
            if (
                old_session_id
                and await self.agent_session_repo.replace_session_id(
                    old_session_id,
                    new_session_id,
                    current_user.id,
                    restored=restored,
                )
            ):
                return
            project_id = storyboard.project_id if storyboard else None
            if project_id is None:
                project = await self.project_service.resolve_project_for_write(
                    current_user, workspace_id
                )
                project_id = project.id
            await self.agent_session_repo.register(
                new_session_id,
                project_id,
                current_user.id,
                workspace_id,
                app_name,
                restored=restored,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[Projects] Could not register re-created session %s: %s",
                new_session_id,
                e,
            )

    async def restore_session(
        self,
        current_user: UserModel,
        user_id: str,
        session_id: str,
        request: Request,
        workspace_id: int | None = None,
        app_name: str = APP_NAME,
    ) -> SessionResponseDto:
        """Restores an expired chat: the same chat on a new agent session.

        The chat's registry row (project, title) and its storyboards move to
        a re-created session, and the row is marked restored. Izumi has no
        memory of the conversation, so ``chat()`` refuses to run there: the
        storyboard and timeline are edited by hand, and no new agent run can
        reuse, and overwrite, them.

        Owner-only: 404 for an unknown chat, 409 while the agent still has
        the session or when the chat owns no storyboard (nothing to
        restore). Nothing is created before these checks pass. A concurrent
        restore that loses the race gets 409 and leaves nothing behind.
        """
        row = await self.agent_session_repo.get(session_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
            )
        if row.user_id != current_user.id:
            raise ForeignSessionError()
        if workspace_id is not None and row.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The chat belongs to another workspace.",
            )
        await self.workspace_auth.authorize(
            workspace_id=row.workspace_id, user=current_user
        )

        chat_app = row.app_name or app_name
        agent_name = self._get_validated_agent_name(chat_app)
        if (
            await self._get_session_or_none(
                agent_name, chat_app, user_id, session_id
            )
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This chat has not expired.",
            )
        owned = await self.storyboard_repo.session_ids_with_storyboards(
            current_user.id, [session_id]
        )
        if session_id not in owned:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This chat has no storyboard to restore.",
            )

        auth_key = self._get_agent_config(chat_app).get(
            "token_key", "user_auth_token"
        )
        state_data = {
            "workspace_id": row.workspace_id,
            auth_key: request.headers.get("Authorization", ""),
        }
        op = await self._sessions_create(
            agent_name, chat_app, user_id, state_data
        )
        session = getattr(op, "response", None) or op
        dto = self._map_session_to_dto(session, chat_app, user_id)
        # Moving the registry row claims the chat: a concurrent restore (a
        # double click) finds it gone and drops its own session.
        if not await self.agent_session_repo.replace_session_id(
            session_id, dto.id, current_user.id, restored=True
        ):
            await self.delete_sessions_best_effort(
                current_user, {dto.id: chat_app}
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This chat was already restored.",
            )
        await self.storyboard_repo.reassign_session(
            session_id, dto.id, current_user.id
        )
        # A fresh read: the bulk UPDATE expired the row's timestamps.
        restored_row = await self.agent_session_repo.get(dto.id)
        if restored_row is not None:
            self._apply_registry_row(dto, restored_row)
        logger.info(
            "[Projects] Restored expired chat %s as %s", session_id, dto.id
        )
        return dto

    async def update_session_metadata(
        self,
        current_user: UserModel,
        session_id: str,
        title: str | None = None,
        summary: str | None = None,
        app_name: str = APP_NAME,
    ) -> SessionResponseDto:
        """Sets a chat's server-side title/summary (owner only)."""
        row = await self.agent_session_repo.get(session_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
            )
        if row.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this chat.",
            )
        clean_title = title.strip() if title else None
        clean_summary = summary.strip() if summary else None
        updated = await self.agent_session_repo.update_metadata(
            session_id,
            title=clean_title or None,
            summary=clean_summary or None,
        )
        row = updated or row
        return SessionResponseDto(
            id=row.session_id,
            appName=row.app_name or app_name,
            userId=str(row.user_id),
            projectId=row.project_id,
            title=row.title,
            summary=row.summary,
            restored=row.restored_at is not None,
        )

    def ensure_sessions_idle(self, session_ids: List[str]) -> None:
        """409 while any of the chats has an agent run in progress.

        Used before deleting a project: removing a session under a live run
        kills the run mid-way. Same per-process registry as ``chat()``.
        """
        busy = [sid for sid in session_ids if _is_run_active(sid)]
        if busy:
            logger.warning(
                "[Projects] Refusing to delete chats %s: a run is still active",
                busy,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A chat in this project is still running. Wait for Izumi "
                    "to finish before deleting the project."
                ),
            )

    async def delete_sessions_best_effort(
        self,
        current_user: UserModel,
        sessions: dict[str, str],
    ) -> List[str]:
        """Deletes agent sessions, logging (never raising) individual failures.

        ``sessions`` maps each session id to the agent (``app_name``) that
        holds it. At most ``_SESSION_DELETE_CONCURRENCY`` deletes run at a
        time, off the event loop (see ``_sessions_delete``). Returns the ids
        that could not be deleted. A survivor is adopted into the default
        project on the next listing: a visible, harmless failure mode.
        """
        targets = {sid: app or APP_NAME for sid, app in sessions.items()}
        if not targets:
            return []
        agent_names: dict[str, str | None] = {}
        for app_name in set(targets.values()):
            try:
                agent_names[app_name] = self._get_validated_agent_name(app_name)
            except HTTPException as e:
                logger.warning(
                    "[Projects] Agent %s unavailable, its chats are not "
                    "deleted: %s",
                    app_name,
                    e.detail,
                )
                agent_names[app_name] = None
        user_id = str(current_user.id)
        limit = asyncio.Semaphore(_SESSION_DELETE_CONCURRENCY)

        async def delete(session_id: str, app_name: str) -> bool:
            agent_name = agent_names[app_name]
            if agent_name is None:
                return False
            async with limit:
                try:
                    await self._sessions_delete(
                        agent_name, app_name, user_id, session_id
                    )
                except Exception as e:  # pylint: disable=broad-exception-caught
                    if _is_session_not_found(e):
                        return True  # Already gone.
                    logger.warning(
                        "[Projects] Could not delete agent session %s: %s",
                        session_id,
                        e,
                    )
                    return False
            return True

        deleted = await asyncio.gather(
            *(delete(sid, app) for sid, app in targets.items())
        )
        return [sid for sid, ok in zip(targets, deleted) if not ok]

    # --- Characters tab -----------------------------------------------------

    def _ensure_session_idle(self, session_id: str) -> None:
        """Refuses a session-state write while a run is executing.

        Same registry as ``chat()``: the agent's session service keeps an
        optimistic lock on ``last_update_time``, so a write from here would
        make the live run's next ``append_event`` fail with the "stale"
        error and lose its work.
        """
        if _is_run_active(session_id):
            logger.warning(
                f"[Characters] Rejecting state write for session_id={session_id}: a run is still active"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=AGENT_BUSY_DETAIL,
            )

    async def _load_session_state(
        self,
        current_user: UserModel,
        agent_name: str,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict:
        """Fetches a session's state dict, authorising its workspace."""
        session = await self._sessions_get(
            agent_name, app_name, user_id, session_id
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        # Owner-only chats: Agent Engine reads sessions by id alone, and this
        # state is about to be rewritten (characters, storyboard sync).
        self._ensure_session_owner(session, user_id)
        if isinstance(session, dict):
            s_state = session.get("session_state") or session.get("state")
        else:
            s_state = getattr(session, "session_state", None) or getattr(
                session, "state", None
            )
        s_state = dict(s_state) if isinstance(s_state, dict) else {}
        s_workspace_id = s_state.get("workspace_id")
        if s_workspace_id is not None:
            await self.workspace_auth.authorize(
                workspace_id=int(s_workspace_id),
                user=current_user,
            )
        return s_state

    async def update_session_character(
        self,
        current_user: UserModel,
        user_id: str,
        session_id: str,
        payload: UpdateCharacterRequestDto,
    ) -> CharacterStateResponseDto:
        """Creates/edits the campaign's on-screen character in session state.

        Rewrites ``asset_refs`` / ``user_assets`` / ``virtual_creator_metadata``
        / ``parameters`` together (see ``character_state.py``) and returns the
        new values so the UI can merge them without a session reload.
        """
        try:
            app_name = payload.appName or APP_NAME
            await self.workspace_auth.authorize(
                workspace_id=payload.workspaceId, user=current_user
            )
            self._ensure_session_idle(session_id)
            agent_name = self._get_validated_agent_name(app_name)
            state = await self._load_session_state(
                current_user, agent_name, app_name, user_id, session_id
            )
            asset_ref = (
                {
                    "id": payload.assetRef.id,
                    "asset_type": payload.assetRef.assetType,
                }
                if payload.assetRef
                else None
            )
            try:
                delta = build_character_delta(
                    state,
                    profile=payload.profile.to_state(),
                    workspace_id=payload.workspaceId,
                    asset_ref=asset_ref,
                    prompt=payload.prompt,
                )
            except CharacterStateError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            await self._append_state_delta(
                agent_name, app_name, user_id, session_id, delta
            )
            logger.info(
                f"[Characters] Updated character for session_id={session_id} "
                f"(key={delta['virtual_creator_metadata'].get('file_name')}, "
                f"headshot_replaced={asset_ref is not None})"
            )
            return CharacterStateResponseDto(state=delta)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error updating session character: {e}",
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def remove_session_character(
        self,
        current_user: UserModel,
        user_id: str,
        session_id: str,
        workspace_id: int,
        app_name: str = APP_NAME,
    ) -> CharacterStateResponseDto:
        """Drops the character: the campaign becomes a product-only ad."""
        try:
            await self.workspace_auth.authorize(
                workspace_id=workspace_id, user=current_user
            )
            self._ensure_session_idle(session_id)
            agent_name = self._get_validated_agent_name(app_name)
            state = await self._load_session_state(
                current_user, agent_name, app_name, user_id, session_id
            )
            delta = build_character_removal_delta(state)
            await self._append_state_delta(
                agent_name, app_name, user_id, session_id, delta
            )
            logger.info(
                f"[Characters] Removed character for session_id={session_id}"
            )
            return CharacterStateResponseDto(state=delta)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error removing session character: {e}",
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(e))

    # --- Storyboard -> session sync ------------------------------------------

    async def sync_storyboard_to_session(
        self,
        current_user: UserModel,
        storyboard: StoryboardResponse,
        app_name: str = APP_NAME,
    ) -> dict:
        """Mirrors a human storyboard edit into the Izumi session state.

        Called after ``PUT /api/storyboards/{id}`` has persisted the record.
        Never raises: the record is already saved, so a busy agent or a
        missing session is reported in the returned ``status`` rather than
        failing the request. Statuses: ``synced``, ``skipped`` (no session or
        no storyboard in state yet), ``busy`` (a run is executing),
        ``rejected`` (the edit cannot be mirrored, e.g. no scenes) and
        ``failed``.
        """
        session_id = storyboard.session_id
        if not session_id:
            return {"status": "skipped", "detail": "Storyboard has no session."}
        user_id = str(current_user.id)
        try:
            if _is_run_active(session_id):
                return {"status": "busy", "detail": AGENT_BUSY_DETAIL}
            agent_name = self._get_validated_agent_name(app_name)
            state = await self._load_session_state(
                current_user, agent_name, app_name, user_id, session_id
            )
            try:
                result = build_storyboard_delta(
                    state, storyboard, storyboard.workspace_id
                )
            except StoryboardStateError as e:
                return {"status": "rejected", "detail": str(e)}
            if result is None:
                return {
                    "status": "skipped",
                    "detail": "The agent has not written a storyboard yet.",
                }
            delta, summary = result
            await self._append_state_delta(
                agent_name, app_name, user_id, session_id, delta
            )
            logger.info(
                f"[Storyboard sync] session_id={session_id} storyboard_id={storyboard.id} "
                f"summary={summary.as_dict()}"
            )
            return {"status": "synced", **summary.as_dict()}
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                return {"status": "skipped", "detail": "Session not found."}
            logger.warning(
                f"[Storyboard sync] session_id={session_id} rejected: {e.detail}"
            )
            return {"status": "failed", "detail": str(e.detail)}
        except Exception as e:
            logger.error(
                f"[Storyboard sync] session_id={session_id} failed: {e}",
                exc_info=True,
            )
            return {"status": "failed", "detail": str(e)}

    async def _fold_into_pending_gate(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        parts: list,
    ) -> dict | None:
        """Rewrites a plain-text turn as the reply to a suspended checkpoint.

        Returns the replacement message part, or ``None`` when the message
        should go through unchanged (not plain text, no pending gate, or the
        session could not be read -- never block the chat on this).
        """
        text = plain_text_of(parts)
        if not text:
            return None
        try:
            agent_name = self._get_validated_agent_name(app_name)
            session = await self._sessions_get(
                agent_name, app_name, user_id, session_id
            )
            if session is None:
                return None
            events = await self._events_list(
                agent_name, app_name, user_id, session_id, session
            )
            gate = find_pending_gate(events)
            if gate is None:
                return None
            part = fold_text_into_gate(text, gate)
            logger.info(
                f"[Gate] session_id={session_id}: typed reply folded into pending "
                f"{gate.tool_name} (call_id={gate.call_id}, "
                f"decision={part['function_response']['response']['decision']})"
            )
            return part
        except Exception as e:
            logger.warning(
                f"[Gate] session_id={session_id}: could not check pending gate: {e}"
            )
            return None

    async def chat(
        self,
        current_user: UserModel,
        user_id: str,
        payload: ChatRequestDto,
        request: Request,
    ) -> dict:
        body = payload.model_dump(exclude_unset=True)
        injections = []
        if "appName" not in body:
            body["appName"] = APP_NAME

        session_id = body.get("sessionId")
        workspace_id = body.get("workspaceId")

        if session_id:
            # First: nothing below may read the session or, in
            # ``process_stream``, write the caller's token into it.
            row = await self._ensure_chat_owner(
                body["appName"], user_id, session_id
            )
            # A restored chat has no agent memory: a run there would start a
            # new campaign that reuses, and overwrites, its storyboard.
            if row is not None and row.restored_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=RESTORED_CHAT_DETAIL,
                )

        if workspace_id is not None:
            injections.append(f"Active Workspace ID: {workspace_id}")
            await self.workspace_auth.authorize(
                workspace_id=workspace_id,
                user=current_user,
            )
        elif session_id is not None:
            try:
                agent_config = self._get_agent_config(body["appName"])
                agent_name = agent_config.get("resource_name")
                session = await self._sessions_get(
                    agent_name, body["appName"], user_id, session_id
                )
                if session:
                    s_state = getattr(session, "session_state", None)
                    if isinstance(session, dict):
                        s_state = session.get("session_state") or s_state

                    s_workspace_id = None
                    if isinstance(s_state, dict):
                        s_workspace_id = s_state.get("workspace_id")

                    if s_workspace_id is not None:
                        workspace_id = int(s_workspace_id)
                        await self.workspace_auth.authorize(
                            workspace_id=workspace_id,
                            user=current_user,
                        )
            except Exception as e_err:
                logger.warning(
                    f"Could not retrieve session workspace for chat authorization: {e_err}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Unauthorized: Could not verify session workspace authorization.",
                )

        if "newMessage" in body:
            new_msg = body["newMessage"]
            if "parts" in new_msg and new_msg["parts"]:
                is_function_response = any(
                    isinstance(p, dict)
                    and ("function_response" in p or "functionResponse" in p)
                    for p in new_msg["parts"]
                )
                if not is_function_response and session_id:
                    # A typed reply while a checkpoint is pending must answer
                    # that checkpoint; sent as text it reaches the root agent,
                    # which restarts the whole pipeline from the brief.
                    folded = await self._fold_into_pending_gate(
                        body["appName"], user_id, session_id, new_msg["parts"]
                    )
                    if folded is not None:
                        new_msg["parts"] = [folded]
                        is_function_response = True
                if not is_function_response:
                    sanitized_parts = []
                    attached_assets = []
                    for p in new_msg["parts"]:
                        if not isinstance(p, dict):
                            sanitized_parts.append(p)
                            continue
                        s_asset_id = p.pop("sourceAssetId", None)
                        s_media = p.pop("sourceMediaItem", None)
                        if s_asset_id is not None:
                            attached_assets.append(
                                f'<creative_studio_asset id={s_asset_id} type="source_asset" />'
                            )
                        if s_media is not None:
                            media_id = s_media.get("mediaItemId")
                            attached_assets.append(
                                f'<creative_studio_asset id={media_id} type="media_item" />'
                            )
                        if p:
                            sanitized_parts.append(p)

                    if attached_assets:
                        asset_list = "\n".join(
                            [f"- {aid}" for aid in attached_assets]
                        )
                        injections.append(
                            f"The user has attached the following reference assets:\n{asset_list}"
                        )

                    if injections:
                        injection_str = (
                            "\n\n[System Note:\n"
                            + "\n".join(injections)
                            + "\n]"
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

        # IMPORTANT: Extract the Authorization header synchronously before the background task starts.
        # FastAPI/Starlette may close the request scope when returning the response, which causes
        # request.headers to evaluate to empty if accessed inside the async process_stream() task.
        auth_header = request.headers.get("Authorization", "")

        # Internal background task function
        async def process_stream():
            try:
                import json

                app_name = body.get("appName") or APP_NAME
                logger.info(
                    f"[Agent Stream] Starting process_stream for session_id={session_id}, user_id={user_id}, app_name={app_name}"
                )
                remote_agent = self._get_remote_agent(app_name)
                agent_config = self._get_agent_config(app_name)
                auth_key = agent_config.get("token_key", "user_auth_token")

                if session_id and auth_header:
                    agent_name = self._get_validated_agent_name(app_name)
                    try:
                        logger.info(
                            f"[Agent Stream] Appending state delta token propagation for session_id={session_id}"
                        )
                        await self._append_state_delta(
                            agent_name,
                            app_name,
                            user_id,
                            session_id,
                            {auth_key: auth_header},
                        )
                        logger.info(
                            f"[Agent Stream] State delta token propagation appended successfully for session_id={session_id}"
                        )
                    except Exception as upd_err:
                        logger.warning(
                            f"[Agent Stream] Could not append state delta event: {upd_err}"
                        )

                msg_payload = body.get("newMessage")

                logger.info(
                    f"[Agent Stream] Invoking async_stream_query for session_id={session_id}, user_id={user_id}"
                )
                response_stream = remote_agent.async_stream_query(
                    user_id=user_id,
                    session_id=session_id,
                    message=msg_payload,
                )

                if hasattr(response_stream, "__await__") and not hasattr(
                    response_stream, "__aiter__"
                ):
                    response_stream = await response_stream

                def texts_of(evt: Any) -> list[str]:
                    data = to_dict_safe(evt)
                    if isinstance(data, str):
                        return [data]
                    if isinstance(data, dict):
                        content = data.get("content")
                        parts = (
                            content.get("parts")
                            if isinstance(content, dict)
                            else data.get("parts")
                        )
                        if isinstance(parts, list):
                            return [
                                str(p.get("text", ""))
                                for p in parts
                                if isinstance(p, dict) and "text" in p
                            ]
                        if "text" in data:
                            return [str(data["text"])]
                    return (
                        [str(getattr(evt, "text", ""))]
                        if hasattr(evt, "text")
                        else []
                    )

                def extract_event_meta(evt: Any):
                    data = to_dict_safe(evt)
                    if isinstance(data, dict):
                        return (
                            data.get("invocation_id"),
                            data.get("long_running_tool_ids"),
                        )
                    return (
                        getattr(evt, "invocation_id", None),
                        getattr(evt, "long_running_tool_ids", None),
                    )

                invocation_id = None
                paused_signal = False
                seen_texts = []

                async with async_session_local() as db_session:
                    repo = AgentRepository(db_session)
                    chunk_count = 0

                    async def handle_chunk(chunk):
                        nonlocal chunk_count, invocation_id, paused_signal
                        chunk_count += 1

                        cur_inv_id, cur_lrt_ids = extract_event_meta(chunk)
                        if cur_inv_id:
                            invocation_id = cur_inv_id

                        detected_approval = (
                            AgentService.detect_approval_function(chunk)
                        )

                        if cur_lrt_ids or detected_approval:
                            paused_signal = True
                            gate_desc = (
                                cur_lrt_ids
                                if cur_lrt_ids
                                else detected_approval
                            )
                            print(f"  gate emitted: {gate_desc}")
                            if detected_approval:
                                print(
                                    f"  [Approval Gate] Detected '{detected_approval}'. Waiting for user response."
                                )
                            logger.info(
                                f"[Agent Stream Gate Emitted] Agent is waiting for user response. "
                                f"long_running_tool_ids: {cur_lrt_ids}, approval_function: {detected_approval}, "
                                f"invocation_id: {invocation_id}"
                            )

                        seen_texts.extend(texts_of(chunk))

                        print(
                            f"[Agent Stream Event #{chunk_count}] invocation_id={invocation_id}, long_running_tool_ids={cur_lrt_ids}, approval_function={detected_approval}, response={chunk}"
                        )
                        logger.info(
                            f"[Agent Stream Chunk Received #{chunk_count}] invocation_id={invocation_id}, long_running_tool_ids={cur_lrt_ids}, approval_function={detected_approval}, Raw chunk: {chunk}"
                        )

                        if isinstance(chunk, str):
                            chunk_text = chunk
                        elif isinstance(chunk, dict):
                            chunk_text = json.dumps(chunk)
                        else:
                            try:
                                if hasattr(chunk, "model_dump"):
                                    chunk_text = json.dumps(chunk.model_dump())
                                elif hasattr(chunk, "to_dict"):
                                    chunk_text = json.dumps(chunk.to_dict())
                                else:
                                    chunk_text = json.dumps(str(chunk))
                            except Exception as parse_err:
                                logger.warning(
                                    f"[Agent Stream] Failed standard JSON parse/dump for chunk #{chunk_count}, falling back: {parse_err}"
                                )
                                chunk_text = json.dumps(str(chunk))

                        logger.info(
                            f"[Agent Stream Parsed JSON #{chunk_count}] {chunk_text}"
                        )
                        await repo.add_chat_event(
                            user_id=user_id,
                            session_id=session_id,
                            payload={"raw": f"data: {chunk_text}\n\n"},
                        )

                    if hasattr(response_stream, "__aiter__"):
                        async for chunk in response_stream:
                            await handle_chunk(chunk)
                    else:
                        for chunk in response_stream:
                            await handle_chunk(chunk)

                    if paused_signal:
                        print(
                            f"  [Agent Stream Paused] Waiting for user response. invocation_id: {invocation_id}"
                        )
                        logger.info(
                            f"[Agent Stream Paused] Stream paused waiting for user response. "
                            f"invocation_id={invocation_id}, seen_texts_count={len(seen_texts)}"
                        )

                    logger.info(
                        f"[Agent Stream Completed] Total chunks processed: {chunk_count} for session_id={session_id}, paused_signal={paused_signal}"
                    )
                    await repo.add_chat_event(
                        user_id=user_id,
                        session_id=session_id,
                        payload={"raw": "data: [DONE]\n\n"},
                    )
                    logger.info(
                        f"[Agent Stream] [DONE] event added to repository for session_id={session_id}"
                    )

            except Exception as e:
                logger.error(
                    f"[Agent Stream Error] Error streaming from Agent Engine: {e}",
                    exc_info=True,
                )
                try:
                    import json

                    error_type = "unknown"
                    code = 500
                    err_str = str(e)
                    err_lower = err_str.lower()
                    # Two runs on one session: the run holding the older
                    # session snapshot dies at its next append_event. Another
                    # run is still live, so a Retry would only kill that one.
                    if is_concurrent_run_error(err_str):
                        error_type = "concurrent_run"
                        code = 409
                    # The agent reuses the user's X-User-Authorization token
                    # for the whole run; when it expires mid-run its tool
                    # calls back into Creative Studio fail with 401. Check
                    # this first: such messages often also mention other
                    # codes/words that would match the branches below.
                    elif (
                        "401" in err_str
                        or "unauthorized" in err_lower
                        or "unauthenticated" in err_lower
                        or "token expired" in err_lower
                        or "token has expired" in err_lower
                        or "invalid token" in err_lower
                        or "expired token" in err_lower
                    ):
                        error_type = "auth_expired"
                        code = 401
                    elif (
                        "429" in err_str
                        or "ResourceExhausted" in err_str
                        or "quota" in err_lower
                    ):
                        error_type = "quota_exceeded"
                        code = 429
                    elif "503" in err_str or "UNAVAILABLE" in err_str:
                        error_type = "service_unavailable"
                        code = 503
                    elif (
                        "504" in err_str
                        or "DeadlineExceeded" in err_str
                        or "timeout" in err_str.lower()
                    ):
                        error_type = "timeout"
                        code = 504
                    elif "400" in err_str or "InvalidArgument" in err_str:
                        error_type = "invalid_argument"
                        code = 400

                    async with async_session_local() as db_session:
                        repo = AgentRepository(db_session)
                        error_msg = (
                            f"Internal error streaming from agent: {err_str}"
                        )
                        error_event = json.dumps(
                            {
                                "error": error_msg,
                                "code": code,
                                "type": error_type,
                            }
                        )
                        await repo.add_chat_event(
                            user_id=user_id,
                            session_id=session_id,
                            payload={"raw": f"data: {error_event}\n\n"},
                        )
                        await repo.add_chat_event(
                            user_id=user_id,
                            session_id=session_id,
                            payload={"raw": "data: [DONE]\n\n"},
                        )
                        logger.info(
                            f"[Agent Stream] Error event saved for session_id={session_id}, code={code}, type={error_type}"
                        )
                except Exception as save_err:
                    logger.error(
                        f"[Agent Stream] Failed to save error event: {save_err}",
                        exc_info=True,
                    )
            finally:
                if session_id:
                    _mark_run_finished(session_id)

        # Chat activity orders a project's chats (``latest_session_id``).
        # Recorded before the run lock below, so no await can separate the
        # lock's check from its mark.
        if session_id:
            try:
                await self.agent_session_repo.touch(session_id, current_user.id)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "[Agent Stream] Could not record activity for %s: %s",
                    session_id,
                    e,
                )

        # Refuse to start a second run on a session that is still executing:
        # it would corrupt the agent's session (see the registry docstring).
        # Check and mark without awaiting in between so that two simultaneous
        # requests cannot both pass.
        if session_id:
            if _is_run_active(session_id):
                logger.warning(
                    f"[Agent Stream] Rejecting chat for session_id={session_id}: a run is still active"
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=AGENT_BUSY_DETAIL,
                )
            _mark_run_started(session_id)

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
