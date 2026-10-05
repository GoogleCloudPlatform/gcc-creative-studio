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
"""Unit tests for Workflow Schema & ImageStep model validation."""

import datetime
import importlib
import json

from pydantic import TypeAdapter

from src.workflows.queue.failure_classifier import ErrorCategory
from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    GenerateVideoInputs,
    GenerateVideoSettings,
    GenerateVideoStep,
    ImageInputs,
    ImageSettings,
    ImageStep,
    NodeTypes,
    StepOutputReference,
    StepStatusEnum,
    UserInputDefinition,
    UserInputSettings,
    UserInputStep,
    WorkflowRunStatusEnum,
    WorkflowStep,
)
from src.workflows.schema.workflow_run_model import (
    QueueReasonEnum,
    StepState,
    WorkflowRun,
    WorkflowRunExecution,
    WorkflowRunModel,
)


def test_image_step_default_creation():
    """Verify creating a default ImageStep with default inputs and settings."""
    step = ImageStep(
        step_id="step_image_1",
        inputs=ImageInputs(prompt="A beautiful sunset over mountains"),
        settings=ImageSettings(mode="generate_image"),
    )
    assert step.type == NodeTypes.IMAGE
    assert step.step_id == "step_image_1"
    assert step.inputs.prompt == "A beautiful sunset over mountains"
    assert step.settings.mode == "generate_image"
    assert step.settings.model == "gemini-3.1-flash-image"


def test_image_step_edit_mode():
    """Verify ImageStep configuration for edit_image mode."""
    step = ImageStep(
        step_id="step_edit_1",
        inputs=ImageInputs(
            prompt="Make the car red",
            input_images=123,
        ),
        settings=ImageSettings(
            mode="edit_image",
            aspect_ratio="16:9",
        ),
    )
    assert step.type == NodeTypes.IMAGE
    assert step.inputs.input_images == 123
    assert step.settings.mode == "edit_image"
    assert step.settings.aspect_ratio == "16:9"
    assert step.settings.resolution == "1K"


def test_image_step_auto_aspect_ratio_and_resolution():
    """Verify ImageStep configuration with auto aspect ratio and custom resolution."""
    step = ImageStep(
        step_id="step_auto_1",
        inputs=ImageInputs(
            prompt="Make the background dynamic",
            input_images=123,
        ),
        settings=ImageSettings(
            mode="edit_image",
            aspect_ratio="auto",
            resolution="4K",
        ),
    )
    assert step.type == NodeTypes.IMAGE
    assert step.settings.mode == "edit_image"
    assert step.settings.aspect_ratio == "auto"
    assert step.settings.resolution == "4K"


def test_image_step_upscale_mode():
    """Verify ImageStep configuration for upscale_image mode."""
    step = ImageStep(
        step_id="step_upscale_1",
        inputs=ImageInputs(input_image=456),
        settings=ImageSettings(
            mode="upscale_image",
            upscale_factor="x4",
            enhance_input_image=True,
            image_preservation_factor=0.8,
        ),
    )
    assert step.type == NodeTypes.IMAGE
    assert step.inputs.input_image == 456
    assert step.settings.mode == "upscale_image"
    assert step.settings.upscale_factor == "x4"
    assert step.settings.enhance_input_image is True
    assert step.settings.image_preservation_factor == 0.8


def test_image_step_vto_mode():
    """Verify ImageStep configuration for virtual_try_on mode."""
    step = ImageStep(
        step_id="step_vto_1",
        inputs=ImageInputs(
            model_image=100,
            top_image=101,
            bottom_image=102,
        ),
        settings=ImageSettings(mode="virtual_try_on"),
    )
    assert step.type == NodeTypes.IMAGE
    assert step.inputs.model_image == 100
    assert step.inputs.top_image == 101
    assert step.settings.mode == "virtual_try_on"


def test_workflow_step_discriminated_union_image_parsing():
    """Verify parsing serialized JSON through WorkflowStep discriminated union."""
    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "image_node_1",
        "type": "image",
        "status": "idle",
        "inputs": {"prompt": "A modern cityscape"},
        "settings": {"mode": "generate_image", "model": "gemini-3-pro-image"},
        "outputs": {},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, ImageStep)
    assert parsed.type == NodeTypes.IMAGE
    assert parsed.inputs.prompt == "A modern cityscape"
    assert parsed.settings.mode == "generate_image"


