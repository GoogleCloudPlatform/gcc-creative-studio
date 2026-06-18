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

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.auth_guard import get_current_user
from src.database import get_db
from src.agents.agent_controller import router
from src.users.user_model import UserModel
from src.agents.agent_chat_event_model import AgentChatEvent
from src.projects.project_repository import StoryboardRepository
from src.projects.project_service import ProjectService


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.fixture(name="mock_db")
def fixture_mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture(name="mock_workspace_service")
def fixture_mock_workspace_service():
    service = AsyncMock()
    service.list_workspaces_for_user = AsyncMock(return_value=[MagicMock(id=1)])
    return service


@pytest.fixture(name="mock_storyboard_repo")
def fixture_mock_storyboard_repo():
    repo = AsyncMock(spec=StoryboardRepository)
    return repo


@pytest.fixture(name="mock_remote_agent")
def fixture_mock_remote_agent():
    with (
        patch(
            "src.agents.agent_service.AgentService._get_remote_agent"
        ) as mock,
        patch("vertexai.Client") as mock_vclient,
    ):
        mock_instance = MagicMock()
        mock.return_value = mock_instance

        mock_vclient_inst = MagicMock()
        mock_vclient.return_value = mock_vclient_inst
        mock_vclient_inst.agent_engines.sessions.list.return_value = [
            {
                "id": "session_1",
                "appName": "ads_x",
                "userId": "1",
                "state": {},
                "lastUpdateTime": None,
                "events": [],
            }
        ]
        mock_vclient_inst.agent_engines.sessions.create.return_value = {
            "id": "session_1",
            "appName": "ads_x",
            "userId": "1",
            "state": {},
            "lastUpdateTime": None,
            "events": [],
        }
        mock_vclient_inst.agent_engines.sessions.get.return_value = {
            "id": "session_1",
            "appName": "ads_x",
            "userId": "1",
            "state": {},
            "lastUpdateTime": None,
            "events": [],
        }
        mock_vclient_inst.agent_engines.sessions.delete.return_value = None
        mock_instance.vclient = mock_vclient_inst
        yield mock_instance


@pytest.fixture(name="mock_project_service")
def fixture_mock_project_service():
    service = AsyncMock(spec=ProjectService)
    return service


@pytest.fixture(name="mock_workspace_repo")
def fixture_mock_workspace_repo():
    repo = AsyncMock()
    from src.workspaces.schema.workspace_model import (
        WorkspaceScopeEnum,
        WorkspaceModel,
    )

    repo.get_scope.return_value = WorkspaceScopeEnum.PUBLIC
    mock_workspace = MagicMock(spec=WorkspaceModel)
    mock_workspace.id = 1
    mock_workspace.name = "Test Workspace"
    mock_workspace.scope = WorkspaceScopeEnum.PUBLIC
    repo.get_by_id.return_value = mock_workspace
    return repo


@pytest.fixture(name="client")
def fixture_client(
    mock_user,
    mock_db,
    mock_workspace_service,
    mock_storyboard_repo,
    mock_workspace_repo,
    mock_project_service,
):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    from src.workspaces.workspace_service import WorkspaceService
    from src.workspaces.repository.workspace_repository import (
        WorkspaceRepository,
    )
    from src.agents.agent_controller import security
    from fastapi.security import HTTPAuthorizationCredentials

    app.dependency_overrides[WorkspaceService] = lambda: mock_workspace_service
    app.dependency_overrides[WorkspaceRepository] = lambda: mock_workspace_repo
    app.dependency_overrides[StoryboardRepository] = (
        lambda: mock_storyboard_repo
    )
    app.dependency_overrides[ProjectService] = lambda: mock_project_service
    app.dependency_overrides[security] = lambda: HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="dummy"
    )
    return TestClient(app, headers={"Authorization": "Bearer dummy"})


