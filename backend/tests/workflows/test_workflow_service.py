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


import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.users.user_model import UserModel
from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    ImageInputs,
    ImageSettings,
    ImageStep,
    NodeTypes,
    StepOutputReference,
    StepStatusEnum,
    WorkflowCreateDto,
    WorkflowModel,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepState,
    WorkflowRunModel,
    WorkflowRunStatusEnum,
)
from src.workflows.workflow_service import (
    WorkflowConflictError,
    WorkflowService,
)


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
    repo.create = AsyncMock(side_effect=lambda model: model)
    repo.get_by_id = AsyncMock()
    repo.update = AsyncMock()
    repo.count_active_by_workflow = AsyncMock(return_value=0)
    repo.list_by_workflow = AsyncMock(return_value=([], 0))
    repo.compute_queue_positions = AsyncMock(return_value={})
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

    @staticmethod
    def _find_step(steps: list[dict], name: str) -> dict:
        for entry in steps:
            if name in entry:
                return entry[name]
        raise KeyError(name)

    def test_generate_workflow_yaml(
        self, workflow_service, sample_workflow_model
    ):
        from src.config.config_service import config_service

        config_service.WORKFLOWS_LOCATION = "us-central1"

        yaml_output = workflow_service._generate_workflow_yaml(
            sample_workflow_model
        )

        # Parse YAML to verify v2 structure
        parsed = yaml.safe_load(yaml_output)

        assert "main" in parsed
        assert "is_transient" in parsed
        assert "params" in parsed["main"]
        assert "steps" in parsed["main"]

        main_steps = parsed["main"]["steps"]
        run_steps = self._find_step(main_steps, "run_steps")
        try_steps = run_steps["try"]["steps"]
        step_1 = self._find_step(try_steps, "step_1")["try"]
        assert step_1["call"] == "http.post"
        assert "args" in step_1
        assert "url" in step_1["args"]
        assert "body" in step_1["args"]
        assert step_1["args"]["body"]["step_id"] == "step_1"
        assert step_1["args"]["body"]["run_id"] == "${run_id}"

    def test_generate_workflow_yaml_with_image_step(self, workflow_service):
        from src.config.config_service import config_service

        config_service.WORKFLOWS_LOCATION = "us-central1"

        workflow_model = WorkflowModel(
            id="id-img-wf",
            user_id=1,
            name="Image Workflow",
            description="Workflow with Image step",
            steps=[
                ImageStep(
                    step_id="image_step_1",
                    type=NodeTypes.IMAGE,
                    inputs=ImageInputs(prompt="A futuristic flying car"),
                    settings=ImageSettings(
                        mode="generate_image",
                        model="gemini-3.1-flash-image",
                        aspect_ratio="16:9",
                    ),
                ),
            ],
        )

        yaml_output = workflow_service._generate_workflow_yaml(workflow_model)
        parsed = yaml.safe_load(yaml_output)

        main_steps = parsed["main"]["steps"]
        try_steps = self._find_step(main_steps, "run_steps")["try"]["steps"]
        image_step = self._find_step(try_steps, "image_step_1")["try"]
        assert image_step["call"] == "http.post"
        assert image_step["args"]["url"].endswith("/image")
        assert image_step["args"]["body"]["config"]["mode"] == "generate_image"

    def test_generate_workflow_yaml_with_generate_text_dynamic_variables(
        self, workflow_service
    ):
        from src.config.config_service import config_service

        config_service.WORKFLOWS_LOCATION = "us-central1"

        workflow_model = WorkflowModel(
            id="id-text-vars-wf",
            user_id=1,
            name="Text Variables Workflow",
            description="Workflow with Generate Text step using dynamic prompt variables",
            steps=[
                GenerateTextStep(
                    step_id="step_gen_text",
                    type=NodeTypes.GENERATE_TEXT,
                    inputs=GenerateTextInputs(
                        prompt="Create an image of a <animal> wearing a <outfit>",
                        animal="cat",
                        outfit=StepOutputReference(
                            step="step_outfit_source",
                            output="generated_text",
                        ),
                    ),
                    settings=GenerateTextSettings(
                        model="gemini-3-flash-preview",
                        temperature=0.7,
                    ),
                ),
            ],
        )

        yaml_output = workflow_service._generate_workflow_yaml(workflow_model)
        parsed = yaml.safe_load(yaml_output)

        main_steps = parsed["main"]["steps"]
        try_steps = self._find_step(main_steps, "run_steps")["try"]["steps"]
        step_entry = self._find_step(try_steps, "step_gen_text")["try"]
        assert step_entry["call"] == "http.post"
        assert step_entry["args"]["url"].endswith("/generate_text")
        inputs_body = step_entry["args"]["body"]["inputs"]
        assert (
            inputs_body["prompt"]
            == "Create an image of a <animal> wearing a <outfit>"
        )
        assert inputs_body["animal"] == "cat"
        assert (
            inputs_body["outfit"] == "${step_outfit_source_out.generated_text}"
        )

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.workflows_v1.WorkflowsClient")
    async def test_ensure_yaml_current_redeploys_when_outdated(
        self,
        mock_client_class,
        workflow_service,
        mock_workflow_repo,
        sample_workflow_model,
    ):
        from src.workflows.workflow_yaml_builder import YAML_VERSION

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock()
        mock_client.update_workflow.return_value = mock_operation

        # 1. Already current -> no GCP call or DB update.
        current_wf = sample_workflow_model.model_copy(
            update={"yaml_version": YAML_VERSION}
        )
        res = await workflow_service.ensure_yaml_current(current_wf)
        assert res.yaml_version == YAML_VERSION
        mock_client.update_workflow.assert_not_called()

        # 2. Outdated (None) passed by ID -> redeploys to GCP and updates DB.
        outdated_wf = sample_workflow_model.model_copy(
            update={"yaml_version": None}
        )
        mock_workflow_repo.get_by_id.return_value = outdated_wf
        mock_workflow_repo.update.return_value = outdated_wf.model_copy(
            update={"yaml_version": YAML_VERSION}
        )
        redeployed = await workflow_service.ensure_yaml_current("id-1234")
        assert redeployed.yaml_version == YAML_VERSION
        mock_client.update_workflow.assert_called_once()
        mock_workflow_repo.update.assert_awaited_once()

        # 3. Missing workflow ID -> raises ValueError.
        mock_workflow_repo.get_by_id.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await workflow_service.ensure_yaml_current("missing-wf")


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
    """Tests for execute_workflow / submit_run methods."""

    @pytest.mark.anyio
    async def test_execute_workflow_success(
        self,
        workflow_service,
        mock_run_repo,
        sample_workflow_model,
        sample_user,
    ):
        workflow_service.get_by_id = AsyncMock(
            return_value=sample_workflow_model
        )
        dispatched: list[tuple[str, int | None]] = []
        workflow_service._dispatch_hook = (
            lambda trigger, uid: dispatched.append((trigger, uid))
        )

        args = {"workspace_id": "1", "user_token": "should-be-stripped"}

        run = await workflow_service.execute_workflow(
            workflow_id="id-123",
            args=args,
            user=sample_user,
        )

        assert isinstance(run, WorkflowRunModel)
        assert run.workflow_id == "id-123"
        assert run.status == WorkflowRunStatusEnum.QUEUED
        assert run.queue_reason == QueueReasonEnum.WAITING_FOR_SLOT
        assert "user_token" not in run.input_args
        assert run.workflow_snapshot.get("yaml_version") is not None
        assert "step_1" in run.step_states
        workflow_service.get_by_id.assert_called_once_with("id-123")
        mock_run_repo.create.assert_called_once()
        assert dispatched == [("submit", sample_user.id)]


