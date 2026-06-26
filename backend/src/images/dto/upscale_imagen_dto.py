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

from typing import Literal

from pydantic import Field, field_validator

from src.common.base_dto import BaseDto, GenerationModelEnum, MimeTypeEnum


class UpscaleImagenDto(BaseDto):
    """The refactored request model. Defaults are defined here to make the API
    contract explicit and self-documenting.
    """

    generation_model: GenerationModelEnum = Field(
        default=GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
        description="Model used for image generation.",
    )
    user_image: str = Field(
        description="Base 64 encoded image or gcs uri of the image to scale.",
    )
    upscale_factor: Literal["x2", "x3", "x4"] = Field(
        default="x2",
        description="""Factor of the upscale, either "x2", "x3" or "x4".""",
    )
    include_rai_reason: bool = Field(
        default=True,
        description="""Whether to include the Responsible AI filter reason if the image
      is filtered out of the response.""",
    )
    mime_type: MimeTypeEnum = Field(
        default=MimeTypeEnum.IMAGE_PNG,
        description="""type of the image to upscale either "image/jpeg" or "image/png".""",
    )
    enhance_input_image: bool = Field(
        default=False,
        description="""Whether to add an image enhancing step before upscaling.
      It is expected to suppress the noise and JPEG compression artifacts
      from the input image.""",
    )
    image_preservation_factor: float | None = Field(
        default=None,
        description="""With a higher image preservation factor, the original image
      pixels are more respected. With a lower image preservation factor, the
      output image will have be more different from the input image, but
      with finer details and less noise.""",
    )

    @field_validator("generation_model")
    def validate_imagen_generation_model(
        cls,
        value: GenerationModelEnum,
    ) -> GenerationModelEnum:
        """Ensures that only supported generation models for imagen are used."""
        valid_video_ratios = [
            GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
        ]
        if value not in valid_video_ratios:
            raise ValueError("Invalid generation model for imagen.")
        return value

    @field_validator("mime_type")
    def validate_imagen_mime_type(cls, value: MimeTypeEnum) -> MimeTypeEnum:
        """Ensures that only supported generation models for imagen are used."""
        valid_mime_types = [
            MimeTypeEnum.IMAGE_PNG,
            MimeTypeEnum.IMAGE_JPEG,
        ]
        if value not in valid_mime_types:
            raise ValueError("Invalid mime type for imagen.")
        return value