def test_workflow_base_translate_legacy_generate_image():
    """Verify legacy generate_image step is translated to ImageStep with mode=generate_image."""
    from src.workflows.schema.workflow_model import WorkflowBase

    legacy_data = {
        "name": "Legacy Workflow",
        "steps": [
            {
                "step_id": "legacy_gen_1",
                "type": "generate_image",
                "inputs": {"prompt": "A sunny day"},
                "settings": {
                    "model": "imagen-3",
                    "brand_guidelines": True,
                    "aspect_ratio": "16:9",
                    "resolution": "2K",
                },
                "outputs": {"image_output": 123},
            }
        ],
    }
    wf = WorkflowBase.model_validate(legacy_data)
    assert len(wf.steps) == 1
    step = wf.steps[0]
    assert isinstance(step, ImageStep)
    assert step.type == NodeTypes.IMAGE
    assert step.step_id == "legacy_gen_1"
    assert step.inputs.prompt == "A sunny day"
    assert step.settings.mode == "generate_image"
    assert step.settings.model == "imagen-3"
    assert step.settings.aspect_ratio == "16:9"
    assert step.settings.resolution == "2K"
    assert step.outputs == {"generated_image": 123}


def test_workflow_base_translate_legacy_edit_image():
    """Verify legacy edit_image step is translated to ImageStep with mode=edit_image."""
    from src.workflows.schema.workflow_model import WorkflowBase

    legacy_data = {
        "name": "Legacy Edit Workflow",
        "steps": [
            {
                "step_id": "legacy_edit_1",
                "type": "edit_image",
                "inputs": {
                    "prompt": "Add a rainbow",
                    "input_images": 999,
                },
                "settings": {
                    "model": "gemini-2.5-flash-image",
                    "aspect_ratio": "4:3",
                },
                "outputs": {"edited_image": 999},
            }
        ],
    }
    wf = WorkflowBase.model_validate(legacy_data)
    assert len(wf.steps) == 1
    step = wf.steps[0]
    assert isinstance(step, ImageStep)
    assert step.type == NodeTypes.IMAGE
    assert step.settings.mode == "edit_image"
    assert step.inputs.prompt == "Add a rainbow"
    assert step.inputs.input_images == 999
    assert step.outputs == {"generated_image": 999}


def test_workflow_base_translate_legacy_upscale_image():
    """Verify legacy upscale_image step is translated to ImageStep with mode=upscale_image."""
    from src.workflows.schema.workflow_model import WorkflowBase

    legacy_data = {
        "name": "Legacy Upscale Workflow",
        "steps": [
            {
                "step_id": "legacy_upscale_1",
                "type": "upscale_image",
                "inputs": {"input_image": 555},
                "settings": {
                    "upscale_factor": "x4",
                    "enhance_input_image": True,
                    "image_preservation_factor": 0.9,
                },
                "outputs": {"upscaled_image": 777},
            }
        ],
    }
    wf = WorkflowBase.model_validate(legacy_data)
    assert len(wf.steps) == 1
    step = wf.steps[0]
    assert isinstance(step, ImageStep)
    assert step.type == NodeTypes.IMAGE
    assert step.settings.mode == "upscale_image"
    assert step.inputs.input_image == 555
    assert step.settings.upscale_factor == "x4"
    assert step.settings.enhance_input_image is True
    assert step.settings.image_preservation_factor == 0.9
    assert step.outputs == {"generated_image": 777}


def test_workflow_base_translate_legacy_virtual_try_on():
    """Verify legacy virtual_try_on step is translated to ImageStep with mode=virtual_try_on."""
    from src.workflows.schema.workflow_model import WorkflowBase

    legacy_data = {
        "name": "Legacy VTO Workflow",
        "steps": [
            {
                "step_id": "legacy_vto_1",
                "type": "virtual_try_on",
                "inputs": {
                    "model_image": 11,
                    "top_image": 22,
                },
                "settings": {},
                "outputs": {"generated_image": 33},
            }
        ],
    }
    wf = WorkflowBase.model_validate(legacy_data)
    assert len(wf.steps) == 1
    step = wf.steps[0]
    assert isinstance(step, ImageStep)
    assert step.type == NodeTypes.IMAGE
    assert step.settings.mode == "virtual_try_on"
    assert step.inputs.model_image == 11
    assert step.inputs.top_image == 22
    assert step.outputs == {"generated_image": 33}


