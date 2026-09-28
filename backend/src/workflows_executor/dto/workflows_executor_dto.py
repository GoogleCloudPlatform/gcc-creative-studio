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
)

# Run ids are UUIDs or GCP execution ids; step ids are editor node ids.
_KEY_PATTERN = r"^[A-Za-z0-9_-]*$"
_KEY_MAX_LENGTH = 128


class StepCallContext(BaseModel):
    """Optional checkpoint / idempotency key of a workflow step call.

    Sent by the generated YAML. Calls without ``run_id`` (missing or empty,
    e.g. executions started before the queue existed) run without
    checkpoint or idempotency.
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
