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

from pydantic import TypeAdapter

from src.workflows.schema.workflow_model import (
    ImageInputs,
    ImageSettings,
    ImageStep,
    NodeTypes,
    WorkflowStep,
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