class TestGetExecutionDetails:
    """Tests for DB-only get_run_details method (spec §9.2, Q17a)."""

    @pytest.mark.anyio
    async def test_get_execution_details_success(
        self,
        workflow_service,
        mock_run_repo,
        sample_workflow_model,
    ):
        now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        run = WorkflowRunModel(
            id="e-123",
            workflow_id="id-123",
            user_id=1,
            workspace_id=1,
            status=WorkflowRunStatusEnum.COMPLETED,
            started_at=now,
            completed_at=now,
            workflow_snapshot=sample_workflow_model.model_dump(mode="json"),
            input_args={"arg1": "val1"},
            step_states={
                "step_1": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "hello world"},
                    started_at=now,
                    completed_at=now,
                )
            },
        )
        mock_run_repo.get_by_id.return_value = run

        details = await workflow_service.get_run_details(
            workflow_id="id-123",
            run_id="e-123",
            user_id=1,
        )

        assert details is not None
        assert details.status == WorkflowRunStatusEnum.COMPLETED
        assert len(details.step_entries) > 0
        step_1_entry = next(
            e for e in details.step_entries if e["step_id"] == "step_1"
        )
        assert step_1_entry["state"] == "STATE_SUCCEEDED"
        assert step_1_entry["step_outputs"] == {"generated_text": "hello world"}

        # Non-owner or empty step_states
        assert (
            await workflow_service.get_run_details(
                workflow_id="id-123", run_id="e-123", user_id=999
            )
            is None
        )
        empty_run = run.model_copy(update={"step_states": {}})
        mock_run_repo.get_by_id.return_value = empty_run
        empty_details = await workflow_service.get_run_details(
            workflow_id="id-123", run_id="e-123", user_id=1
        )
        assert empty_details is not None
        assert empty_details.step_entries == []

    @pytest.mark.anyio
    async def test_get_execution_details_image_step_filtering(
        self,
        workflow_service,
        mock_run_repo,
    ):
        from src.workflows.schema.workflow_model import (
            UserInputInputs,
            UserInputSettings,
            UserInputStep,
        )

        image_workflow = WorkflowModel(
            id="wf-image",
            user_id=1,
            name="Image Workflow",
            description="Test image mode filtering",
            steps=[
                UserInputStep(
                    step_id="user_input",
                    type=NodeTypes.USER_INPUT,
                    inputs=UserInputInputs(),
                    settings=UserInputSettings(),
                ),
                ImageStep(
                    step_id="img_step",
                    type=NodeTypes.IMAGE,
                    inputs=ImageInputs(
                        prompt="A majestic eagle",
                        input_images=None,
                        input_image=None,
                        model_image=None,
                    ),
                    settings=ImageSettings(mode="generate_image"),
                ),
                ImageStep(
                    step_id="upscale_step",
                    type=NodeTypes.IMAGE,
                    inputs=ImageInputs(
                        prompt=None,
                        input_image=555,
                        model_image=None,
                    ),
                    settings=ImageSettings(mode="upscale_image"),
                ),
            ],
        )

        now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        run = WorkflowRunModel(
            id="e-456",
            workflow_id="wf-image",
            user_id=1,
            status=WorkflowRunStatusEnum.COMPLETED,
            started_at=now,
            workflow_snapshot=image_workflow.model_dump(
                mode="json", by_alias=True
            ),
            input_args={},
            step_states={
                "img_step": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_image": 111, "image_output": 111},
                ),
                "upscale_step": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"upscaled_image": 222, "image_output": 222},
                ),
            },
        )
        mock_run_repo.get_by_id.return_value = run

        details = await workflow_service.get_run_details(
            workflow_id="wf-image",
            run_id="e-456",
            user_id=1,
        )

        assert details is not None
        step_entries = details.step_entries
        img_entry = next(e for e in step_entries if e["step_id"] == "img_step")
        upscale_entry = next(
            e for e in step_entries if e["step_id"] == "upscale_step"
        )

        assert img_entry["step_inputs"] == {"prompt": "A majestic eagle"}
        assert img_entry["step_outputs"] == {"generated_image": 111}
        assert upscale_entry["step_inputs"] == {"input_image": 555}
        assert upscale_entry["step_outputs"] == {"generated_image": 222}

    @pytest.mark.anyio
    async def test_get_execution_details_video_step_reference_resolution(
        self,
        workflow_service,
        mock_run_repo,
    ):
        from src.workflows.schema.workflow_model import (
            GenerateVideoInputs,
            GenerateVideoSettings,
            GenerateVideoStep,
            UserInputInputs,
            UserInputSettings,
            UserInputStep,
        )

        video_workflow = WorkflowModel(
            id="wf-video",
            user_id=1,
            name="Video Workflow",
            description="Test video reference resolution",
            steps=[
                UserInputStep(
                    step_id="user_input",
                    type=NodeTypes.USER_INPUT,
                    inputs=UserInputInputs(),
                    settings=UserInputSettings(),
                ),
                GenerateVideoStep(
                    step_id="step_1",
                    type=NodeTypes.GENERATE_VIDEO,
                    inputs=GenerateVideoInputs(
                        prompt="A lion walking in savanna",
                    ),
                    settings=GenerateVideoSettings(
                        model="veo-3.1-generate-001",
                        brand_guidelines=False,
                        aspect_ratio="16:9",
                    ),
                ),
                GenerateVideoStep(
                    step_id="step_2",
                    type=NodeTypes.GENERATE_VIDEO,
                    inputs=GenerateVideoInputs(
                        prompt="add an elephant here",
                        input_video=StepOutputReference(
                            step="step_1", output="generated_video"
                        ),
                    ),
                    settings=GenerateVideoSettings(
                        model="veo-3.1-generate-001",
                        input_mode="Ingredients to Video",
                        brand_guidelines=False,
                        aspect_ratio="16:9",
                    ),
                ),
            ],
        )

        now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        run = WorkflowRunModel(
            id="e-789",
            workflow_id="wf-video",
            user_id=1,
            status=WorkflowRunStatusEnum.COMPLETED,
            started_at=now,
            workflow_snapshot=video_workflow.model_dump(
                mode="json", by_alias=True
            ),
            input_args={},
            step_states={
                "step_1": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_video": 888},
                ),
                "step_2": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_video": 999},
                ),
            },
        )
        mock_run_repo.get_by_id.return_value = run

        details = await workflow_service.get_run_details(
            workflow_id="wf-video",
            run_id="e-789",
            user_id=1,
        )

        assert details is not None
        step_entries = details.step_entries
        step_2_entry = next(e for e in step_entries if e["step_id"] == "step_2")

        assert step_2_entry["step_inputs"]["input_video"] == 888
        assert step_2_entry["step_inputs"]["prompt"] == "add an elephant here"
        assert step_2_entry["step_outputs"] == {"generated_video": 999}

    @pytest.mark.anyio
    async def test_get_execution_details_resolves_step_output_references(
        self,
        workflow_service,
        mock_run_repo,
    ):
        from src.workflows.schema.workflow_model import (
            UserInputInputs,
            UserInputSettings,
            UserInputStep,
        )

        wf_with_refs = WorkflowModel(
            id="wf-ref-test",
            user_id=1,
            name="Ref Test Workflow",
            description="Test resolving references from user input and steps",
            steps=[
                UserInputStep(
                    step_id="user_input",
                    type=NodeTypes.USER_INPUT,
                    inputs=UserInputInputs(),
                    settings=UserInputSettings(),
                    outputs={
                        "User_Text_Input": {
                            "type": "text",
                            "label": "User Text Input",
                        },
                    },
                ),
                ImageStep(
                    step_id="img_step",
                    type=NodeTypes.IMAGE,
                    inputs=ImageInputs(
                        prompt=StepOutputReference(
                            step="user_input",
                            output="User_Text_Input",
                        ),
                        input_images=None,
                        input_image=None,
                        model_image=None,
                    ),
                    settings=ImageSettings(mode="generate_image"),
                ),
            ],
        )

        now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        run = WorkflowRunModel(
            id="e-ref-1",
            workflow_id="wf-ref-test",
            user_id=1,
            status=WorkflowRunStatusEnum.COMPLETED,
            started_at=now,
            workflow_snapshot=wf_with_refs.model_dump(
                mode="json", by_alias=True
            ),
            input_args={
                "User_Text_Input": "A photo of a cyberpunk city at night"
            },
            step_states={
                "img_step": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_image": 777},
                ),
            },
        )
        mock_run_repo.get_by_id.return_value = run

        details = await workflow_service.get_run_details(
            workflow_id="wf-ref-test",
            run_id="e-ref-1",
            user_id=1,
        )

        assert details is not None
        step_entries = details.step_entries
        img_entry = next(e for e in step_entries if e["step_id"] == "img_step")

        assert img_entry["step_inputs"] == {
            "prompt": "A photo of a cyberpunk city at night",
        }

    @pytest.mark.anyio
    async def test_get_execution_details_resolves_generate_text_prompt_variables(
        self,
        workflow_service,
        mock_run_repo,
    ):
        from src.workflows.schema.workflow_model import (
            UserInputInputs,
            UserInputSettings,
            UserInputStep,
        )

        wf_with_vars = WorkflowModel(
            id="wf-text-vars",
            user_id=1,
            name="Text Variables Test Workflow",
            steps=[
                UserInputStep(
                    step_id="user_input",
                    type=NodeTypes.USER_INPUT,
                    inputs=UserInputInputs(),
                    settings=UserInputSettings(),
                ),
                GenerateTextStep(
                    step_id="text_step",
                    type=NodeTypes.GENERATE_TEXT,
                    inputs=GenerateTextInputs(
                        prompt="create a short story of a <animal> with a <color> hat",
                        animal="cat",
                        color="red",
                    ),
                    settings=GenerateTextSettings(
                        model="gemini-3-flash-preview",
                        temperature=0.7,
                    ),
                ),
            ],
        )

        now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        run = WorkflowRunModel(
            id="e-text-1",
            workflow_id="wf-text-vars",
            user_id=1,
            status=WorkflowRunStatusEnum.COMPLETED,
            started_at=now,
            workflow_snapshot=wf_with_vars.model_dump(
                mode="json", by_alias=True
            ),
            input_args={"workspace_id": 1},
            step_states={
                "text_step": StepState(
                    status=StepStatusEnum.COMPLETED,
                    outputs={"generated_text": "Barnaby was a cat..."},
                ),
            },
        )
        mock_run_repo.get_by_id.return_value = run

        details = await workflow_service.get_run_details(
            workflow_id="wf-text-vars",
            run_id="e-text-1",
            user_id=1,
        )

        assert details is not None
        step_entries = details.step_entries
        text_entry = next(
            e for e in step_entries if e["step_id"] == "text_step"
        )

        assert text_entry["step_inputs"] == {
            "prompt": "create a short story of a cat with a red hat",
            "animal": "cat",
            "color": "red",
        }

    def test_interpolate_prompt_variables(self, workflow_service):
        prompt = "Hello <name>, your score is <score>. Missing: <missing>."
        inputs = {
            "name": "Alice",
            "score": 100,
            "extra": "ignored",
        }
        resolved = workflow_service._interpolate_prompt_variables(
            prompt, inputs
        )
        assert resolved == "Hello Alice, your score is 100. Missing: <missing>."

    def test_interpolate_prompt_variables_dict_values(self, workflow_service):
        prompt = "Generated: <gen_text> and Text: <text_only> and Empty: <empty_dict>"
        inputs = {
            "gen_text": {"generated_text": "sample output"},
            "text_only": {"text": "plain output"},
            "empty_dict": {},
        }
        resolved = workflow_service._interpolate_prompt_variables(
            prompt, inputs
        )
        assert (
            resolved
            == "Generated: sample output and Text: plain output and Empty: "
        )


