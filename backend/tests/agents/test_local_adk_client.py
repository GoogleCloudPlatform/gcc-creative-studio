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
"""Tests for the local Izumi (ADK api_server) HTTP adapter."""

import json

import httpx
import pytest

from src.agents.local_adk_client import (
    LocalAdkAgentClient,
    LocalAgentError,
    LocalRemoteAgent,
    _snake_keys_shallow,
    normalize_event,
    normalize_session,
)

BASE = "http://izumi-agent:8080"
SESSIONS = "/apps/ads_x/users/u1/sessions"


def _session_json(**overrides):
    data = {
        "id": "s1",
        "appName": "ads_x",
        "userId": "u1",
        "state": {"workspace_id": 7, "user_auth_token": "Bearer t"},
        "events": [
            {
                "id": "e1",
                "invocationId": "inv-1",
                "author": "ads_x",
                "timestamp": 1.5,
                "content": {"role": "model", "parts": [{"text": "hi"}]},
                "actions": {"stateDelta": {"fooBar": 1}},
                "longRunningToolIds": ["lrt-1"],
            }
        ],
        "lastUpdateTime": 1718976000.0,
    }
    data.update(overrides)
    return data


def _client(handler) -> LocalAdkAgentClient:
    return LocalAdkAgentClient(
        BASE + "/", transport=httpx.MockTransport(handler)
    )


# --- normalisation helpers -------------------------------------------------


def test_normalize_event_uses_adk_model_snake_case():
    evt = normalize_event(_session_json()["events"][0])
    assert evt["invocation_id"] == "inv-1"
    assert evt["actions"]["state_delta"] == {"fooBar": 1}  # payload untouched
    assert evt["long_running_tool_ids"] == ["lrt-1"]
    assert evt["content"]["parts"][0]["text"] == "hi"


def test_normalize_event_passthrough_and_fallback():
    assert normalize_event("raw") == "raw"
    # An invalid author type makes the ADK model reject it -> shallow fallback.
    fallback = normalize_event(
        {
            "invocationId": "x",
            "author": {"bad": 1},
            "actions": {"stateDelta": {}},
        }
    )
    assert fallback["invocation_id"] == "x"
    assert fallback["actions"] == {"state_delta": {}}


def test_snake_keys_shallow_depth():
    out = _snake_keys_shallow(
        {"topKey": {"innerKey": {"deepKey": 1}}, "plain": 2}, depth=1
    )
    assert out == {"top_key": {"inner_key": {"deepKey": 1}}, "plain": 2}
    assert _snake_keys_shallow("x") == "x"


def test_normalize_session_shapes():
    s = normalize_session(_session_json())
    assert s["id"] == "s1"
    assert s["app_name"] == "ads_x"
    assert s["user_id"] == "u1"
    assert s["session_state"]["workspace_id"] == 7
    assert s["last_update_time"] == 1718976000.0
    assert s["events"][0]["invocation_id"] == "inv-1"

    minimal = normalize_session({"id": 5, "sessionState": {"a": 1}})
    assert minimal["id"] == "5"
    assert minimal["session_state"] == {"a": 1}
    assert minimal["last_update_time"] is None
    assert minimal["events"] == []


def test_remote_agent_delegates_to_client():
    client = LocalAdkAgentClient(BASE)
    agent = client.remote_agent("ads_x")
    assert isinstance(agent, LocalRemoteAgent)
    assert agent.app_name == "ads_x"
    stream = agent.async_stream_query(
        user_id="u1", session_id="s1", message={"parts": []}
    )
    assert hasattr(stream, "__aiter__")


# --- session endpoints -----------------------------------------------------


