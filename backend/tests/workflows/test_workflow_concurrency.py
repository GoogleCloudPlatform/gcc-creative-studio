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
"""Tests to verify concurrency issues in Workflow Service batch execution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.users.user_model import UserModel
from src.workflows.dto.batch_execution_dto import (
    BatchExecutionItemDto,
    BatchExecutionRequestDto,
)
from src.workflows.repository.workflow_repository import WorkflowRepository
from src.workflows.repository.workflow_run_repository import (
    WorkflowRunRepository,
)
from src.workflows.schema.workflow_model import Workflow, WorkflowModel
from src.workflows.workflow_service import WorkflowService


class ConcurrencyDetectingSession:
    """A mock-like session that raises an error if async methods are called concurrently."""

    def __init__(self, mock_workflow_db_item):
        self.active_calls = 0
        self.mock_workflow_db_item = mock_workflow_db_item

    async def _enter_call(self):
        if self.active_calls > 0:
            raise RuntimeError(
                "CONCURRENCY DETECTED: AsyncSession method called concurrently!"
            )
        self.active_calls += 1

    async def _exit_call(self):
        self.active_calls -= 1

    async def execute(self, *args, **kwargs):
        await self._enter_call()
        try:
            await asyncio.sleep(0.05)  # Simulate network latency to ensure overlap
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = (
                self.mock_workflow_db_item
            )
            return mock_result
        finally:
            await self._exit_call()

    async def commit(self, *args, **kwargs):
        await self._enter_call()
        try:
            await asyncio.sleep(0.05)
        finally:
            await self._exit_call()

    async def refresh(self, *args, **kwargs):
        await self._enter_call()
        try:
            await asyncio.sleep(0.05)
        finally:
            await self._exit_call()

    def add(self, *args, **kwargs):
        # add is synchronous, but we can check if it's called during an active async call
        if self.active_calls > 0:
            raise RuntimeError(
                "CONCURRENCY DETECTED: session.add called during active async operation!"
            )


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.mark.anyio
@patch("src.workflows.workflow_service.executions_v1.ExecutionsAsyncClient")
async def test_batch_execute_concurrency_issue(
    mock_exec_client_class,
    sample_user,
):
    # 1. Setup mock GCP response
    mock_exec_client = AsyncMock()
    mock_exec_client_class.return_value = mock_exec_client
    mock_response = MagicMock()
    mock_response.name = (
        "projects/p/locations/l/workflows/w/executions/exec-123"
    )
    mock_exec_client.create_execution.return_value = mock_response

    # 2. Setup mock Workflow DB item for get_by_id
    import datetime
    now = datetime.datetime.now(datetime.UTC)
    db_workflow = Workflow(
        id="id-123",
        user_id=sample_user.id,
        name="Test Workflow",
        steps=[
            {
                "step_id": "step1",
                "type": "user_input",
                "inputs": {},
                "settings": {},
            }
        ],
        created_at=now,
        updated_at=now,
    )


    # 3. Setup Concurrency Detecting Session
    detecting_session = ConcurrencyDetectingSession(db_workflow)

    # 4. Instantiate repositories with the detecting session
    # We cast detecting_session to Any to satisfy type checker (it expects AsyncSession)
    workflow_repo = WorkflowRepository(db=detecting_session)  # type: ignore
    workflow_run_repo = WorkflowRunRepository(db=detecting_session)  # type: ignore

    # 5. Instantiate service
    service = WorkflowService(
        workflow_repository=workflow_repo,
        workflow_run_repository=workflow_run_repo,
        source_asset_service=MagicMock(),  # Not used for non-GCS args
    )

    # 6. Prepare Batch Request (2 items to trigger concurrency)
    batch_dto = BatchExecutionRequestDto(
        items=[
            BatchExecutionItemDto(row_index=0, args={"param": "val1"}),
            BatchExecutionItemDto(row_index=1, args={"param": "val2"}),
        ]
    )

    # 7. Execute
    # We expect this to fail because ConcurrencyDetectingSession will raise RuntimeError
    # when the second task tries to call execute/commit/refresh while the first is sleeping.
    
    # Actually, batch_execute_workflow catches exceptions inside process_row and returns them in results.
    # So we should check the results for failures.
    response = await service.batch_execute_workflow(
        workflow_id="id-123",
        batch_dto=batch_dto,
        user=sample_user,
    )

    assert response is not None
    assert len(response.results) == 2
    
    # If concurrency issue exists, at least one of them should have failed with our RuntimeError
    failed_results = [r for r in response.results if r.status == "FAILED"]
    
    print("\nBatch execution results:")
    for r in response.results:
        print(f"Row {r.row_index}: {r.status} (Error: {r.error})")
        
    assert len(failed_results) > 0, "Expected at least one failure due to concurrency"
    assert any("CONCURRENCY DETECTED" in str(r.error) for r in failed_results), "Expected concurrency error in results"