def test_generate_video_step_default_creation():
    """Verify creating a default GenerateVideoStep with default duration_seconds."""
    step = GenerateVideoStep(
        step_id="step_video_1",
        inputs=GenerateVideoInputs(prompt="A dog running on the beach"),
        settings=GenerateVideoSettings(
            model="veo-3.1-generate-001",
        ),
    )
    assert step.type == NodeTypes.GENERATE_VIDEO
    assert step.step_id == "step_video_1"
    assert step.inputs.prompt == "A dog running on the beach"
    assert step.settings.model == "veo-3.1-generate-001"
    assert step.settings.duration_seconds == 8
    assert step.settings.aspect_ratio == "16:9"
    assert step.settings.brand_guidelines is False
    assert step.settings.resolution == "1K"


def test_generate_video_step_custom_duration():
    """Verify creating a GenerateVideoStep with custom duration_seconds."""
    step = GenerateVideoStep(
        step_id="step_video_2",
        inputs=GenerateVideoInputs(prompt="A bird flying in slow motion"),
        settings=GenerateVideoSettings(
            model="veo-3.1-generate-001",
            brand_guidelines=True,
            aspect_ratio="9:16",
            duration_seconds=4,
            resolution="2K",
        ),
    )
    assert step.type == NodeTypes.GENERATE_VIDEO
    assert step.settings.duration_seconds == 4
    assert step.settings.aspect_ratio == "9:16"
    assert step.settings.resolution == "2K"
    assert step.settings.brand_guidelines is True


def test_workflow_step_discriminated_union_generate_video_parsing():
    """Verify parsing serialized GenerateVideoStep JSON through WorkflowStep discriminated union."""
    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "video_node_1",
        "type": "generate_video",
        "status": "idle",
        "inputs": {"prompt": "A sunset time-lapse"},
        "settings": {
            "model": "veo-3.1-fast-generate-001",
            "brand_guidelines": False,
            "aspect_ratio": "16:9",
            "duration_seconds": 6,
        },
        "outputs": {},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, GenerateVideoStep)
    assert parsed.type == NodeTypes.GENERATE_VIDEO
    assert parsed.inputs.prompt == "A sunset time-lapse"
    assert parsed.settings.duration_seconds == 6


def test_generate_video_step_with_video_and_audio_ingredients():
    """Verify GenerateVideoStep creation with input_video and input_audio."""
    from src.workflows.schema.workflow_model import (
        ReferenceMediaOrAsset,
        SourceMediaItemLink,
        StepOutputReference,
    )

    # 1. With StepOutputReference
    step_with_refs = GenerateVideoStep(
        step_id="step_video_ingredients_1",
        inputs=GenerateVideoInputs(
            prompt="A car driving through the rain",
            input_video=StepOutputReference(
                step="step_upstream_video", output="generated_video"
            ),
            input_audio=StepOutputReference(
                step="step_upstream_audio", output="generated_audio"
            ),
        ),
        settings=GenerateVideoSettings(
            model="veo-3.1-generate-001",
            brand_guidelines=False,
            aspect_ratio="16:9",
            input_mode="Ingredients to Video",
        ),
    )
    assert step_with_refs.type == NodeTypes.GENERATE_VIDEO
    assert isinstance(step_with_refs.inputs.input_video, StepOutputReference)
    assert step_with_refs.inputs.input_video.step == "step_upstream_video"
    assert step_with_refs.inputs.input_video.output == "generated_video"
    assert isinstance(step_with_refs.inputs.input_audio, StepOutputReference)
    assert step_with_refs.inputs.input_audio.step == "step_upstream_audio"
    assert step_with_refs.inputs.input_audio.output == "generated_audio"

    # 2. With ReferenceMediaOrAsset
    step_with_assets = GenerateVideoStep(
        step_id="step_video_ingredients_2",
        inputs=GenerateVideoInputs(
            prompt="A car driving through the rain",
            input_video=ReferenceMediaOrAsset(
                previewUrl="https://example.com/video.mp4",
                sourceMediaItem=SourceMediaItemLink(
                    mediaItemId=101, mediaIndex=0, role="video_reference_asset"
                ),
            ),
            input_audio=ReferenceMediaOrAsset(
                previewUrl="https://example.com/audio.wav",
                sourceAssetId=202,
            ),
        ),
        settings=GenerateVideoSettings(
            model="veo-3.1-generate-001",
            brand_guidelines=False,
            aspect_ratio="16:9",
        ),
    )
    assert isinstance(
        step_with_assets.inputs.input_video, ReferenceMediaOrAsset
    )
    assert (
        step_with_assets.inputs.input_video.sourceMediaItem.mediaItemId == 101
    )
    assert isinstance(
        step_with_assets.inputs.input_audio, ReferenceMediaOrAsset
    )
    assert step_with_assets.inputs.input_audio.sourceAssetId == 202

    # 3. With raw integer IDs
    step_with_ints = GenerateVideoStep(
        step_id="step_video_ingredients_3",
        inputs=GenerateVideoInputs(
            prompt="A car driving through the rain",
            input_video=301,
            input_audio=302,
        ),
        settings=GenerateVideoSettings(
            model="veo-3.1-generate-001",
            brand_guidelines=False,
            aspect_ratio="16:9",
        ),
    )
    assert step_with_ints.inputs.input_video == 301
    assert step_with_ints.inputs.input_audio == 302