class TestBatchExecuteWorkflow:
    """Tests for batch_execute_workflow method."""

    @pytest.mark.anyio
    async def test_batch_execute_success(
        self, workflow_service, sample_user, sample_workflow_model
    ):
        from src.workflows.dto.batch_execution_dto import (
            BatchExecutionItemDto,
            BatchExecutionRequestDto,
        )

        workflow_service.get_by_id = AsyncMock(
            return_value=sample_workflow_model
        )
        dispatched: list[tuple[str, int | None]] = []
        workflow_service._dispatch_hook = (
            lambda trigger, uid: dispatched.append((trigger, uid))
        )

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
        assert response.results[0].run_id is not None
        assert response.results[0].run_status == "queued"
        assert response.results[1].status == "SUCCESS"
        # Single dispatcher trigger at the end of the batch!
        assert dispatched == [("batch_submit", sample_user.id)]

    @pytest.mark.anyio
    async def test_batch_execute_gcs_ingestion_success(
        self,
        workflow_service,
        sample_user,
        sample_workflow_model,
    ):
        from src.workflows.dto.batch_execution_dto import (
            BatchExecutionItemDto,
            BatchExecutionRequestDto,
        )

        workflow_service.get_by_id = AsyncMock(
            return_value=sample_workflow_model
        )

        mock_asset = MagicMock()
        mock_asset.id = 100
        workflow_service.source_asset_service.create_from_gcs_uri = AsyncMock(
            return_value=mock_asset,
        )

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
        assert response.results[0].run_id is not None
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

        workflow_service.submit_run = AsyncMock()

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
        workflow_service.submit_run.assert_not_called()


