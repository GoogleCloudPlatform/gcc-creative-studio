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
"""AgentService running against a local Izumi agent (AGENT_BACKEND=local)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.agents.agent_service import AgentService
from src.agents.local_agent_client import (
    LocalAgentEngineClient,
    LocalRemoteAgent,
)
from src.config.config_service import ConfigService, config_service

BASE = "http://izumi-agent:8080"


def _adk_session(session_id, workspace_id):
    return {
        "id": session_id,
        "appName": "ads_x",
        "userId": "7",
        "state": (
            {"workspace_id": workspace_id} if workspace_id is not None else {}
        ),
        "lastUpdateTime": 1790000000.0,
        "events": [],
    }


@pytest.fixture
def local_backend():
    with patch.object(config_service, "AGENT_BACKEND", "local"):
        yield


def _service(current_user=None, transport=None):
    with patch("vertexai.Client") as vertex_client:
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=MagicMock(authorize=AsyncMock()),
            project_service=MagicMock(),
            current_user=current_user or MagicMock(id=7),
        )
    vertex_client.assert_not_called()
    if transport is not None:
        service.client = LocalAgentEngineClient(
            BASE, user_id="7", transport=transport
        )
    return service


# --- wiring --------------------------------------------------------------------


def test_local_backend_uses_local_client_and_agent(local_backend):
    service = _service()

    assert isinstance(service.client, LocalAgentEngineClient)
    assert service.client.agent_engines.sessions._http.user_id == "7"
    assert service._get_validated_agent_name("ads_x") == (
        "local-izumi/apps/ads_x"
    )
    remote = service._get_remote_agent("ads_x")
    assert isinstance(remote, LocalRemoteAgent)
    assert remote.app_name == "ads_x"


def test_local_backend_without_user_leaves_client_unbound(local_backend):
    service = _service(current_user=object())
    assert service.client.agent_engines.sessions._http.user_id is None


def test_agent_engine_backend_creates_vertex_client():
    # tests/agents/conftest.py pins AGENT_BACKEND="agent_engine".
    with patch("vertexai.Client") as vertex_client:
        AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=MagicMock(),
            workspace_auth=MagicMock(),
            project_service=MagicMock(),
        )
    vertex_client.assert_called_once()


# --- config guard --------------------------------------------------------------


def test_local_backend_is_rejected_outside_local_environment():
    with pytest.raises(ValueError, match="only allowed with ENVIRONMENT=local"):
        ConfigService(
            _env_file=None,
            PROJECT_ID="p",
            ENVIRONMENT="production",
            AGENT_BACKEND="local",
        )


def test_local_backend_is_accepted_in_local_environment():
    config = ConfigService(
        _env_file=None,
        PROJECT_ID="p",
        ENVIRONMENT="local",
        AGENT_BACKEND="local",
    )
    assert config.AGENT_BACKEND == "local"


def test_unknown_agent_backend_is_rejected():
    with pytest.raises(ValueError):
        ConfigService(_env_file=None, PROJECT_ID="p", AGENT_BACKEND="other")


# --- AgentService flows through the adapter --------------------------------------


@pytest.mark.anyio
async def test_list_sessions_filters_by_workspace(local_backend):
    def handler(request):
        assert request.url.path == "/apps/ads_x/users/7/sessions"
        return httpx.Response(
            200,
            json=[
                _adk_session("s1", 3),
                _adk_session("s2", 4),
                _adk_session("s3", None),
            ],
        )

    service = _service(transport=httpx.MockTransport(handler))
    sessions = await service.list_sessions(
        current_user=MagicMock(id=7),
        user_id="7",
        request=MagicMock(),
        workspace_id=3,
    )

    assert [s.id for s in sessions] == ["s1"]
    assert sessions[0].state == {"workspace_id": 3}
    assert sessions[0].lastUpdateTime == 1790000000.0


@pytest.mark.anyio
async def test_create_session_stores_workspace_and_token(local_backend):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_adk_session("new", 3))

    service = _service(transport=httpx.MockTransport(handler))
    request = MagicMock()
    request.headers = {"Authorization": "Bearer user-token"}

    session = await service.create_session(
        current_user=MagicMock(id=7),
        user_id="7",
        request=request,
        workspace_id=3,
    )

    assert session.id == "new"
    assert seen["body"] == {
        "state": {"workspace_id": 3, "user_auth_token": "Bearer user-token"}
    }


@pytest.mark.anyio
async def test_get_session_messages_and_delete(local_backend):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "DELETE":
            return httpx.Response(200)
        return httpx.Response(200, json=_adk_session("s1", 3))

    service = _service(transport=httpx.MockTransport(handler))
    user = MagicMock(id=7)

    messages = await service.get_session_messages(
        current_user=user, session_id="s1", user_id="7", request=MagicMock()
    )
    assert messages.id == "s1"

    result = await service.delete_session(
        current_user=user, session_id="s1", user_id="7", request=MagicMock()
    )
    assert result == {"status": "success"}
    assert calls == ["GET", "GET", "GET", "DELETE"]