def test_workflow_step_discriminated_union_generate_video_ingredients_parsing():
    """Verify parsing serialized GenerateVideoStep with video & audio ingredients via discriminated union."""
    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "video_ingredients_node",
        "type": "generate_video",
        "status": "idle",
        "inputs": {
            "prompt": "An astronaut walking on Mars",
            "input_video": {
                "step": "step_video_source",
                "output": "generated_video",
            },
            "input_audio": {
                "step": "step_audio_source",
                "output": "generated_audio",
            },
            "input_images": [
                {
                    "previewUrl": "https://example.com/img.png",
                    "sourceAssetId": 12,
                }
            ],
        },
        "settings": {
            "model": "veo-3.1-generate-001",
            "brand_guidelines": True,
            "aspect_ratio": "16:9",
            "duration_seconds": 8,
            "input_mode": "Ingredients to Video",
        },
        "outputs": {},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, GenerateVideoStep)
    assert parsed.type == NodeTypes.GENERATE_VIDEO
    assert parsed.inputs.input_video.step == "step_video_source"
    assert parsed.inputs.input_audio.step == "step_audio_source"
    assert parsed.settings.input_mode == "Ingredients to Video"


def test_user_input_step_with_video_definition():
    """Verify creating and parsing a UserInputStep with a video definition."""
    step = UserInputStep(
        step_id="user_input",
        settings=UserInputSettings(
            definitions=[
                UserInputDefinition(id="def-1", name="Prompt", type="text"),
                UserInputDefinition(
                    id="def-2", name="Input Video", type="video"
                ),
            ]
        ),
        outputs={
            "Prompt": {"type": "text"},
            "Input Video": {"type": "video"},
        },
    )
    assert step.type == NodeTypes.USER_INPUT
    assert len(step.settings.definitions) == 2
    assert step.settings.definitions[1].type == "video"
    assert step.outputs["Input Video"]["type"] == "video"

    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "user_input",
        "type": "user_input",
        "status": "idle",
        "inputs": {},
        "settings": {
            "definitions": [
                {"id": "def-vid", "name": "source_video", "type": "video"}
            ]
        },
        "outputs": {"source_video": {"type": "video"}},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, UserInputStep)
    assert parsed.settings.definitions[0].type == "video"


def test_generate_text_inputs_dynamic_variables():
    """Verify GenerateTextInputs accepts arbitrary extra variable fields."""
    inputs = GenerateTextInputs(
        prompt="Create an image of a <animal> wearing a <article_of_clothing>",
        animal="cat",
        article_of_clothing=StepOutputReference(
            step="user_input", output="clothing"
        ),
    )
    dumped = inputs.model_dump()
    assert dumped["prompt"] == (
        "Create an image of a <animal> wearing a <article_of_clothing>"
    )
    assert dumped["animal"] == "cat"
    assert dumped["article_of_clothing"] == {
        "step": "user_input",
        "output": "clothing",
    }


def test_generate_text_step_discriminated_union_dynamic_variables():
    """Verify parsing GenerateTextStep with extra dynamic variable inputs via discriminated union."""
    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "generate_text_node",
        "type": "generate_text",
        "status": "idle",
        "inputs": {
            "prompt": "Hello <name>, welcome to <location>!",
            "name": "Alice",
            "location": {
                "step": "step_location_gen",
                "output": "generated_text",
            },
        },
        "settings": {
            "model": "gemini-3-flash-preview",
            "temperature": 0.7,
        },
        "outputs": {"generated_text": {"type": "text"}},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, GenerateTextStep)
    assert parsed.type == NodeTypes.GENERATE_TEXT
    dumped = parsed.inputs.model_dump()
    assert dumped["name"] == "Alice"
    assert dumped["location"] == {
        "step": "step_location_gen",
        "output": "generated_text",
    }