class TestListRuns:
    """Tests for DB-only list_runs method (spec §9.2, Q4)."""

    @pytest.mark.anyio
    async def test_list_runs_attaches_queue_positions(
        self, workflow_service, mock_run_repo
    ):
        now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
        queued_run = WorkflowRunModel(
            id="run-q1",
            workflow_id="id-123",
            user_id=1,
            status=WorkflowRunStatusEnum.QUEUED,
            started_at=now,
            queued_at=now,
            queue_reason=QueueReasonEnum.WAITING_FOR_SLOT,
            workflow_snapshot={"name": "WF", "steps": []},
        )
        completed_run = WorkflowRunModel(
            id="run-c1",
            workflow_id="id-123",
            user_id=1,
            status=WorkflowRunStatusEnum.COMPLETED,
            started_at=now,
            completed_at=now,
            workflow_snapshot={"name": "WF", "steps": []},
        )
        mock_run_repo.list_by_workflow.return_value = (
            [queued_run, completed_run],
            2,
        )
        mock_run_repo.compute_queue_positions.return_value = {"run-q1": 3}

        result = await workflow_service.list_runs(
            workflow_id="id-123", user_id=1, limit=20, offset=0
        )

        assert result.count == 2
        assert len(result.data) == 2
        assert result.data[0].id == "run-q1"
        assert result.data[0].queue_position == 3
        assert result.data[1].id == "run-c1"
        assert result.data[1].queue_position is None


