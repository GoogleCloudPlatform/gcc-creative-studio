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
"""Client for a self-hosted Izumi agent (ADK web server), used when
``AGENT_BACKEND=local``.

``AgentService`` was written against the Vertex AI Agent Engine SDK. Rather than
branching every method on the backend type, this module implements the small
slice of that SDK the service actually uses, on top of the ADK web server's REST
API (``/apps/{app}/users/{user}/sessions...`` and ``/run_sse``):

* ``LocalAgentEngineClient().agent_engines.sessions.{list,create,get,delete}``
* ``LocalAgentEngineClient().agent_engines.sessions.events.{list,append}``
* ``LocalRemoteAgent.async_stream_query(...)``

Two contract differences are bridged here:

1. The ADK web server scopes every session path by ``user_id``, whereas Agent
   Engine addresses a session by its resource name alone. The client is
   therefore bound to the requesting user when it is created.
2. The ADK web server serializes events in camelCase, while Agent Engine (and
   therefore the frontend) uses snake_case. Events are normalized with
   :func:`to_snake_case_event`.
"""

import json
import logging
import re
from typing import Any, AsyncIterator
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# Prefix of the pseudo "resource name" used for the local agent. It only needs to
# round-trip through AgentService, which appends "/sessions/{id}" to it.
LOCAL_AGENT_NAME_PREFIX = "local-izumi/apps/"

# Session calls are quick; agent runs (video generation) can take many minutes.
_REQUEST_TIMEOUT = httpx.Timeout(30.0)
_STREAM_TIMEOUT = httpx.Timeout(30.0, read=None)

# Keys whose values are user/agent data, not event structure. Their contents
# are copied verbatim so that, e.g., tool arguments or session-state keys are
# never renamed.
_OPAQUE_KEYS = frozenset(
    {
        "args",
        "response",
        "state_delta",
        "artifact_delta",
        "custom_metadata",
        "requested_auth_configs",
        "requested_tool_confirmations",
    }
)

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


class LocalAgentError(Exception):
    """Raised when the local Izumi agent returns an error or is unreachable."""


def local_agent_name(app_name: str) -> str:
    """Returns the pseudo resource name AgentService uses for a local app."""
    return f"{LOCAL_AGENT_NAME_PREFIX}{app_name}"


def _parse_name(name: str) -> tuple[str, str | None]:
    """Splits ``local-izumi/apps/{app}[/sessions/{id}]`` into (app, session_id)."""
    if not name.startswith(LOCAL_AGENT_NAME_PREFIX):
        raise LocalAgentError(f"Not a local agent resource name: {name!r}")
    rest = name[len(LOCAL_AGENT_NAME_PREFIX) :]
    app_name, _, session_id = rest.partition("/sessions/")
    if not app_name:
        raise LocalAgentError(f"Missing app name in resource name: {name!r}")
    return app_name, (session_id or None)


