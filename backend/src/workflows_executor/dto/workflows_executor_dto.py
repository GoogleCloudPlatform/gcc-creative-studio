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

from typing import Optional
from pydantic import BaseModel
from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateImageInputs,
    GenerateImageSettings,
    EditImageInputs,
    EditImageSettings,
    GenerateVideoInputs,
    GenerateVideoSettings,
    CropImageInputs,
    CropImageSettings,
    VirtualTryOnInputs,
    VirtualTryOnSettings,
    GenerateAudioInputs,
    GenerateAudioSettings,
)

class GenerateTextRequest(BaseModel):
    inputs: GenerateTextInputs
    config: GenerateTextSettings

class GenerateImageRequest(BaseModel):
    workspace_id: int
    inputs: GenerateImageInputs
    config: GenerateImageSettings

class EditImageRequest(BaseModel):
    workspace_id: int
    inputs: EditImageInputs
    config: EditImageSettings

class GenerateVideoRequest(BaseModel):
    workspace_id: int
    inputs: GenerateVideoInputs
    config: GenerateVideoSettings

class CropImageRequest(BaseModel):
    inputs: CropImageInputs
    config: CropImageSettings

class VirtualTryOnRequest(BaseModel):
    workspace_id: int
    inputs: VirtualTryOnInputs
    config: VirtualTryOnSettings

class GenerateAudioRequest(BaseModel):
    workspace_id: int
    inputs: GenerateAudioInputs
    config: GenerateAudioSettings