class TestUpdateAndUpdateMethods:
    """Tests for update, delete, 409 active-run guards, resume_run, and cancel_run."""

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
    async def test_update_and_delete_raise_409_when_active_runs_exist(
        self,
        workflow_service,
        mock_run_repo,
        sample_workflow_create_dto,
        sample_user,
    ):
        mock_run_repo.count_active_by_workflow.return_value = 2
        with pytest.raises(
            WorkflowConflictError, match="while runs are queued or running"
        ):
            await workflow_service.update_workflow(
                workflow_id="id-123",
                workflow_dto=sample_workflow_create_dto,
                user=sample_user,
            )
        with pytest.raises(
            WorkflowConflictError, match="while runs are queued or running"
        ):
            await workflow_service.delete_by_id(workflow_id="id-123")

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


class TestWorkflowValidation:
    """Tests for validate_workflow method."""

    def test_validate_workflow_success(
        self,
        workflow_service,
        sample_workflow_create_dto,
        sample_user,
    ):
        result = workflow_service.validate_workflow(
            sample_workflow_create_dto,
            sample_user,
        )
        assert result["valid"] is True
        assert "valid" in result["message"].lower()

    def test_validate_workflow_cycle_raises_value_error(
        self,
        workflow_service,
        sample_user,
    ):
        cycle_dto = WorkflowCreateDto(
            name="Cyclic",
            steps=[
                GenerateTextStep(
                    step_id="step_a",
                    type=NodeTypes.GENERATE_TEXT,
                    inputs=GenerateTextInputs(
                        prompt=StepOutputReference(
                            step="step_b", output="generated_text"
                        )
                    ),
                    settings=GenerateTextSettings(
                        model="gemini-1.5", temperature=0.7
                    ),
                ),
                GenerateTextStep(
                    step_id="step_b",
                    type=NodeTypes.GENERATE_TEXT,
                    inputs=GenerateTextInputs(
                        prompt=StepOutputReference(
                            step="step_a", output="generated_text"
                        )
                    ),
                    settings=GenerateTextSettings(
                        model="gemini-1.5", temperature=0.7
                    ),
                ),
            ],
        )
        with pytest.raises(ValueError, match="Cycle detected"):
            workflow_service.validate_workflow(cycle_dto, sample_user)

    def test_validate_workflow_does_not_persist_or_call_gcp(
        self,
        workflow_service,
        sample_workflow_create_dto,
        sample_user,
        mock_workflow_repo,
    ):
        workflow_service.validate_workflow(
            sample_workflow_create_dto,
            sample_user,
        )
        mock_workflow_repo.create.assert_not_called()
        mock_workflow_repo.update.assert_not_called()