def _camel_to_snake(key: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def to_snake_case_event(obj: Any) -> Any:
    """Recursively converts ADK camelCase event keys to snake_case.

    Values under :data:`_OPAQUE_KEYS` (tool args/responses, state deltas, ...)
    are left untouched because their keys are data, not schema.
    """
    if isinstance(obj, dict):
        converted = {}
        for key, value in obj.items():
            snake_key = _camel_to_snake(key) if isinstance(key, str) else key
            converted[snake_key] = (
                value
                if snake_key in _OPAQUE_KEYS
                else to_snake_case_event(value)
            )
        return converted
    if isinstance(obj, list):
        return [to_snake_case_event(item) for item in obj]
    return obj


def _to_session(data: dict) -> dict:
    """Maps an ADK session payload onto the shape AgentService expects."""
    return {
        "id": data.get("id"),
        "app_name": data.get("appName"),
        "user_id": data.get("userId"),
        "session_state": data.get("state") or {},
        "update_time": data.get("lastUpdateTime"),
        "events": [to_snake_case_event(e) for e in data.get("events") or []],
    }


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("detail", response.text)
    except (ValueError, AttributeError):
        detail = response.text
    # The status code is kept in the message on purpose: AgentService detects a
    # missing session by looking for "404" / "Session not found" in the error.
    raise LocalAgentError(
        f"{response.status_code} from local Izumi agent "
        f"({response.request.method} {response.request.url.path}): {detail}"
    )


class _Http:
    """Thin synchronous HTTP helper shared by the session resources."""

    def __init__(
        self,
        base_url: str,
        user_id: str | None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self._transport = transport

    def sessions_url(self, app_name: str, session_id: str | None = None) -> str:
        if not self.user_id:
            raise LocalAgentError(
                "The local agent client is not bound to a user; cannot address sessions."
            )
        url = (
            f"{self.base_url}/apps/{quote(app_name, safe='')}"
            f"/users/{quote(self.user_id, safe='')}/sessions"
        )
        if session_id:
            url += f"/{quote(session_id, safe='')}"
        return url

    def request(self, method: str, url: str, **kwargs) -> Any:
        try:
            with httpx.Client(
                timeout=_REQUEST_TIMEOUT, transport=self._transport
            ) as client:
                response = client.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise LocalAgentError(
                f"Could not reach the local Izumi agent at {self.base_url}: {e}"
            ) from e
        _raise_for_status(response)
        return response.json() if response.content else None


class _LocalSessionEvents:
    def __init__(self, http: _Http):
        self._http = http

    def list(self, name: str) -> list[dict]:
        app_name, session_id = _parse_name(name)
        data = self._http.request(
            "GET", self._http.sessions_url(app_name, session_id)
        )
        return [
            to_snake_case_event(e) for e in (data or {}).get("events") or []
        ]

    def append(self, name: str, config: dict | None = None, **_: Any) -> None:
        """Applies the ``state_delta`` of an appended event.

        AgentService only appends system events to refresh the user's auth
        token in the session state; the ADK web server exposes that as PATCH.
        """
        state_delta = ((config or {}).get("actions") or {}).get("state_delta")
        if not state_delta:
            raise LocalAgentError(
                "The local agent only supports appending events with a state_delta."
            )
        app_name, session_id = _parse_name(name)
        self._http.request(
            "PATCH",
            self._http.sessions_url(app_name, session_id),
            json={"stateDelta": state_delta},
        )


class _LocalSessions:
    def __init__(self, http: _Http):
        self._http = http
        self.events = _LocalSessionEvents(http)

    def list(self, name: str, config: dict | None = None) -> list[dict]:
        # `config` carries Agent Engine's user_id filter; ADK paths are already
        # scoped to the bound user, so it is not needed here.
        app_name, _ = _parse_name(name)
        data = self._http.request("GET", self._http.sessions_url(app_name))
        return [_to_session(s) for s in data or []]

    def create(
        self, name: str, user_id: str, config: dict | None = None
    ) -> dict:
        if user_id != self._http.user_id:
            raise LocalAgentError(
                "Refusing to create a session for a different user than the "
                "one the local agent client is bound to."
            )
        app_name, _ = _parse_name(name)
        state = (config or {}).get("session_state") or {}
        data = self._http.request(
            "POST", self._http.sessions_url(app_name), json={"state": state}
        )
        return _to_session(data or {})

    def get(self, name: str) -> dict:
        app_name, session_id = _parse_name(name)
        data = self._http.request(
            "GET", self._http.sessions_url(app_name, session_id)
        )
        return _to_session(data or {})

    def delete(self, name: str) -> None:
        app_name, session_id = _parse_name(name)
        self._http.request(
            "DELETE", self._http.sessions_url(app_name, session_id)
        )


class _LocalAgentEngines:
    def __init__(self, http: _Http):
        self.sessions = _LocalSessions(http)


class LocalAgentEngineClient:
    """Drop-in for the parts of ``vertexai.Client`` used by AgentService."""

    def __init__(
        self,
        base_url: str,
        user_id: str | None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.agent_engines = _LocalAgentEngines(
            _Http(base_url, user_id, transport)
        )


class LocalRemoteAgent:
    """Drop-in for the Agent Engine remote agent's ``async_stream_query``."""

    def __init__(
        self,
        base_url: str,
        app_name: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.app_name = app_name
        self._transport = transport

    async def async_stream_query(
        self, user_id: str, session_id: str, message: Any
    ) -> AsyncIterator[dict]:
        """Runs the agent and yields its events in Agent Engine (snake_case) form.

        ``streaming`` is False to match Agent Engine, which emits complete
        events rather than token-level partial chunks.
        """
        payload = {
            "appName": self.app_name,
            "userId": user_id,
            "sessionId": session_id,
            "newMessage": message,
            "streaming": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=_STREAM_TIMEOUT, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/run_sse", json=payload
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        _raise_for_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data:
                            continue
                        event = json.loads(data)
                        # The ADK web server reports run failures in-band.
                        if (
                            isinstance(event, dict)
                            and "error" in event
                            and "author" not in event
                        ):
                            raise LocalAgentError(
                                f"Local Izumi agent error: {event['error']}"
                            )
                        yield to_snake_case_event(event)
        except httpx.HTTPError as e:
            raise LocalAgentError(
                f"Could not stream from the local Izumi agent at {self.base_url}: {e}"
            ) from e
