# Copyright 2026 Google LLC
# ... License ...

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


@pytest.fixture(name="client")
def fixture_client(mock_user, mock_db, mock_workspace_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    from src.workspaces.workspace_service import WorkspaceService

    app.dependency_overrides[WorkspaceService] = lambda: mock_workspace_service
    return TestClient(app)


@pytest.mark.anyio
@patch("src.agents.agent_controller.httpx.AsyncClient")
async def test_get_sessions_success(mock_async_client, client):
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"id": "session_1", "appName": "creative_toolbox", "userId": "1"}
    ]
    mock_client.get.return_value = mock_response
    mock_async_client.return_value.__aenter__.return_value = mock_client

    response = client.get("/api/agent/sessions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "session_1",
            "appName": "creative_toolbox",
            "userId": "1",
            "lastUpdateTime": None,
            "state": None,
            "events": None,
        }
    ]


@pytest.mark.anyio
@patch("src.agents.agent_controller.httpx.AsyncClient")
async def test_create_session_success(mock_async_client, client):
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "session_1",
        "appName": "creative_toolbox",
        "userId": "1",
    }
    mock_client.post.return_value = mock_response
    mock_async_client.return_value.__aenter__.return_value = mock_client

    response = client.post("/api/agent/sessions")

    assert response.status_code == 200
    assert response.json() == {
        "id": "session_1",
        "appName": "creative_toolbox",
        "userId": "1",
        "lastUpdateTime": None,
        "state": None,
        "events": None,
    }


@pytest.mark.anyio
@patch("src.agents.agent_controller.httpx.AsyncClient")
async def test_get_session_messages_success(mock_async_client, client):
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "session_1",
        "appName": "creative_toolbox",
        "userId": "1",
    }
    mock_client.get.return_value = mock_response
    mock_async_client.return_value.__aenter__.return_value = mock_client

    response = client.get("/api/agent/sessions/session_1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "session_1",
        "appName": "creative_toolbox",
        "userId": "1",
        "lastUpdateTime": None,
        "state": None,
        "events": None,
    }


@pytest.mark.anyio
@patch("src.agents.agent_controller.httpx.AsyncClient")
async def test_delete_session_success(mock_async_client, client):
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "deleted"}
    mock_client.delete.return_value = mock_response
    mock_async_client.return_value.__aenter__.return_value = mock_client

    response = client.delete("/api/agent/sessions/session_1")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}


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
@patch("src.agents.agent_controller.httpx.AsyncClient")
async def test_chat_success(mock_async_client, client, mock_db):
    # This tests the endpoint returns immediately with processing status
    mock_client = AsyncMock()
    mock_async_client.return_value.__aenter__.return_value = mock_client

    payload = {
        "sessionId": "s1",
        "newMessage": {"role": "user", "parts": [{"text": "hello"}]},
    }

    response = client.post("/api/agent/chat", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "processing"}
