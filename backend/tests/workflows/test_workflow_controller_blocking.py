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

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.workflow_controller import router
from src.workflows.workflow_service import WorkflowService


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    return UserModel(
        id=1,
        email="test@example.com",
        name="Test User",
        roles=[UserRoleEnum.WORKFLOWS],
    )


@pytest.fixture(name="mock_service")
def fixture_mock_service():
    service = AsyncMock()
    service.get_workflow = AsyncMock()
    # Synchronous method in service that we will mock to block
    service.list_executions = MagicMock()
    return service


@pytest.fixture(name="app")
def fixture_app(mock_user, mock_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[WorkflowService] = lambda: mock_service
    return app


@pytest.mark.anyio
async def test_list_executions_endpoint_blocks_event_loop(app, mock_service):
    mock_workflow = MagicMock()
    mock_workflow.user_id = 1
    mock_service.get_workflow.return_value = mock_workflow

    # Mock list_executions to block
    def blocking_list_executions(*args, **kwargs):
        time.sleep(0.2)  # Blocking sleep
        return [{"execution_id": "exec1"}]

    mock_service.list_executions.side_effect = blocking_list_executions

    # Background task to check for interleaving
    bg_runs = []
    async def background_task():
        for _ in range(4):
            await asyncio.sleep(0.05)
            bg_runs.append(time.time())

    # We need to run the client and the background task in the same event loop.
    # httpx.AsyncClient with ASGITransport runs the app in the same event loop.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        bg_promise = asyncio.create_task(background_task())
        
        start_time = time.time()
        # This request will trigger the blocking list_executions
        response = await ac.get("/api/workflows/wf1/executions")
        request_end = time.time()
        
        await bg_promise

    assert response.status_code == 200
    assert len(response.json()) == 1

    # If blocked, all bg runs should be after request_end
    blocked_runs = [t for t in bg_runs if t > request_end]
    
    assert len(blocked_runs) == len(bg_runs), "Expected event loop to be blocked during list_executions request"
