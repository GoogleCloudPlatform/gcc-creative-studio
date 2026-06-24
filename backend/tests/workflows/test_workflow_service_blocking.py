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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.cloud.workflows import executions_v1 as exec_v1

from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    NodeTypes,
    WorkflowModel,
)
from src.workflows.schema.workflow_run_model import (
    WorkflowRunStatusEnum,
)
from src.workflows.workflow_service import WorkflowService


@pytest.fixture(name="mock_workflow_repo")
def fixture_mock_workflow_repo():
    repo = AsyncMock()
    return repo


@pytest.fixture(name="mock_run_repo")
def fixture_mock_run_repo():
    repo = AsyncMock()
    return repo


@pytest.fixture(name="workflow_service")
def fixture_workflow_service(mock_workflow_repo, mock_run_repo):
    return WorkflowService(
        workflow_repository=mock_workflow_repo,
        workflow_run_repository=mock_run_repo,
        source_asset_service=MagicMock(),
    )


@pytest.fixture(name="sample_workflow_model")
def fixture_sample_workflow_model():
    return WorkflowModel(
        id="id-1234",
        user_id=1,
        name="Test Workflow",
        description="A test workflow",
        steps=[
            GenerateTextStep(
                step_id="step_1",
                type=NodeTypes.GENERATE_TEXT,
                inputs=GenerateTextInputs(prompt="Hello World"),
                settings=GenerateTextSettings(
                    model="gemini-1.5", temperature=0.7
                ),
            ),
        ],
    )


@pytest.mark.anyio
@patch("src.workflows.workflow_service.executions_v1.ExecutionsClient")
@patch("src.workflows.workflow_service.google.auth.default")
@patch("src.workflows.workflow_service.AuthorizedSession")
async def test_get_execution_details_blocks_event_loop(
    mock_auth_session_class,
    mock_auth_default,
    mock_exec_client_class,
    workflow_service,
    mock_run_repo,
    sample_workflow_model,
):
    # Mock ExecutionsClient to block on get_execution
    mock_client = MagicMock()
    mock_exec_client_class.return_value = mock_client
    
    def blocking_get_execution(*args, **kwargs):
        time.sleep(0.2)  # Blocking sleep
        mock_execution = MagicMock()
        mock_execution.name = (
            "projects/p/locations/l/workflows/w/executions/e-123"
        )
        mock_execution.state = exec_v1.Execution.State.SUCCEEDED
        mock_execution.argument = '{"arg1": "val1"}'
        mock_execution.result = '{"res1": "val1"}'
        mock_execution.start_time = MagicMock()
        mock_execution.end_time = MagicMock()
        return mock_execution

    mock_client.get_execution.side_effect = blocking_get_execution

    # Mock Auth for REST API
    mock_auth_default.return_value = (MagicMock(), "project-id")
    mock_session = MagicMock()
    mock_auth_session_class.return_value = mock_session
    
    def blocking_session_get(*args, **kwargs):
        time.sleep(0.2)  # Blocking sleep
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stepEntries": [{"step": "step_1", "state": "STATE_SUCCEEDED"}],
        }
        return mock_response

    mock_session.get.side_effect = blocking_session_get

    # Mock DB Snapshot (no block)
    mock_run = MagicMock()
    mock_run.id = "e-123"
    mock_run.workflow_snapshot = sample_workflow_model.model_dump(
        mode="json"
    )
    mock_run.status = WorkflowRunStatusEnum.RUNNING.value
    mock_run_repo.get_by_id.return_value = mock_run

    # Setup mock get_by_id in service fallback
    workflow_service.get_by_id = AsyncMock(
        return_value=sample_workflow_model
    )

    # Background task to check for interleaving
    bg_runs = []
    async def background_task():
        for _ in range(8):
            await asyncio.sleep(0.05)
            bg_runs.append(time.time())

    bg_promise = asyncio.create_task(background_task())
    
    start_time = time.time()
    # This should block for ~0.4s total (0.2s in get_execution, 0.2s in session.get)
    details = await workflow_service.get_execution_details(
        workflow_id="id-123",
        execution_id="e-123",
    )
    get_details_end = time.time()
    
    await bg_promise
    
    assert details is not None
    
    # If blocked, all bg runs should be after get_details_end
    blocked_runs = [t for t in bg_runs if t > get_details_end]
    
    assert len(blocked_runs) == len(bg_runs), "Expected event loop to be blocked during get_execution_details"
