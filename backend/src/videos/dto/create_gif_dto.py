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

from typing import Annotated

from fastapi import Query
from pydantic import Field, field_validator

from src.common.base_dto import (
    AspectRatioEnum,
    BaseDto,
    GenerationModelEnum,
)


class CreateGifDto(BaseDto):
    """Request model for generating an animated GIF from text and an optional
    reference image via Veo.
    """

    prompt: Annotated[str, Query(max_length=10000)] = Field(
        description="Text prompt describing the desired animation.",
    )
    workspace_id: int = Field(
        ge=1,
        description="The ID of the workspace for this generation.",
    )
    generation_model: GenerationModelEnum = Field(
        default=GenerationModelEnum.VEO_3_1_FAST_GENERATE_001,
        description="Veo model used for the intermediate video generation.",
    )
    aspect_ratio: AspectRatioEnum = Field(
        default=AspectRatioEnum.RATIO_16_9,
        description="Aspect ratio of the output GIF.",
    )
    # Optional reference image — provides the starting frame for image-to-video.
    # Supply the ID of an existing SourceAsset; the backend resolves its GCS URI.
    start_image_asset_id: int | None = Field(
        default=None,
        description="ID of a SourceAsset to use as the reference (starting) image.",
    )
    duration_seconds: int = Field(
        default=5,
        ge=3,
        le=8,
        description="Duration of the intermediate video in seconds (3-8).",
    )
    enhance_prompt: bool = Field(
        default=True,
        description="Whether to enhance the prompt using Gemini before generation.",
    )
    gif_fps: int = Field(
        default=10,
        ge=5,
        le=24,
        description="Frame rate of the output GIF (5-24 fps).",
    )
    gif_width: int = Field(
        default=480,
        ge=240,
        le=960,
        description="Width of the output GIF in pixels (height is auto-scaled).",
    )

    @field_validator("aspect_ratio")
    def validate_aspect_ratio(cls, value: AspectRatioEnum) -> AspectRatioEnum:
        valid = [AspectRatioEnum.RATIO_16_9, AspectRatioEnum.RATIO_9_16]
        if value not in valid:
            raise ValueError(
                "Invalid aspect ratio for GIF. Only '16:9' and '9:16' are supported.",
            )
        return value

    @field_validator("generation_model")
    def validate_generation_model(
        cls, value: GenerationModelEnum
    ) -> GenerationModelEnum:
        valid = [
            GenerationModelEnum.VEO_3_1_GENERATE_001,
            GenerationModelEnum.VEO_3_1_FAST_GENERATE_001,
            GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
            GenerationModelEnum.VEO_3_FAST,
            GenerationModelEnum.VEO_3_QUALITY,
        ]
        if value not in valid:
            raise ValueError(
                "Invalid generation model for GIF. Please use a Veo model.",
            )
        return value
