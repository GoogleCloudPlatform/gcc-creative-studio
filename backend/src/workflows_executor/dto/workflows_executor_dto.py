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

"""Request bodies of the workflows executor step routes."""

from pydantic import BaseModel, Field, model_validator

from src.workflows.schema.workflow_model import (
    GenerateAudioInputs,
    GenerateAudioSettings,
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateVideoInputs,
    GenerateVideoSettings,
    ImageInputs,
    ImageSettings,
    LoopSettings,
)

# Run ids are UUIDs or GCP execution ids; step ids are editor node ids.
# '#' is rejected: it separates '<step_id>#<iteration>' step state keys.
_KEY_PATTERN = r"^[A-Za-z0-9_-]*$"
_KEY_MAX_LENGTH = 128
# Upper bound of a loop iteration index (MAX_LOOP_ITEMS is far below).
MAX_ITERATION_INDEX = 1000
# Bound of the raw comma-separated text of a text_input Loop step.
MAX_LOOP_ITEMS_TEXT_LENGTH = 100_000


class StepCallContext(BaseModel):
    """Optional checkpoint / idempotency key of a workflow step call.

    Sent by the generated YAML. Calls without ``run_id`` (missing or empty,
    e.g. executions started before the queue existed) run without
    checkpoint or idempotency. Loop body calls send ``iteration`` and are
    checkpointed under ``"<step_id>#<iteration>"``.
    """

    run_id: str | None = Field(
        default=None, max_length=_KEY_MAX_LENGTH, pattern=_KEY_PATTERN
    )
    step_id: str | None = Field(
        default=None, max_length=_KEY_MAX_LENGTH, pattern=_KEY_PATTERN
    )
    execution_id: str | None = Field(
        default=None, max_length=_KEY_MAX_LENGTH, pattern=_KEY_PATTERN
    )
    iteration: int | None = Field(default=None, ge=0, le=MAX_ITERATION_INDEX)

    @model_validator(mode="after")
    def _require_step_id_with_run_id(self) -> "StepCallContext":
        if self.run_id and not self.step_id:
            raise ValueError("step_id is required when run_id is set")
        return self


class GenerateTextRequest(StepCallContext):
    inputs: GenerateTextInputs
    config: GenerateTextSettings


class ImageStepRequest(StepCallContext):
    workspace_id: int
    inputs: ImageInputs
    config: ImageSettings


class GenerateVideoRequest(StepCallContext):
    workspace_id: int
    inputs: GenerateVideoInputs
    config: GenerateVideoSettings


class GenerateAudioRequest(StepCallContext):
    workspace_id: int
    inputs: GenerateAudioInputs
    config: GenerateAudioSettings


class ResolveLoopItemsInputs(BaseModel):
    """Resolved inputs of a ``Loop`` step (``loop_ending`` is a back-edge
    and never sent)."""

    items_text: str | None = Field(
        default=None, max_length=MAX_LOOP_ITEMS_TEXT_LENGTH
    )


class ResolveLoopItemsRequest(StepCallContext):
    workspace_id: int
    inputs: ResolveLoopItemsInputs = Field(
        default_factory=ResolveLoopItemsInputs
    )
    config: LoopSettings
