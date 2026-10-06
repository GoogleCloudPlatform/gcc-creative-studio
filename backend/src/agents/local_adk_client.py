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

"""HTTP client for a locally running Izumi agent (ADK ``api_server``).

In production the backend talks to Vertex AI Agent Engine through
``vertexai.Client``. When Creative Studio runs locally (``ENVIRONMENT=local``)
the same agent can be served by the ``izumi-agent`` Docker container, which
exposes the standard ADK REST API (``/apps/{app}/users/{user}/sessions`` and
``/run_sse``). This module adapts that API to the small surface
``AgentService`` needs so the rest of the chat pipeline stays untouched.

Everything returned here is normalised to the *snake_case* shape produced by
Agent Engine (``invocation_id``, ``actions.state_delta`` ...) because both the
backend stream handler and the Angular frontend already key off those names.
"""

import json
import logging
import re
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


class LocalAgentError(RuntimeError):
    """Raised when the local Izumi agent cannot be reached or returns an error."""


def _to_snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower()


def _snake_keys_shallow(data: Any, depth: int = 1) -> Any:
    """Converts camelCase keys to snake_case for the top ``depth`` levels only.

    Free-form payloads (tool args, state values, function responses) are left
    untouched so user data keys are never rewritten.
    """
    if not isinstance(data, dict) or depth < 0:
        return data
    return {
        _to_snake(k): (
            _snake_keys_shallow(v, depth - 1) if isinstance(v, dict) else v
        )
        for k, v in data.items()
    }


def normalize_event(raw: Any) -> Any:
    """Normalises an ADK REST event (camelCase) to Agent Engine's snake_case.

    Prefers a round-trip through the installed ``google.adk`` ``Event`` model
    (which leaves nested free-form dictionaries intact and serialises sets);
    falls back to a shallow key conversion if the payload does not validate.
    """
    if not isinstance(raw, dict):
        return raw
    try:
        from google.adk.events import (  # pylint: disable=import-outside-toplevel
            Event,
        )

        return Event.model_validate(raw).model_dump(
            mode="json", exclude_none=True
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("ADK Event validation failed, using shallow map: %s", exc)
        return _snake_keys_shallow(raw, depth=1)


def normalize_session(raw: dict[str, Any]) -> dict[str, Any]:
    """Maps an ADK ``Session`` JSON payload to the dict shape AgentService reads."""
    state = raw.get("state")
    if not isinstance(state, dict):
        state = raw.get("sessionState") or raw.get("session_state") or {}
    last_update = raw.get("lastUpdateTime", raw.get("last_update_time"))
    events = raw.get("events") or []
    return {
        "id": str(raw.get("id") or ""),
        "app_name": raw.get("appName") or raw.get("app_name"),
        "user_id": raw.get("userId") or raw.get("user_id"),
        "state": state,
        # AgentService reads Agent Engine's ``session_state`` key.
        "session_state": state,
        "last_update_time": (
            float(last_update)
            if isinstance(last_update, (int, float))
            else None
        ),
        "events": [normalize_event(e) for e in events if e is not None],
    }


class LocalRemoteAgent:
    """Mimics the ``agent_engines.get(...)`` handle used by ``process_stream``."""

    def __init__(self, client: "LocalAdkAgentClient", app_name: str):
        self._client = client
        self.app_name = app_name

    def async_stream_query(
        self, *, user_id: str, session_id: str, message: Any
    ) -> AsyncIterator[dict[str, Any]]:
        return self._client.stream_query(
            app_name=self.app_name,
            user_id=user_id,
            session_id=session_id,
            message=message,
        )


class LocalAdkAgentClient:
    """Minimal async client for the ADK ``api_server`` REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    # --- helpers -----------------------------------------------------------

    def _http(
        self, timeout: httpx.Timeout | float | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout if timeout is not None else self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _sessions_path(app_name: str, user_id: str) -> str:
        return f"/apps/{app_name}/users/{user_id}/sessions"

    def _unreachable(self, exc: Exception) -> LocalAgentError:
        return LocalAgentError(
            f"Local Izumi agent is not reachable at {self.base_url} ({exc}). "
            "Start it with `docker compose up` from "
            "genmedia-izumi-agent/demos/backend/ads_x or set "
            "USE_LOCAL_IZUMI_AGENT=false to use Vertex AI Agent Engine."
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response, action: str) -> None:
        if resp.is_success:
            return
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except (ValueError, AttributeError):
            pass
        raise LocalAgentError(
            f"Local Izumi agent {action} failed ({resp.status_code}): {detail}"
        )

    def remote_agent(self, app_name: str) -> LocalRemoteAgent:
        return LocalRemoteAgent(self, app_name)

    # --- sessions ----------------------------------------------------------

    async def list_sessions(
        self, app_name: str, user_id: str
    ) -> list[dict[str, Any]]:
        try:
            async with self._http() as http:
                resp = await http.get(self._sessions_path(app_name, user_id))
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(resp, "list sessions")
        payload = resp.json()
        sessions = payload if isinstance(payload, list) else []
        return [normalize_session(s) for s in sessions if isinstance(s, dict)]

    async def create_session(
        self,
        app_name: str,
        user_id: str,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._http() as http:
                resp = await http.post(
                    self._sessions_path(app_name, user_id),
                    json={"state": state or {}},
                )
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(resp, "create session")
        return normalize_session(resp.json())

    async def get_session(
        self, app_name: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        """Returns the normalised session, or ``None`` when it does not exist."""
        try:
            async with self._http() as http:
                resp = await http.get(
                    f"{self._sessions_path(app_name, user_id)}/{session_id}"
                )
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp, "get session")
        return normalize_session(resp.json())

    async def delete_session(
        self, app_name: str, user_id: str, session_id: str
    ) -> None:
        try:
            async with self._http() as http:
                resp = await http.delete(
                    f"{self._sessions_path(app_name, user_id)}/{session_id}"
                )
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        if resp.status_code == 404:
            return
        self._raise_for_status(resp, "delete session")

    async def update_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        state_delta: dict[str, Any],
    ) -> dict[str, Any]:
        """Applies a state delta without running the agent (token propagation)."""
        try:
            async with self._http() as http:
                resp = await http.patch(
                    f"{self._sessions_path(app_name, user_id)}/{session_id}",
                    json={"stateDelta": state_delta},
                )
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(resp, "update session state")
        return normalize_session(resp.json())

    # --- run ---------------------------------------------------------------

    async def stream_query(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        message: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streams complete ADK events from ``POST /run_sse``.

        ``streaming`` is left off so each SSE frame is a full event, which is
        what Agent Engine's ``async_stream_query`` yields as well.
        """
        body = {
            "appName": app_name,
            "userId": user_id,
            "sessionId": session_id,
            "newMessage": message,
            "streaming": False,
        }
        # Generation steps can take minutes: no read timeout, but fail fast
        # if the container is not up at all.
        timeout = httpx.Timeout(None, connect=10.0)
        try:
            async with self._http(timeout) as http:
                async with http.stream("POST", "/run_sse", json=body) as resp:
                    if not resp.is_success:
                        await resp.aread()
                        self._raise_for_status(resp, "run")
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data:
                            continue
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            logger.warning(
                                "Skipping non-JSON SSE frame from local agent: %s",
                                data[:200],
                            )
                            continue
                        if isinstance(parsed, dict) and set(parsed) == {
                            "error"
                        }:
                            agent_error = parsed["error"]
                            raise LocalAgentError(
                                f"Local Izumi agent error: {agent_error}"
                            )
                        yield normalize_event(parsed)
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