def test_step_position_parsing_and_serialization():
    """Verify step position coordinates are parsed and serialized properly."""
    from src.workflows.schema.workflow_model import Point

    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "image_node_pos",
        "type": "image",
        "position": {"x": 240.5, "y": 180.0},
        "status": "idle",
        "inputs": {"prompt": "Test prompt"},
        "settings": {"mode": "generate_image"},
        "outputs": {},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, ImageStep)
    assert isinstance(parsed.position, Point)
    assert parsed.position.x == 240.5
    assert parsed.position.y == 180.0

    dumped = parsed.model_dump(by_alias=True)
    assert dumped["position"] == {"x": 240.5, "y": 180.0}

    # Verify default fallback when position is omitted
    raw_without_pos = {
        "stepId": "image_node_default_pos",
        "type": "image",
        "status": "idle",
        "inputs": {"prompt": "Default pos prompt"},
        "settings": {"mode": "generate_image"},
        "outputs": {},
    }
    parsed_default = adapter.validate_python(raw_without_pos)
    assert isinstance(parsed_default.position, Point)
    assert parsed_default.position.x == 100.0
    assert parsed_default.position.y == 100.0


def test_legacy_step_translation_preserves_position():
    """Verify legacy step translation preserves node position coordinates."""
    from src.workflows.schema.workflow_model import WorkflowBase

    legacy_data = {
        "name": "Legacy Workflow With Coords",
        "steps": [
            {
                "step_id": "legacy_gen_pos",
                "type": "generate_image",
                "position": {"x": 320, "y": 400},
                "inputs": {"prompt": "A sunny day"},
                "settings": {"model": "imagen-3"},
                "outputs": {},
            }
        ],
    }
    wf = WorkflowBase.model_validate(legacy_data)
    assert wf.steps[0].position is not None
    assert wf.steps[0].position.x == 320.0
    assert wf.steps[0].position.y == 400.0


def test_step_collapsed_default_and_preservation():
    """Verify collapsed defaults to False and collapsed=True is preserved across validation and serialization."""
    user_step = UserInputStep(step_id="user_1")
    text_step = GenerateTextStep(
        step_id="text_1",
        inputs=GenerateTextInputs(prompt="Test"),
        settings=GenerateTextSettings(
            model="gemini-3-flash-preview", temperature=0.7
        ),
    )
    image_step = ImageStep(
        step_id="img_1",
        inputs=ImageInputs(prompt="Test"),
        settings=ImageSettings(),
    )

    assert user_step.collapsed is False
    assert text_step.collapsed is False
    assert image_step.collapsed is False

    adapter = TypeAdapter(WorkflowStep)
    raw_data = {
        "stepId": "collapsed_node_1",
        "type": "image",
        "collapsed": True,
        "status": "idle",
        "inputs": {"prompt": "A collapsed node prompt"},
        "settings": {"mode": "generate_image"},
        "outputs": {},
    }
    parsed = adapter.validate_python(raw_data)
    assert isinstance(parsed, ImageStep)
    assert parsed.collapsed is True

    dumped = parsed.model_dump(by_alias=True)
    assert dumped["collapsed"] is True


def test_legacy_step_translation_preserves_collapsed():
    """Verify legacy step translation preserves collapsed state."""
    from src.workflows.schema.workflow_model import WorkflowBase

    legacy_data = {
        "name": "Legacy Workflow With Collapsed Node",
        "steps": [
            {
                "step_id": "legacy_gen_collapsed",
                "type": "generate_image",
                "collapsed": True,
                "inputs": {"prompt": "A sunny day"},
                "settings": {"model": "imagen-3"},
                "outputs": {},
            }
        ],
    }
    wf = WorkflowBase.model_validate(legacy_data)
    assert wf.steps[0].collapsed is True


# --- Workflow runs: statuses and queue / checkpoint columns -----

RUN_STARTED_AT = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
QUEUE_COLUMNS = (
    "input_args",
    "definition_hash",
    "queued_at",
    "dispatched_at",
    "queue_reason",
    "waiting_for_session_since",
    "session_wait_seconds",
    "current_step_id",
    "attempt_count",
    "next_retry_at",
    "last_error_category",
    "last_error_detail",
    "execution_ids",
    "step_states",
    "canceled_by_user",
)


