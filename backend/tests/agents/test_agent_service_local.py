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
"""AgentService behaviour when ENVIRONMENT=local routes to the Izumi container."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from src.agents.agent_service import (
    LOCAL_AGENT_NAME_PREFIX,
    AgentService,
)
from src.agents.local_adk_client import LocalAdkAgentClient, LocalRemoteAgent
from src.config.config_service import config_service
from src.users.user_model import UserModel


@pytest.fixture(name="local_mode")
def fixture_local_mode():
    """Forces the local Izumi agent path and restores the prior setting."""
    previous = config_service.USE_LOCAL_IZUMI_AGENT
    config_service.USE_LOCAL_IZUMI_AGENT = True
    yield
    config_service.USE_LOCAL_IZUMI_AGENT = previous


def _service(local_client: AsyncMock | None = None, **deps) -> AgentService:
    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=deps.get("agent_repo", MagicMock()),
            workspace_service=MagicMock(),
            storyboard_repo=deps.get("storyboard_repo", AsyncMock()),
            workspace_auth=deps.get("workspace_auth", AsyncMock()),
            project_service=deps.get("project_service", AsyncMock()),
        )
    if local_client is not None:
        service.local_client = local_client
    return service


def _local_session(session_id="s1", workspace_id=10, events=None):
    return {
        "id": session_id,
        "app_name": "ads_x",
        "user_id": "999",
        "state": {"workspace_id": workspace_id},
        "session_state": {"workspace_id": workspace_id},
        "last_update_time": 1718976000.0,
        "events": events or [],
    }


def test_is_local_izumi_agent_resolution():
    previous_flag = config_service.USE_LOCAL_IZUMI_AGENT
    previous_env = config_service.ENVIRONMENT
    try:
        config_service.USE_LOCAL_IZUMI_AGENT = None
        config_service.ENVIRONMENT = "local"
        assert config_service.IS_LOCAL_IZUMI_AGENT is True
        config_service.ENVIRONMENT = "production"
        assert config_service.IS_LOCAL_IZUMI_AGENT is False
        config_service.USE_LOCAL_IZUMI_AGENT = True
        assert config_service.IS_LOCAL_IZUMI_AGENT is True
        config_service.ENVIRONMENT = "local"
        config_service.USE_LOCAL_IZUMI_AGENT = False
        assert config_service.IS_LOCAL_IZUMI_AGENT is False
    finally:
        config_service.USE_LOCAL_IZUMI_AGENT = previous_flag
        config_service.ENVIRONMENT = previous_env


def test_init_builds_local_client_and_remote_agent(local_mode):
    service = _service()
    assert service.use_local_agent is True
    assert isinstance(service.local_client, LocalAdkAgentClient)
    assert (
        service.local_client.base_url
        == config_service.IZUMI_AGENT_URL.rstrip("/")
    )
    remote = service._get_remote_agent("ads_x")
    assert isinstance(remote, LocalRemoteAgent)
    assert remote.app_name == "ads_x"


def test_vertex_mode_does_not_build_local_client():
    service = _service()
    assert service.use_local_agent is False
    assert service.local_client is None


def test_validated_agent_name_falls_back_locally(local_mode):
    service = _service()
    with patch(
        "src.agents.agent_service.AGENT_REASONING_ENGINES",
        {"ads_x": {"resource_name": "", "token_key": "user_auth_token"}},
    ):
        assert (
            service._get_validated_agent_name("ads_x")
            == f"{LOCAL_AGENT_NAME_PREFIX}/ads_x"
        )


@pytest.mark.anyio
async def test_list_sessions_local_filters_by_workspace(local_mode):
    local_client = AsyncMock()
    local_client.list_sessions.return_value = [
        _local_session("s1", 10),
        _local_session("s2", 11),
        {**_local_session("s3"), "session_state": {}},
    ]
    service = _service(local_client)
    user = MagicMock(spec=UserModel)

    result = await service.list_sessions(
        current_user=user,
        user_id="999",
        request=MagicMock(spec=Request),
        workspace_id=10,
    )
    local_client.list_sessions.assert_awaited_once_with("ads_x", "999")
    assert [s.id for s in result] == ["s1"]
    assert result[0].lastUpdateTime == 1718976000.0


@pytest.mark.anyio
async def test_create_session_local_passes_state(local_mode):
    local_client = AsyncMock()
    local_client.create_session.return_value = _local_session("fresh", 10)
    service = _service(local_client)
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer abc"}

    dto = await service.create_session(
        current_user=MagicMock(spec=UserModel),
        user_id="999",
        request=request,
        workspace_id=10,
    )
    local_client.create_session.assert_awaited_once_with(
        "ads_x",
        "999",
        {"workspace_id": 10, "user_auth_token": "Bearer abc"},
    )
    assert dto.id == "fresh"
    assert dto.userId == "999"


@pytest.mark.anyio
async def test_get_session_detail_local_recreates_missing_session(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = None
    local_client.create_session.return_value = _local_session("new_id", 1)

    storyboard = MagicMock()
    storyboard.id = 123
    storyboard.user_id = 999
    storyboard.session_id = "old"
    storyboard.template_name = "test_template"
    storyboard.bg_music_description = "some music"
    storyboard.timeline = MagicMock(title="my timeline")
    project_service = AsyncMock()
    project_service.get_storyboard.return_value = storyboard
    storyboard_repo = AsyncMock()

    service = _service(
        local_client,
        project_service=project_service,
        storyboard_repo=storyboard_repo,
    )
    user = MagicMock(spec=UserModel)
    user.id = 999
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer abc"}

    res = await service.get_session_detail(
        current_user=user, workspace_id=1, request=request, storyboard_id=123
    )
    local_client.get_session.assert_awaited_once_with("ads_x", "999", "old")
    storyboard_repo.update.assert_awaited_once_with(
        123, {"session_id": "new_id"}
    )
    assert res.session.id == "new_id"
    # Events come straight from the (new) session payload, no extra fetch.
    assert local_client.get_session.await_count == 1


@pytest.mark.anyio
async def test_get_session_messages_local_uses_embedded_events(local_mode):
    event = {"id": "e1", "author": "ads_x", "invocation_id": "inv"}
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(
        "s1", 10, events=[event]
    )
    workspace_auth = AsyncMock()
    service = _service(local_client, workspace_auth=workspace_auth)
    user = MagicMock(spec=UserModel)

    dto = await service.get_session_messages(
        current_user=user,
        session_id="s1",
        user_id="999",
        request=MagicMock(spec=Request),
    )
    workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=10, user=user
    )
    assert dto.events == [event]
    assert local_client.get_session.await_count == 1


@pytest.mark.anyio
async def test_get_session_messages_local_404(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = None
    service = _service(local_client)
    with pytest.raises(Exception) as exc:
        await service.get_session_messages(
            current_user=MagicMock(spec=UserModel),
            session_id="missing",
            user_id="999",
            request=MagicMock(spec=Request),
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.anyio
async def test_events_list_local_refetches_without_session(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session(
        "s1", 10, events=[{"id": "x"}]
    )
    service = _service(local_client)
    events = await service._events_list("agent", "ads_x", "999", "s1")
    assert events == [{"id": "x"}]

    local_client.get_session.return_value = None
    assert await service._events_list("agent", "ads_x", "999", "s1") == []


@pytest.mark.anyio
async def test_delete_session_local(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session("s1", 10)
    workspace_auth = AsyncMock()
    service = _service(local_client, workspace_auth=workspace_auth)
    user = MagicMock(spec=UserModel)

    res = await service.delete_session(
        current_user=user,
        session_id="s1",
        user_id="999",
        request=MagicMock(spec=Request),
    )
    assert res == {"status": "success"}
    workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=10, user=user
    )
    local_client.delete_session.assert_awaited_once_with("ads_x", "999", "s1")


@pytest.mark.anyio
async def test_chat_local_streams_and_propagates_token(local_mode):
    local_client = AsyncMock()
    local_client.get_session.return_value = _local_session("s1", 10)

    async def fake_stream(**kwargs):
        assert kwargs["app_name"] == "ads_x"
        assert kwargs["user_id"] == "999"
        assert kwargs["session_id"] == "s1"
        yield {
            "id": "e1",
            "invocation_id": "inv-1",
            "author": "ads_x",
            "content": {"role": "model", "parts": [{"text": "working"}]},
        }
        yield {
            "id": "e2",
            "invocation_id": "inv-1",
            "author": "ads_x",
            "long_running_tool_ids": ["lrt"],
            "content": {
                "role": "model",
                "parts": [
                    {"function_call": {"name": "await_strategy_approval"}}
                ],
            },
        }

    # stream_query is an async generator function, not a coroutine.
    local_client.stream_query = MagicMock(side_effect=fake_stream)
    local_client.remote_agent = MagicMock(
        side_effect=lambda app: LocalRemoteAgent(local_client, app)
    )

    workspace_auth = AsyncMock()
    service = _service(local_client, workspace_auth=workspace_auth)
    user = MagicMock(spec=UserModel)
    payload = MagicMock()
    payload.model_dump.return_value = {
        "sessionId": "s1",
        "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
    }
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer abc"}

    repo = AsyncMock()
    with (
        patch("src.agents.agent_service.async_session_local") as db_ctx,
        patch("src.agents.agent_service.AgentRepository", return_value=repo),
    ):
        db_ctx.return_value.__aenter__.return_value = AsyncMock()
        res = await service.chat(
            current_user=user, user_id="999", payload=payload, request=request
        )
        await asyncio.sleep(0.1)

    assert res == {"status": "processing"}
    # Workspace resolved from the local session state.
    workspace_auth.authorize.assert_awaited_once_with(
        workspace_id=10, user=user
    )
    # Token propagated through PATCH state delta on the local container.
    local_client.update_session_state.assert_awaited_once_with(
        "ads_x", "999", "s1", {"user_auth_token": "Bearer abc"}
    )
    raws = [
        c.kwargs["payload"]["raw"] for c in repo.add_chat_event.await_args_list
    ]
    assert len(raws) == 3
    assert json.loads(raws[0].split("data: ")[1])["id"] == "e1"
    assert json.loads(raws[1].split("data: ")[1])["long_running_tool_ids"] == [
        "lrt"
    ]
    assert raws[2] == "data: [DONE]\n\n"


@pytest.mark.anyio
async def test_chat_local_unreachable_agent_records_error(local_mode):
    from src.agents.local_adk_client import LocalAgentError

    local_client = AsyncMock()

    async def failing_stream(**_kwargs):
        raise LocalAgentError("Local Izumi agent is not reachable (503)")
        yield  # pragma: no cover - makes this an async generator

    local_client.stream_query = MagicMock(side_effect=failing_stream)
    local_client.remote_agent = MagicMock(
        side_effect=lambda app: LocalRemoteAgent(local_client, app)
    )
    service = _service(local_client)
    payload = MagicMock()
    payload.model_dump.return_value = {
        "sessionId": "s1",
        "workspaceId": 10,
        "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
    }
    request = MagicMock(spec=Request)
    request.headers = {}

    repo = AsyncMock()
    with (
        patch("src.agents.agent_service.async_session_local") as db_ctx,
        patch("src.agents.agent_service.AgentRepository", return_value=repo),
    ):
        db_ctx.return_value.__aenter__.return_value = AsyncMock()
        await service.chat(
            current_user=MagicMock(spec=UserModel),
            user_id="999",
            payload=payload,
            request=request,
        )
        await asyncio.sleep(0.1)

    # No Authorization header -> no token propagation attempted.
    local_client.update_session_state.assert_not_awaited()
    raws = [
        c.kwargs["payload"]["raw"] for c in repo.add_chat_event.await_args_list
    ]
    error = json.loads(raws[0].split("data: ")[1])
    assert error["type"] == "service_unavailable"
    assert "not reachable" in error["error"]
    assert raws[-1] == "data: [DONE]\n\n"
