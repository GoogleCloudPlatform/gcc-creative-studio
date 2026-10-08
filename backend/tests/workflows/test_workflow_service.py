# Copyright 2025 Google LLC
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
"""Tests for Workflow Service."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.users.user_model import UserModel
from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    NodeTypes,
    WorkflowCreateDto,
    WorkflowModel,
)
from src.workflows.schema.workflow_run_model import (
    WorkflowRunStatusEnum,
)
from src.workflows.workflow_service import WorkflowService


@pytest.fixture(name="mock_workflow_repo")
def fixture_mock_workflow_repo():
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture(name="mock_run_repo")
def fixture_mock_run_repo():
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.update = AsyncMock()
    return repo


@pytest.fixture(name="workflow_service")
def fixture_workflow_service(mock_workflow_repo, mock_run_repo):
    # Pass None for source_asset_service for now as it's not used in basic tests
    return WorkflowService(
        workflow_repository=mock_workflow_repo,
        workflow_run_repository=mock_run_repo,
        source_asset_service=MagicMock(),
    )


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
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


@pytest.fixture(name="sample_workflow_create_dto")
def fixture_sample_workflow_create_dto():
    return WorkflowCreateDto(
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


class TestWorkflowServiceConfig:
    """Tests for basic workflow generation logic."""

    def test_generate_workflow_yaml(
        self, workflow_service, sample_workflow_model
    ):
        from src.config.config_service import config_service

        config_service.WORKFLOWS_LOCATION = "us-central1"

        yaml_output = workflow_service._generate_workflow_yaml(
            sample_workflow_model
        )

        # Parse YAML to verify structure
        parsed = yaml.safe_load(yaml_output)

        assert "main" in parsed
        assert "params" in parsed["main"]
        assert "steps" in parsed["main"]

        steps = parsed["main"]["steps"]
        assert len(steps) == 1

        step_1_wrapper = steps[0]
        assert "step_1" in step_1_wrapper

        step_1 = step_1_wrapper["step_1"]
        assert step_1["call"] == "http.post"
        assert "args" in step_1
        assert "url" in step_1["args"]
        assert "body" in step_1["args"]


class TestCreateWorkflow:
    """Tests for create_workflow method."""

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.workflows_v1.WorkflowsClient")
    async def test_create_workflow_success(
        self,
        mock_client_class,
        workflow_service,
        mock_workflow_repo,
        sample_workflow_create_dto,
        sample_user,
    ):
        # Mock GCP Client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock()
        mock_client.create_workflow.return_value = mock_operation

        # Mock DB Repo
        mock_workflow_repo.create.return_value = WorkflowModel(
            id="id-123",
            user_id=1,
            name="Test",
            steps=sample_workflow_create_dto.steps,
        )

        result = await workflow_service.create_workflow(
            sample_workflow_create_dto,
            sample_user,
        )

        assert result.id == "id-123"
        mock_workflow_repo.create.assert_called_once()
        mock_client.create_workflow.assert_called_once()

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.workflows_v1.WorkflowsClient")
    async def test_create_workflow_gcp_failure_rollback(
        self,
        mock_client_class,
        workflow_service,
        mock_workflow_repo,
        sample_workflow_create_dto,
        sample_user,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.create_workflow.side_effect = Exception("GCP Error")

        created_model = WorkflowModel(
            id="id-123",
            user_id=1,
            name="Test",
            steps=sample_workflow_create_dto.steps,
        )
        mock_workflow_repo.create.return_value = created_model

        with pytest.raises(Exception) as exc_info:
            await workflow_service.create_workflow(
                sample_workflow_create_dto,
                sample_user,
            )

        assert "GCP Error" in str(exc_info.value)
        mock_workflow_repo.create.assert_called_once()
        # Verify rollback (deletion) called
        mock_workflow_repo.delete.assert_called_once_with("id-123")


class TestExecuteWorkflow:
    """Tests for execute_workflow method."""

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.executions_v1.ExecutionsAsyncClient")
    async def test_execute_workflow_success(
        self,
        mock_exec_client_class,
        workflow_service,
        mock_workflow_repo,
        mock_run_repo,
        sample_workflow_model,
        sample_user,
    ):
        # Setup
        workflow_service.get_by_id = AsyncMock(
            return_value=sample_workflow_model
        )

        # Mock GCP Execution Client
        mock_exec_client = AsyncMock()
        mock_exec_client_class.return_value = mock_exec_client

        mock_response = MagicMock()
        mock_response.name = (
            "projects/p/locations/l/workflows/w/executions/exec-123"
        )
        mock_exec_client.create_workflow_execution = AsyncMock(
            return_value=mock_response,
        )
        # Wait, the method name in service is create_execution from AsyncClient
        mock_exec_client.create_execution = AsyncMock(
            return_value=mock_response
        )

        args = {"workspace_id": "1"}

        # Execute
        exec_id = await workflow_service.execute_workflow(
            workflow_id="id-123",
            args=args,
            user=sample_user,
        )

        assert exec_id == "exec-123"
        workflow_service.get_by_id.assert_called_once_with("id-123")
        mock_exec_client.create_execution.assert_called_once()
        mock_run_repo.create.assert_called_once()


class TestGetExecutionDetails:
    """Tests for get_execution_details method."""

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.executions_v1.ExecutionsClient")
    @patch("src.workflows.workflow_service.google.auth.default")
    @patch("src.workflows.workflow_service.AuthorizedSession")
    async def test_get_execution_details_success(
        self,
        mock_auth_session_class,
        mock_auth_default,
        mock_exec_client_class,
        workflow_service,
        mock_run_repo,
        sample_workflow_model,
    ):
        # Mock ExecutionsClient
        mock_client = MagicMock()
        mock_exec_client_class.return_value = mock_client
        mock_execution = MagicMock()
        mock_execution.name = (
            "projects/p/locations/l/workflows/w/executions/e-123"
        )
        # Setup State
        from google.cloud.workflows import executions_v1 as exec_v1

        mock_execution.state = exec_v1.Execution.State.SUCCEEDED
        mock_execution.argument = '{"arg1": "val1"}'
        mock_execution.result = '{"res1": "val1"}'
        mock_execution.start_time = MagicMock()
        mock_execution.end_time = MagicMock()
        mock_client.get_execution.return_value = mock_execution

        # Mock Auth for REST API
        mock_auth_default.return_value = (MagicMock(), "project-id")
        mock_session = MagicMock()
        mock_auth_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stepEntries": [{"step": "step_1", "state": "STATE_SUCCEEDED"}],
        }
        mock_session.get.return_value = mock_response

        # Mock DB Snapshot
        mock_run = MagicMock()
        mock_run.id = "e-123"
        mock_run.workflow_snapshot = sample_workflow_model.model_dump(
            mode="json"
        )
        # Ensure enum value string is passed
        mock_run.status = WorkflowRunStatusEnum.RUNNING.value
        mock_run_repo.get_by_id.return_value = mock_run

        # Setup mock get_by_id in service fallback
        workflow_service.get_by_id = AsyncMock(
            return_value=sample_workflow_model
        )

        # Execute
        details = await workflow_service.get_execution_details(
            workflow_id="id-123",
            execution_id="e-123",
        )

        assert details is not None
        assert details["state"] == "SUCCEEDED"
        assert len(details["step_entries"]) > 0

        # Verify lazy update was triggered (RUNNING -> SUCCEEDED transition)
        mock_run_repo.update.assert_called_once()


class TestBatchExecuteWorkflow:
    """Tests for batch_execute_workflow method."""

    @pytest.mark.anyio
    async def test_batch_execute_success(self, workflow_service, sample_user):
        from src.workflows.dto.batch_execution_dto import (
            BatchExecutionItemDto,
            BatchExecutionRequestDto,
        )

        # Mock execute_workflow
        workflow_service.execute_workflow = AsyncMock(return_value="exec-123")

        # Build DTO
        batch_dto = BatchExecutionRequestDto(
            items=[
                BatchExecutionItemDto(row_index=0, args={"prompt": "test1"}),
                BatchExecutionItemDto(row_index=1, args={"prompt": "test2"}),
            ],
        )

        response = await workflow_service.batch_execute_workflow(
            workflow_id="id-123",
            batch_dto=batch_dto,
            user=sample_user,
        )

        assert response is not None
        assert len(response.results) == 2
        assert response.results[0].status == "SUCCESS"
        assert response.results[0].execution_id == "exec-123"
        assert response.results[1].status == "SUCCESS"

    @pytest.mark.anyio
    async def test_batch_execute_gcs_ingestion_success(
        self,
        workflow_service,
        sample_user,
    ):
        from src.workflows.dto.batch_execution_dto import (
            BatchExecutionItemDto,
            BatchExecutionRequestDto,
        )

        # Mock execute_workflow
        workflow_service.execute_workflow = AsyncMock(return_value="exec-123")

        # Mock SourceAssetService
        mock_asset = MagicMock()
        mock_asset.id = 100
        workflow_service.source_asset_service.create_from_gcs_uri = AsyncMock(
            return_value=mock_asset,
        )

        # Build DTO with GCS URI
        batch_dto = BatchExecutionRequestDto(
            items=[
                BatchExecutionItemDto(
                    row_index=0,
                    args={"image": "gs://bucket/img.jpg", "workspace_id": "1"},
                ),
            ],
        )

        response = await workflow_service.batch_execute_workflow(
            workflow_id="id-123",
            batch_dto=batch_dto,
            user=sample_user,
        )

        assert response is not None
        assert len(response.results) == 1
        assert response.results[0].status == "SUCCESS"
        assert response.results[0].execution_id == "exec-123"

        # Verify GCS Ingestion was called
        workflow_service.source_asset_service.create_from_gcs_uri.assert_called_once()

    @pytest.mark.anyio
    async def test_batch_execute_gcs_ingestion_no_workspace_id_failure(
        self,
        workflow_service,
        sample_user,
    ):
        from src.workflows.dto.batch_execution_dto import (
            BatchExecutionItemDto,
            BatchExecutionRequestDto,
        )

        # Mock execute_workflow (should not be called)
        workflow_service.execute_workflow = AsyncMock()

        # Build DTO with GCS URI but NO workspace_id
        batch_dto = BatchExecutionRequestDto(
            items=[
                BatchExecutionItemDto(
                    row_index=0,
                    args={"image": "gs://bucket/img.jpg"},
                ),
            ],
        )

        response = await workflow_service.batch_execute_workflow(
            workflow_id="id-123",
            batch_dto=batch_dto,
            user=sample_user,
        )

        assert response is not None
        assert len(response.results) == 1
        assert response.results[0].status == "FAILED"
        assert "No workspace_id provided" in response.results[0].error

        # Verify execute_workflow was NOT called
        workflow_service.execute_workflow.assert_not_called()


class TestListExecutions:
    """Tests for list_executions method."""

    @patch("src.workflows.workflow_service.executions_v1.ExecutionsClient")
    def test_list_executions_success(
        self, mock_exec_client_class, workflow_service
    ):
        mock_client = MagicMock()
        mock_exec_client_class.return_value = mock_client

        mock_response = MagicMock()
        mock_page = MagicMock()
        mock_execution = MagicMock()
        mock_execution.name = (
            "projects/p/locations/l/workflows/w/executions/e-123"
        )

        # Setup State
        from google.cloud.workflows import executions_v1 as exec_v1

        mock_execution.state = exec_v1.Execution.State.SUCCEEDED
        mock_execution.start_time = MagicMock()
        mock_execution.end_time = MagicMock()

        mock_page.executions = [mock_execution]
        mock_page.next_page_token = "next_token"

        # Mock iterator
        mock_pages = MagicMock()
        mock_pages.__next__.return_value = mock_page
        mock_response.pages = mock_pages
        mock_client.list_executions.return_value = mock_response
        mock_client.workflow_path.return_value = (
            "projects/p/locations/l/workflows/w"
        )

        result = workflow_service.list_executions(workflow_id="id-123")

        assert result is not None
        assert "executions" in result
        assert len(result["executions"]) == 1
        assert result["executions"][0]["id"] == "e-123"
        assert result["next_page_token"] == "next_token"


class TestUpdateAndUpdateMethods:
    """Tests for update and delete methods."""

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.workflows_v1.WorkflowsClient")
    async def test_update_workflow_success(
        self,
        mock_client_class,
        workflow_service,
        mock_workflow_repo,
        sample_workflow_create_dto,
        sample_user,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock()
        mock_client.update_workflow.return_value = mock_operation

        updated_model = WorkflowModel(
            id="id-123",
            user_id=1,
            name="Updated",
            steps=sample_workflow_create_dto.steps,
        )
        mock_workflow_repo.update.return_value = updated_model

        result = await workflow_service.update_workflow(
            workflow_id="id-123",
            workflow_dto=sample_workflow_create_dto,
            user=sample_user,
        )

        assert result.name == "Updated"
        mock_workflow_repo.update.assert_called_once()
        mock_client.update_workflow.assert_called_once()

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.workflows_v1.WorkflowsClient")
    async def test_delete_by_id_success(
        self,
        mock_client_class,
        workflow_service,
        mock_workflow_repo,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock()
        mock_client.delete_workflow.return_value = mock_operation
        mock_client.workflow_path.return_value = "parent_path"

        mock_workflow_repo.delete.return_value = True

        result = await workflow_service.delete_by_id(workflow_id="id-123")

        assert result is True
        mock_workflow_repo.delete.assert_called_once()
        mock_client.delete_workflow.assert_called_once()
