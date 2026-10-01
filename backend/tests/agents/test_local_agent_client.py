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
"""Tests for the local Izumi (ADK web server) client."""

import json

import httpx
import pytest

from src.agents.local_agent_client import (
    LocalAgentEngineClient,
    LocalAgentError,
    LocalRemoteAgent,
    local_agent_name,
    to_snake_case_event,
)

BASE = "http://izumi-agent:8080"
AGENT = local_agent_name("ads_x")
SESSION = f"{AGENT}/sessions/s1"

ADK_SESSION = {
    "id": "s1",
    "appName": "ads_x",
    "userId": "7",
    "state": {"workspace_id": 3, "user_auth_token": "Bearer t"},
    "lastUpdateTime": 1790000000.5,
    "events": [
        {
            "author": "ads_x_agent",
            "invocationId": "inv-1",
            "longRunningToolIds": ["tool-1"],
            "content": {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "await_strategy_approval",
                            "args": {"campaignName": "x"},
                        }
                    }
                ],
            },
        }
    ],
}


def _client(handler, user_id="7"):
    return LocalAgentEngineClient(
        BASE, user_id=user_id, transport=httpx.MockTransport(handler)
    )


# --- to_snake_case_event -------------------------------------------------------


def test_to_snake_case_event_converts_structure_but_not_data():
    event = {
        "invocationId": "inv",
        "content": {
            "parts": [
                {"inlineData": {"mimeType": "image/png"}},
                {"functionCall": {"name": "f", "args": {"camelArg": 1}}},
                {"functionResponse": {"response": {"someKey": {"deepKey": 2}}}},
            ]
        },
        "actions": {
            "stateDelta": {"workspaceId": 1},
            "artifactDelta": {"fileName.png": 0},
        },
    }

    out = to_snake_case_event(event)

    assert out["invocation_id"] == "inv"
    parts = out["content"]["parts"]
    assert parts[0] == {"inline_data": {"mime_type": "image/png"}}
    assert parts[1]["function_call"]["args"] == {"camelArg": 1}
    assert parts[2]["function_response"]["response"] == {
        "someKey": {"deepKey": 2}
    }
    assert out["actions"]["state_delta"] == {"workspaceId": 1}
    assert out["actions"]["artifact_delta"] == {"fileName.png": 0}


def test_to_snake_case_event_passes_scalars_through():
    assert to_snake_case_event("text") == "text"
    assert to_snake_case_event(3) == 3
    assert to_snake_case_event({1: "a"}) == {1: "a"}


# --- resource names ------------------------------------------------------------


def test_rejects_non_local_resource_names():
    client = _client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(LocalAgentError, match="Not a local agent"):
        client.agent_engines.sessions.get(
            name="projects/p/locations/l/reasoningEngines/1/sessions/s1"
        )
    with pytest.raises(LocalAgentError, match="Missing app name"):
        client.agent_engines.sessions.get(name="local-izumi/apps//sessions/s1")


def test_requires_a_bound_user():
    client = _client(lambda request: httpx.Response(200, json={}), user_id=None)
    with pytest.raises(LocalAgentError, match="not bound to a user"):
        client.agent_engines.sessions.list(name=AGENT)


# --- sessions ------------------------------------------------------------------


def test_list_sessions_maps_adk_payload():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json=[ADK_SESSION])

    sessions = _client(handler).agent_engines.sessions.list(
        name=AGENT, config={"filter": 'user_id="7"'}
    )

    assert seen == [("GET", "/apps/ads_x/users/7/sessions")]
    assert sessions[0]["id"] == "s1"
    assert sessions[0]["app_name"] == "ads_x"
    assert sessions[0]["user_id"] == "7"
    assert sessions[0]["session_state"]["workspace_id"] == 3
    assert sessions[0]["update_time"] == 1790000000.5
    assert sessions[0]["events"][0]["long_running_tool_ids"] == ["tool-1"]


def test_create_session_posts_state():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ADK_SESSION)

    session = _client(handler).agent_engines.sessions.create(
        name=AGENT,
        user_id="7",
        config={"session_state": {"workspace_id": 3}},
    )

    assert seen == {
        "method": "POST",
        "path": "/apps/ads_x/users/7/sessions",
        "body": {"state": {"workspace_id": 3}},
    }
    assert session["id"] == "s1"


def test_create_session_refuses_another_user():
    client = _client(lambda request: httpx.Response(200, json=ADK_SESSION))
    with pytest.raises(LocalAgentError, match="different user"):
        client.agent_engines.sessions.create(name=AGENT, user_id="8")