@pytest.mark.anyio
async def test_get_sessions_success(mock_remote_agent, client):
    mock_remote_agent.async_list_sessions.return_value = [
        {"id": "session_1", "state": {}, "last_update_time": None, "events": []}
    ]

    response = client.get("/api/agent/sessions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "session_1",
            "appName": "ads_x",
            "userId": "1",
            "lastUpdateTime": None,
            "state": {},
            "events": [],
        }
    ]


@pytest.mark.anyio
async def test_create_session_success(mock_remote_agent, client):
    mock_remote_agent.async_create_session.return_value = {
        "id": "session_1",
        "state": {},
    }

    response = client.post("/api/agent/sessions")

    assert response.status_code == 200
    assert response.json() == {
        "id": "session_1",
        "appName": "ads_x",
        "userId": "1",
        "lastUpdateTime": None,
        "state": {},
        "events": [],
    }


@pytest.mark.anyio
async def test_get_session_messages_success(mock_remote_agent, client):
    mock_remote_agent.async_get_session.return_value = {
        "id": "session_1",
        "state": {},
        "last_update_time": None,
        "events": [],
    }

    response = client.get("/api/agent/sessions/session_1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "session_1",
        "appName": "ads_x",
        "userId": "1",
        "lastUpdateTime": None,
        "state": {},
        "events": [],
    }


@pytest.mark.anyio
async def test_delete_session_success(mock_remote_agent, client):
    mock_remote_agent.async_delete_session.return_value = None

    response = client.delete("/api/agent/sessions/session_1")

    assert response.status_code == 200
    assert response.json() == {"status": "success"}


@pytest.mark.anyio
async def test_poll_session_events_success(client, mock_db):
    mock_result = MagicMock()
    dummy_event = AgentChatEvent(
        id=1, user_id="1", session_id="s1", payload={"raw": "data: event1"}
    )
    mock_result.scalars().all.return_value = [dummy_event]
    mock_db.execute.return_value = mock_result

    response = client.get("/api/agent/sessions/s1/poll")

    assert response.status_code == 200
    assert response.json() == {"events": ["data: event1"]}
    mock_db.execute.assert_called()
    mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_chat_success(mock_remote_agent, client, mock_db):
    async def dummy_stream(*args, **kwargs):
        if False:
            yield None

    mock_remote_agent.async_stream_query = dummy_stream

    payload = {
        "sessionId": "s1",
        "workspaceId": 1,
        "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
    }

    response = client.post("/api/agent/chat", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "processing"}


@pytest.mark.anyio
async def test_get_session_detail_by_session_id(
    mock_remote_agent, mock_project_service, client
):
    mock_remote_agent.vclient.agent_engines.sessions.get.return_value = {
        "id": "s1",
        "state": {},
        "last_update_time": None,
        "events": [],
    }

    mock_storyboard = MagicMock()
    mock_storyboard.id = 123
    mock_storyboard.user_id = 1
    mock_storyboard.workspace_id = 1
    mock_storyboard.session_id = "s1"
    mock_storyboard.template_name = "Custom"
    mock_storyboard.bg_music_description = None
    mock_storyboard.bg_music_asset_id = None
    mock_storyboard.scenes = []
    mock_storyboard.timeline = None
    mock_project_service.list_storyboards.return_value = [mock_storyboard]

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&session_id=s1"
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["session"]["id"] == "s1"
    assert res_data["storyboard"]["id"] == 123


@pytest.mark.anyio
async def test_get_session_detail_by_storyboard_id(
    mock_remote_agent, mock_project_service, client
):
    mock_storyboard = MagicMock()
    mock_storyboard.id = 123
    mock_storyboard.user_id = 1
    mock_storyboard.workspace_id = 1
    mock_storyboard.session_id = "s1"
    mock_storyboard.template_name = "Custom"
    mock_storyboard.bg_music_description = None
    mock_storyboard.bg_music_asset_id = None
    mock_storyboard.scenes = []
    mock_storyboard.timeline = None
    mock_project_service.get_storyboard.return_value = mock_storyboard

    mock_remote_agent.vclient.agent_engines.sessions.get.return_value = {
        "id": "s1",
        "state": {},
        "last_update_time": None,
        "events": [],
    }

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&storyboard_id=123"
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["session"]["id"] == "s1"
    assert res_data["storyboard"]["id"] == 123