@pytest.mark.anyio
async def test_list_create_get_delete_update_sessions():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.method == "GET" and request.url.path == SESSIONS:
            return httpx.Response(200, json=[_session_json(), "junk"])
        if request.method == "POST" and request.url.path == SESSIONS:
            body = json.loads(request.content)
            return httpx.Response(
                200, json=_session_json(id="new", state=body["state"])
            )
        if request.method == "GET" and request.url.path == f"{SESSIONS}/s1":
            return httpx.Response(200, json=_session_json())
        if request.method == "GET" and request.url.path == f"{SESSIONS}/gone":
            return httpx.Response(404, json={"detail": "Session not found"})
        if request.method == "DELETE":
            return httpx.Response(
                404 if request.url.path.endswith("gone") else 200
            )
        if request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"stateDelta": {"user_auth_token": "Bearer x"}}
            return httpx.Response(200, json=_session_json())
        return httpx.Response(500, text="unexpected")

    client = _client(handler)

    sessions = await client.list_sessions("ads_x", "u1")
    assert len(sessions) == 1 and sessions[0]["id"] == "s1"

    created = await client.create_session("ads_x", "u1", {"workspace_id": 7})
    assert created["id"] == "new"
    assert created["session_state"] == {"workspace_id": 7}

    created_default = await client.create_session("ads_x", "u1")
    assert created_default["session_state"] == {}

    assert (await client.get_session("ads_x", "u1", "s1"))["id"] == "s1"
    assert await client.get_session("ads_x", "u1", "gone") is None

    await client.delete_session("ads_x", "u1", "s1")
    await client.delete_session("ads_x", "u1", "gone")  # 404 is tolerated

    updated = await client.update_session_state(
        "ads_x", "u1", "s1", {"user_auth_token": "Bearer x"}
    )
    assert updated["id"] == "s1"
    assert any(m == "PATCH" for m, _, _ in seen)


@pytest.mark.anyio
async def test_http_errors_are_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SESSIONS and request.method == "GET":
            return httpx.Response(200, json={"not": "a list"})
        if request.method == "PATCH":
            return httpx.Response(422, text="not json")
        return httpx.Response(500, json={"detail": "boom"})

    client = _client(handler)
    assert await client.list_sessions("ads_x", "u1") == []

    with pytest.raises(
        LocalAgentError, match="create session failed \\(500\\): boom"
    ):
        await client.create_session("ads_x", "u1", {})
    with pytest.raises(LocalAgentError, match="get session failed"):
        await client.get_session("ads_x", "u1", "s1")
    with pytest.raises(LocalAgentError, match="delete session failed"):
        await client.delete_session("ads_x", "u1", "s1")
    with pytest.raises(LocalAgentError, match="\\(422\\): not json"):
        await client.update_session_state("ads_x", "u1", "s1", {})


@pytest.mark.anyio
async def test_unreachable_agent_raises_actionable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler)
    for coro in (
        client.list_sessions("ads_x", "u1"),
        client.create_session("ads_x", "u1", {}),
        client.get_session("ads_x", "u1", "s1"),
        client.delete_session("ads_x", "u1", "s1"),
        client.update_session_state("ads_x", "u1", "s1", {}),
    ):
        with pytest.raises(LocalAgentError, match="not reachable"):
            await coro

    with pytest.raises(LocalAgentError, match="docker compose up"):
        async for _ in client.stream_query(
            app_name="ads_x", user_id="u1", session_id="s1", message={}
        ):
            pass


# --- run_sse ---------------------------------------------------------------


@pytest.mark.anyio
async def test_stream_query_parses_sse_and_normalizes():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        frames = [
            "event: ping",
            "",
            "data: " + json.dumps(_session_json()["events"][0]),
            "data: not-json",
            "data: ",
            "data: " + json.dumps({"id": "e2", "author": "user"}),
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="\n".join(frames) + "\n",
        )

    client = _client(handler)
    events = [
        e
        async for e in client.stream_query(
            app_name="ads_x",
            user_id="u1",
            session_id="s1",
            message={"role": "user", "parts": [{"text": "go"}]},
        )
    ]
    assert captured["body"] == {
        "appName": "ads_x",
        "userId": "u1",
        "sessionId": "s1",
        "newMessage": {"role": "user", "parts": [{"text": "go"}]},
        "streaming": False,
    }
    assert [e["id"] for e in events] == ["e1", "e2"]
    assert events[0]["invocation_id"] == "inv-1"


@pytest.mark.anyio
async def test_stream_query_error_frame_and_http_error():
    def handler_error_frame(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content='data: {"error": "agent exploded"}\n\n'
        )

    client = _client(handler_error_frame)
    with pytest.raises(LocalAgentError, match="agent exploded"):
        async for _ in client.stream_query(
            app_name="ads_x", user_id="u1", session_id="s1", message={}
        ):
            pass

    def handler_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Session not found"})

    client_404 = _client(handler_404)
    with pytest.raises(LocalAgentError, match="run failed \\(404\\)"):
        async for _ in client_404.stream_query(
            app_name="ads_x", user_id="u1", session_id="s1", message={}
        ):
            pass