def test_get_session_and_quotes_path_segments():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json=ADK_SESSION)

    client = LocalAgentEngineClient(
        BASE + "/", user_id="a/b", transport=httpx.MockTransport(handler)
    )
    session = client.agent_engines.sessions.get(name=SESSION)

    assert seen == ["/apps/ads_x/users/a%2Fb/sessions/s1"]
    assert session["session_state"]["user_auth_token"] == "Bearer t"


def test_get_missing_session_raises_404_error():
    client = _client(
        lambda request: httpx.Response(
            404, json={"detail": "Session not found"}
        )
    )
    with pytest.raises(LocalAgentError) as err:
        client.agent_engines.sessions.get(name=SESSION)
    # AgentService relies on these markers to re-create a missing session.
    assert "404" in str(err.value)
    assert "Session not found" in str(err.value)


def test_error_with_non_json_body():
    client = _client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(LocalAgentError, match="500 .*boom"):
        client.agent_engines.sessions.get(name=SESSION)


def test_unreachable_agent_raises():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LocalAgentError, match="Could not reach"):
        _client(handler).agent_engines.sessions.get(name=SESSION)


def test_delete_session():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200)

    assert _client(handler).agent_engines.sessions.delete(name=SESSION) is None
    assert seen == [("DELETE", "/apps/ads_x/users/7/sessions/s1")]


# --- events --------------------------------------------------------------------


def test_list_events_returns_snake_case_events():
    events = _client(
        lambda request: httpx.Response(200, json=ADK_SESSION)
    ).agent_engines.sessions.events.list(name=SESSION)

    assert events[0]["invocation_id"] == "inv-1"
    part = events[0]["content"]["parts"][0]
    assert part["function_call"]["name"] == "await_strategy_approval"
    assert part["function_call"]["args"] == {"campaignName": "x"}


def test_append_state_delta_patches_session():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ADK_SESSION)

    _client(handler).agent_engines.sessions.events.append(
        name=SESSION,
        author="system",
        invocation_id="token_propagation",
        timestamp=None,
        config={"actions": {"state_delta": {"user_auth_token": "Bearer n"}}},
    )

    assert seen == {
        "method": "PATCH",
        "path": "/apps/ads_x/users/7/sessions/s1",
        "body": {"stateDelta": {"user_auth_token": "Bearer n"}},
    }


def test_append_without_state_delta_is_rejected():
    client = _client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(LocalAgentError, match="state_delta"):
        client.agent_engines.sessions.events.append(name=SESSION, config={})


# --- streaming -----------------------------------------------------------------


def _agent(handler):
    return LocalRemoteAgent(
        BASE, app_name="ads_x", transport=httpx.MockTransport(handler)
    )


async def _collect(agent):
    return [
        event
        async for event in agent.async_stream_query(
            user_id="7", session_id="s1", message={"role": "user"}
        )
    ]


@pytest.mark.anyio
async def test_stream_query_yields_snake_case_events():
    seen = {}
    sse = (
        ": keep-alive\n\n"
        'data: {"author": "ads_x_agent", "invocationId": "inv-1"}\n\n'
        "data: \n\n"
        'data: {"author": "ads_x_agent", "longRunningToolIds": ["t"]}\n\n'
    )

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=sse)

    events = await _collect(_agent(handler))

    assert seen["path"] == "/run_sse"
    assert seen["body"] == {
        "appName": "ads_x",
        "userId": "7",
        "sessionId": "s1",
        "newMessage": {"role": "user"},
        "streaming": False,
    }
    assert events == [
        {"author": "ads_x_agent", "invocation_id": "inv-1"},
        {"author": "ads_x_agent", "long_running_tool_ids": ["t"]},
    ]


@pytest.mark.anyio
async def test_stream_query_raises_on_in_band_error():
    agent = _agent(
        lambda request: httpx.Response(
            200, text='data: {"error": "model not found"}\n\n'
        )
    )
    with pytest.raises(LocalAgentError, match="model not found"):
        await _collect(agent)


@pytest.mark.anyio
async def test_stream_query_raises_on_http_error_status():
    agent = _agent(
        lambda request: httpx.Response(
            404, json={"detail": "Session not found"}
        )
    )
    with pytest.raises(LocalAgentError, match="404"):
        await _collect(agent)


@pytest.mark.anyio
async def test_stream_query_raises_when_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LocalAgentError, match="Could not stream"):
        await _collect(_agent(handler))