class TestWorkflowCollapsedState:
    """Tests for persisting and retrieving collapsed node state in workflows."""

    @pytest.mark.anyio
    @patch("src.workflows.workflow_service.workflows_v1.WorkflowsClient")
    async def test_create_update_get_workflow_preserves_collapsed_state(
        self,
        mock_client_class,
        workflow_service,
        mock_workflow_repo,
        sample_user,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock()
        mock_client.create_workflow.return_value = mock_operation
        mock_client.update_workflow.return_value = mock_operation

        step_collapsed = GenerateTextStep(
            step_id="step_collapsed",
            type=NodeTypes.GENERATE_TEXT,
            collapsed=True,
            inputs=GenerateTextInputs(prompt="Collapsed step prompt"),
            settings=GenerateTextSettings(model="gemini-1.5", temperature=0.7),
        )
        dto = WorkflowCreateDto(
            name="Collapsed Workflow",
            description="Workflow with a collapsed node",
            steps=[step_collapsed],
        )

        # Create
        mock_workflow_repo.create.side_effect = lambda model: model
        created = await workflow_service.create_workflow(dto, sample_user)
        assert len(created.steps) == 1
        assert created.steps[0].collapsed is True

        # Update
        step_updated = GenerateTextStep(
            step_id="step_collapsed",
            type=NodeTypes.GENERATE_TEXT,
            collapsed=True,
            inputs=GenerateTextInputs(prompt="Updated prompt"),
            settings=GenerateTextSettings(model="gemini-1.5", temperature=0.7),
        )
        update_dto = WorkflowCreateDto(
            name="Collapsed Workflow Updated",
            description="Updated description",
            steps=[step_updated],
        )
        mock_workflow_repo.update.side_effect = lambda wf_id, model: model
        updated = await workflow_service.update_workflow(
            created.id, update_dto, sample_user
        )
        assert updated is not None
        assert updated.steps[0].collapsed is True

        # Retrieve
        mock_workflow_repo.get_by_id.return_value = updated
        fetched = await workflow_service.get_workflow(
            sample_user.id, created.id
        )
        assert fetched is not None
        assert fetched.steps[0].collapsed is True
