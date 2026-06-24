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
"""Tests for Workflow Repository."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.workflows.dto.workflow_search_dto import WorkflowSearchDto
from src.workflows.repository.workflow_repository import WorkflowRepository
from src.workflows.schema.workflow_model import Workflow


def get_dummy_workflow(**kwargs):
    now = datetime.datetime.now(datetime.UTC)
    defaults = {
        "id": "wf-123",
        "user_id": 1,
        "name": "Test Workflow",
        "description": "A test workflow",
        "steps": [
            {
                "step_id": "step1",
                "type": "user_input",
                "inputs": {},
                "settings": {},
            }
        ],
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    return Workflow(**defaults)


@pytest.mark.anyio
async def test_query_no_filters():
    mock_db = AsyncMock()

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 3

    mock_workflows_result = MagicMock()
    mock_wf = get_dummy_workflow(id="wf-1")
    mock_workflows_result.scalars().all.return_value = [mock_wf]

    mock_db.execute.side_effect = [mock_count_result, mock_workflows_result]

    repo = WorkflowRepository(db=mock_db)
    search_dto = WorkflowSearchDto(limit=10, offset=0)
    response = await repo.query(user_id=1, search_dto=search_dto)

    assert response is not None
    assert response.count == 3
    assert response.page == 1
    assert response.page_size == 10
    assert response.total_pages == 1
    assert len(response.data) == 1
    assert response.data[0].id == "wf-1"

    assert mock_db.execute.call_count == 2


@pytest.mark.anyio
async def test_query_with_name_filter():
    mock_db = AsyncMock()

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1

    mock_workflows_result = MagicMock()
    mock_wf = get_dummy_workflow(id="wf-2", name="Specific Name")
    mock_workflows_result.scalars().all.return_value = [mock_wf]

    mock_db.execute.side_effect = [mock_count_result, mock_workflows_result]

    repo = WorkflowRepository(db=mock_db)
    search_dto = WorkflowSearchDto(name="Specific", limit=5, offset=0)
    response = await repo.query(user_id=1, search_dto=search_dto)

    assert response is not None
    assert response.count == 1
    assert response.page == 1
    assert response.page_size == 5
    assert response.total_pages == 1
    assert len(response.data) == 1
    assert response.data[0].name == "Specific Name"

    assert mock_db.execute.call_count == 2