def _run_row(**overrides) -> dict:
    row = {
        "id": "exec-1",
        "workflow_id": "wf-1",
        "user_id": 1,
        "workspace_id": None,
        "status": "needs_attention",
        "started_at": RUN_STARTED_AT,
        "completed_at": None,
        "workflow_snapshot": {"name": "Workflow", "steps": []},
    }
    row.update({column: None for column in QUEUE_COLUMNS})
    row.update(overrides)
    return row


def test_run_status_enum_has_no_failed_or_scheduled():
    assert {status.value for status in WorkflowRunStatusEnum} == {
        "queued",
        "running",
        "step_failed",
        "needs_attention",
        "completed",
        "canceled",
    }
    assert "FAILED" not in WorkflowRunStatusEnum.__members__
    assert "SCHEDULED" not in WorkflowRunStatusEnum.__members__


def test_duplicate_run_model_is_no_longer_in_workflow_model():
    module = importlib.import_module("src.workflows.schema.workflow_model")
    assert not hasattr(module, "WorkflowRunModel")


def test_run_model_maps_null_queue_columns_to_generic_defaults():
    run = WorkflowRunModel.model_validate(_run_row())

    # use_enum_values=True: enum fields hold their (str) values.
    assert run.status == WorkflowRunStatusEnum.NEEDS_ATTENTION
    assert run.input_args == {}
    assert run.step_states == {}
    assert run.execution_ids == []
    assert run.attempt_count == 0
    assert run.session_wait_seconds == 0
    for column in (
        "definition_hash",
        "queued_at",
        "dispatched_at",
        "queue_reason",
        "waiting_for_session_since",
        "current_step_id",
        "next_retry_at",
        "last_error_category",
        "last_error_detail",
        "canceled_by_user",
    ):
        assert getattr(run, column) is None, column


def test_run_model_reads_orm_rows_with_null_columns():
    orm_row = WorkflowRun(
        id="exec-2",
        workflow_id="wf-1",
        user_id=1,
        status="running",
        started_at=RUN_STARTED_AT,
        workflow_snapshot={"name": "Workflow", "steps": []},
    )

    run = WorkflowRunModel.model_validate(orm_row)

    assert run.status == WorkflowRunStatusEnum.RUNNING
    assert (run.input_args, run.step_states, run.execution_ids) == ({}, {}, [])
    assert (run.attempt_count, run.session_wait_seconds) == (0, 0)


def test_run_model_parses_and_dumps_checkpoint_data_as_json():
    run = WorkflowRunModel.model_validate(
        _run_row(
            status="queued",
            queue_reason="RETRY_SCHEDULED",
            last_error_category="QUOTA",
            attempt_count=2,
            execution_ids=[
                {"execution_id": "exec-1", "started_at": RUN_STARTED_AT}
            ],
            step_states={
                "image_1": {
                    "status": "completed",
                    "outputs": {"generated_image": 5},
                    "job_id": 5,
                    "attempts": None,
                    "completed_at": RUN_STARTED_AT,
                    "error": {"category": "QUOTA", "http_status": 429},
                }
            },
        )
    )

    assert run.queue_reason == QueueReasonEnum.RETRY_SCHEDULED
    assert run.last_error_category == ErrorCategory.QUOTA
    assert isinstance(run.execution_ids[0], WorkflowRunExecution)
    step = run.step_states["image_1"]
    assert isinstance(step, StepState)
    assert step.status == StepStatusEnum.COMPLETED
    assert step.attempts == 0
    assert step.in_progress_continuations == 0

    # Repositories write model_dump() output straight into JSONB columns.
    dumped = run.model_dump()
    assert dumped["execution_ids"] == [
        {"execution_id": "exec-1", "started_at": "2026-01-01T12:00:00Z"}
    ]
    assert dumped["step_states"]["image_1"] == {
        "status": "completed",
        "outputs": {"generated_image": 5},
        "attempts": 0,
        "in_progress_continuations": 0,
        "job_id": 5,
        "completed_at": "2026-01-01T12:00:00Z",
        "error": {"category": "QUOTA", "http_status": 429},
    }
    json.dumps(dumped["step_states"])


def test_step_state_defaults_and_json_output():
    state = StepState()
    assert state.status == StepStatusEnum.PENDING
    assert state.to_json() == {
        "status": "pending",
        "attempts": 0,
        "in_progress_continuations": 0,
    }
    state = StepState.model_validate(
        {"status": "running", "in_progress_continuations": None, "extra": 1}
    )
    assert state.in_progress_continuations == 0
    assert state.to_json()["extra"] == 1
