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


@pytest.fixture(name="mock_reasoning_engine")
def fixture_mock_reasoning_engine():
    with patch(
        "src.agents.agent_controller.reasoning_engines.ReasoningEngine"
    ) as mock:
        mock_instance = MagicMock()
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture(name="mock_enrich_storyboard", autouse=True)
def fixture_mock_enrich_storyboard():
    with patch(
        "src.agents.agent_controller._enrich_storyboard", AsyncMock()
    ) as mock:
        yield mock


@pytest.fixture(name="client")
def fixture_client(
    mock_user, mock_db, mock_workspace_service, mock_storyboard_repo
):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    from src.workspaces.workspace_service import WorkspaceService

    app.dependency_overrides[WorkspaceService] = lambda: mock_workspace_service
    app.dependency_overrides[StoryboardRepository] = (
        lambda: mock_storyboard_repo
    )
    return TestClient(app)


@pytest.mark.anyio
async def test_get_sessions_success(mock_reasoning_engine, client):
    mock_reasoning_engine.list_sessions.return_value = [
        {"id": "session_1", "state": {}, "lastUpdateTime": None, "events": []}
    ]

    response = client.get("/api/agent/sessions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "session_1",
            "appName": "ads_x_template",
            "userId": "1",
            "lastUpdateTime": None,
            "state": {},
            "events": [],
        }
    ]


@pytest.mark.anyio
async def test_create_session_success(mock_reasoning_engine, client):
    mock_reasoning_engine.create_session.return_value = {
        "id": "session_1",
        "state": {},
    }

    response = client.post("/api/agent/sessions")

    assert response.status_code == 200
    assert response.json() == {
        "id": "session_1",
        "appName": "ads_x_template",
        "userId": "1",
        "lastUpdateTime": None,
        "state": {},
        "events": None,
    }


@pytest.mark.anyio
async def test_get_session_messages_success(mock_reasoning_engine, client):
    mock_reasoning_engine.get_session.return_value = {
        "id": "session_1",
        "state": {},
        "lastUpdateTime": None,
        "events": [],
    }

    response = client.get("/api/agent/sessions/session_1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "session_1",
        "appName": "ads_x_template",
        "userId": "1",
        "lastUpdateTime": None,
        "state": {},
        "events": [],
    }


@pytest.mark.anyio
async def test_delete_session_success(mock_reasoning_engine, client):
    mock_reasoning_engine.delete_session.return_value = None

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
async def test_chat_success(client, mock_db):
    # Mock Vertex AI stream query dependencies to avoid live GCP calls
    with patch(
        "src.agents.agent_controller.reasoning_engines.ReasoningEngine"
    ) as mock_engine:
        mock_instance = MagicMock()
        mock_engine.return_value = mock_instance
        mock_instance.resource_name = "dummy-resource"
        mock_instance.execution_api_client.stream_query_reasoning_engine.return_value = (
            []
        )

        payload = {
            "sessionId": "s1",
            "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
        }

        response = client.post("/api/agent/chat", json=payload)

        assert response.status_code == 200
        assert response.json() == {"status": "processing"}


@pytest.mark.anyio
async def test_get_session_detail_by_session_id(
    mock_reasoning_engine, mock_storyboard_repo, client
):
    # Mock reasoning engine
    mock_reasoning_engine.get_session.return_value = {
        "id": "s1",
        "state": {},
        "lastUpdateTime": None,
        "events": [],
    }

    # Mock storyboard repo find_by_workspace
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
    # Use standard dict representation to align with pydantic validation
    mock_storyboard_repo.find_by_workspace.return_value = [mock_storyboard]

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&session_id=s1"
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["session"]["id"] == "s1"
    assert res_data["storyboard"]["id"] == 123


@pytest.mark.anyio
async def test_get_session_detail_by_storyboard_id(
    mock_reasoning_engine, mock_storyboard_repo, client
):
    # Mock storyboard repo get_by_id_with_details
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
    mock_storyboard_repo.get_by_id_with_details.return_value = mock_storyboard

    # Mock reasoning engine
    mock_reasoning_engine.get_session.return_value = {
        "id": "s1",
        "state": {},
        "lastUpdateTime": None,
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
    mock_storyboard_repo, client
):
    mock_storyboard_repo.get_by_id_with_details.return_value = None

    response = client.get(
        "/api/agent/sessions/detail?workspace_id=1&storyboard_id=999"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Storyboard not found"


@pytest.mark.anyio
async def test_get_session_detail_unauthorized(mock_storyboard_repo, client):
    mock_storyboard = MagicMock()
    mock_storyboard.id = 123
    mock_storyboard.user_id = 999  # different user
    mock_storyboard_repo.get_by_id_with_details.return_value = mock_storyboard

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
