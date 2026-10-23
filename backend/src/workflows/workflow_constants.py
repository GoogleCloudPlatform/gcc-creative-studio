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
"""Constants for workflows."""

from enum import Enum


class ImageModeEnum(str, Enum):
    """Supported modes for the unified Image step."""

    GENERATE_IMAGE = "generate_image"
    EDIT_IMAGE = "edit_image"
    UPSCALE_IMAGE = "upscale_image"
    VIRTUAL_TRY_ON = "virtual_try_on"


IMAGE_MODE_ALLOWED_INPUTS: dict[str, list[str]] = {
    ImageModeEnum.GENERATE_IMAGE.value: ["prompt"],
    ImageModeEnum.EDIT_IMAGE.value: ["prompt", "input_images"],
    ImageModeEnum.UPSCALE_IMAGE.value: ["input_image"],
    ImageModeEnum.VIRTUAL_TRY_ON.value: [
        "model_image",
        "top_image",
        "bottom_image",
        "dress_image",
        "shoes_image",
    ],
}