@pytest.mark.anyio
async def test_get_session_detail_storyboard_not_found(
    mock_project_service, client
):
    mock_project_service.get_storyboard.return_value = None

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&storyboard_id=999"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Storyboard not found"


@pytest.mark.anyio
async def test_get_session_detail_unauthorized(mock_project_service, client):
    mock_storyboard = MagicMock()
    mock_storyboard.id = 123
    mock_storyboard.user_id = 999
    mock_project_service.get_storyboard.return_value = mock_storyboard

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&storyboard_id=123"
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"] == "Not authorized to access this storyboard"
    )


@pytest.mark.anyio
async def test_get_session_detail_missing_params(client):
    response = client.get("/api/agent/sessions/detail?workspace_id=1")

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Either session_id or storyboard_id must be provided to query details."
    )


@pytest.mark.anyio
async def test_get_session_detail_storyboard_id_out_of_range(
    mock_project_service, client
):
    mock_project_service.get_storyboard.side_effect = Exception(
        "value out of int32 range"
    )

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&storyboard_id=6454042614055305000"
    )

    assert response.status_code == 400
    assert "Invalid storyboard ID" in response.json()["detail"]
    assert (
        "out of range for the database integer type"
        in response.json()["detail"]
    )


@pytest.mark.anyio
async def test_agent_service_sync_fallbacks(mock_remote_agent):
    from src.agents.agent_service import AgentService

    service = AgentService(
        agent_repo=MagicMock(),
        workspace_service=MagicMock(),
        storyboard_repo=MagicMock(),
        workspace_auth=MagicMock(),
        project_service=MagicMock(),
    )

    # Remove async methods to trigger sync fallback branches
    for attr in [
        "async_list_sessions",
        "async_create_session",
        "async_get_session",
        "async_delete_session",
        "async_stream_query",
    ]:
        if hasattr(mock_remote_agent, attr):
            delattr(mock_remote_agent, attr)

    mock_remote_agent.list_sessions.return_value = [
        MagicMock(
            id="s1",
            app_name="app",
            user_id="u",
            state={},
            last_update_time=None,
            events=[],
        )
    ]
    mock_remote_agent.create_session.return_value = {"id": "s2"}
    mock_remote_agent.get_session.return_value = MagicMock(
        id="s1",
        app_name="app",
        user_id="u",
        state={},
        last_update_time=None,
        events=[],
    )
    mock_remote_agent.delete_session.return_value = None

    await service.list_sessions("u", MagicMock())
    await service.create_session("u", MagicMock())
    await service.get_session_messages("s1", "u", MagicMock())
    await service.delete_session("s1", "u", MagicMock())


@pytest.mark.anyio
async def test_agent_service_exceptions(mock_remote_agent):
    from src.agents.agent_service import AgentService
    import pytest
    from fastapi import HTTPException

    service = AgentService(
        agent_repo=MagicMock(),
        workspace_service=MagicMock(),
        storyboard_repo=MagicMock(),
        workspace_auth=MagicMock(),
        project_service=MagicMock(),
    )

    service.client.agent_engines.sessions.list.side_effect = Exception("err")
    with pytest.raises(HTTPException):
        await service.list_sessions("u", MagicMock())

    service.client.agent_engines.sessions.create.side_effect = Exception("err")
    with pytest.raises(HTTPException):
        await service.create_session("u", MagicMock())

    service.client.agent_engines.sessions.get.side_effect = Exception("err")
    with pytest.raises(HTTPException):
        await service.get_session_messages("s1", "u", MagicMock())

    service.client.agent_engines.sessions.delete.side_effect = Exception("err")
    with pytest.raises(HTTPException):
        await service.delete_session("s1", "u", MagicMock())
