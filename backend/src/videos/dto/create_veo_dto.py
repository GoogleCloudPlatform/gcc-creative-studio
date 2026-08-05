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


from typing import Annotated, Literal

from fastapi import Query
from pydantic import Field, field_validator, model_validator

from src.common.base_dto import (
    AspectRatioEnum,
    BaseDto,
    ColorAndToneEnum,
    CompositionEnum,
    GenerationModelEnum,
    LightingEnum,
    ReferenceImageTypeEnum,
    StyleEnum,
)
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    SourceMediaItemLink,
)

# Models served by the Gemini Omni Interactions API. Their capabilities differ
# substantially from Veo's, so several limits below are resolved per-model
# rather than as static field constraints.
#
# GEMINI_OMNI ("gemini-omni-generate-preview") is intentionally absent: it is
# not a real model. Vertex rejects it with "Unsupported model interaction". The
# enum member survives only so historical rows deserialize.
OMNI_MODELS = frozenset({GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW})

# Widest bounds accepted by any supported model. The real, per-model limits are
# enforced in CreateVeoDto.validate_cross_fields.
MAX_REFERENCE_IMAGES_ANY_MODEL = 7
MAX_DURATION_SECONDS_ANY_MODEL = 10

# Omni accepts any whole number of seconds from 3 to 10. Verified against the
# live API: 3s, 6s and 10s requests returned clips of 3.01s, 6.02s and 10.01s,
# so the value is honoured rather than merely accepted.
OMNI_DURATION_RANGE = (3, 10)

# Veo offers a fixed set of lengths rather than a range, so 5s and 7s are not
# valid even though they fall between the bounds.
VEO_DURATION_CHOICES = frozenset({4, 6, 8})

# Reference image limits. Omni's ceiling is higher than Veo's.
#
# This is a product guardrail, not an API limit: Vertex accepted 8 references
# without complaint. Google's cookbook advises "up to 5" for quality while its
# own example uses 6 successfully. 7 sits between the documented advice and the
# point where the API pushes back; lower it if quality degrades in practice.
OMNI_MAX_REFERENCE_IMAGES = 7
VEO_MAX_REFERENCE_IMAGES = 3


class ReferenceImageDto(BaseDto):
    asset_id: int = Field(
        description="The ID of the SourceAsset to use as a reference.",
    )
    reference_type: ReferenceImageTypeEnum = Field(
        default=ReferenceImageTypeEnum.ASSET
    )


class AssetReferenceDto(BaseDto):
    id: int = Field(description="The ID of the asset.")
    type: str = Field(
        description="The type of asset: 'source_asset' or 'media_item'."
    )
    index: int | None = Field(
        default=0,
        description="The index of the media in the media item (if applicable).",
    )


class CreateVeoDto(BaseDto):
    """The refactored request model. Defaults are defined here to make the API
    contract explicit and self-documenting.
    """

    prompt: Annotated[str, Query(max_length=10000)] = Field(
        description="Prompt term to be passed to the model",
    )
    workspace_id: int = Field(
        ge=1,
        description="The ID of the workspace for this generation.",
    )
    generation_model: GenerationModelEnum = Field(
        default=GenerationModelEnum.VEO_3_1_GENERATE_001,
        description="Model used for image generation.",
    )
    aspect_ratio: AspectRatioEnum = Field(
        default=AspectRatioEnum.RATIO_16_9,
        description="Aspect ratio of the image.",
    )
    number_of_media: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Number of videos to generate (between 1 and 4).",
    )
    style: StyleEnum | None = Field(
        default=None, description="Style of the image."
    )
    negative_prompt: str = Field(
        default="",
        description="Negative prompt for the image.",
    )
    color_and_tone: ColorAndToneEnum | None = Field(
        default=None,
        description="The desired color and tone style for the image.",
    )
    lighting: LightingEnum | None = Field(
        default=None,
        description="The desired lighting style for the image.",
    )
    composition: CompositionEnum | None = Field(
        default=None,
        description="The desired lighting style for the image.",
    )
    generate_audio: bool = Field(
        default=False,
        description="Whether to add audio to the generated video.",
    )
    duration_seconds: int = Field(
        default=8,
        ge=1,
        le=MAX_DURATION_SECONDS_ANY_MODEL,
        description=(
            "Duration in seconds for the videos to generate. The accepted "
            "range depends on the model: Veo allows 1-8, Omni allows 3-10."
        ),
    )
    start_image_asset_id: AssetReferenceDto | None = Field(
        default=None,
        description="Object containing ID and type of asset to use as the starting image.",
    )
    end_image_asset_id: AssetReferenceDto | None = Field(
        default=None,
        description="Object containing ID and type of asset to use as the ending image.",
    )
    source_video_asset_id: AssetReferenceDto | None = Field(
        default=None,
        description="Object containing ID and type of asset to use as the source video.",
    )
    source_media_items: list[SourceMediaItemLink] | None = Field(
        default=None,
        description="A list of previously generated media items (from the gallery) to be used as inputs (e.g., start/end frames).",
    )
    use_brand_guidelines: bool = Field(
        default=False,
        description="Whether to prepend brand guidelines to the prompt.",
    )
    enhance_prompt: bool = Field(
        default=False,
        description="Whether to enhance the prompt using Gemini.",
    )
    reference_images: list[ReferenceImageDto] | None = Field(
        default=None,
        max_length=MAX_REFERENCE_IMAGES_ANY_MODEL,
        description=(
            "A list of reference images, each with an ID and a type (ASSET or "
            "STYLE). The maximum count depends on the model: Veo allows 3, "
            "Gemini Omni allows 7."
        ),
    )
    reference_video: AssetReferenceDto | None = Field(
        default=None,
        description="Object containing ID and type of asset to use as a reference video.",
    )
    reference_audio: AssetReferenceDto | None = Field(
        default=None,
        description="Object containing ID and type of asset to use as a reference audio.",
    )
    edit_source: AssetReferenceDto | None = Field(
        default=None,
        description=(
            "A video to modify. Unlike parent_media_item_id, which continues "
            "an existing conversation, this starts a fresh edit of any clip, "
            "including uploaded footage. Gemini Omni only."
        ),
    )
    parent_media_item_id: int | None = Field(
        default=None,
        description="The ID of the parent media item for multi-turn conversation editing.",
    )
    parent_media_index: int = Field(
        default=0,
        ge=0,
        description=(
            "Which video within the parent media item to continue editing. A "
            "single job can produce several clips, each with its own "
            "interaction, so the index selects which conversation to resume."
        ),
    )
    resolution: Literal["1K", "2K", "4K"] = Field(
        default="1K",
        description="Resolution of the generated videos.",
    )

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "CreateVeoDto":
        """Performs several validations:
        1. Ensures that source_media_items have a valid role.
        2. Ensures references are not used with start/end frames or source videos.
        3. Ensures reference image roles are only used with correct model.
        """
        conflicting_roles_present = False
        reference_roles_present = False
        model = self.generation_model

        if self.source_media_items:
            non_reference_roles = {
                AssetRoleEnum.START_FRAME,
                AssetRoleEnum.END_FRAME,
                AssetRoleEnum.VIDEO_EXTENSION_SOURCE,
            }
            reference_roles = {
                AssetRoleEnum.IMAGE_REFERENCE_ASSET,
                AssetRoleEnum.IMAGE_REFERENCE_STYLE,
            }
            valid_roles = non_reference_roles.union(reference_roles)

            for item in self.source_media_items:
                if item.role not in valid_roles:
                    raise ValueError(
                        f"Invalid role '{item.role}' for source_media_item.",
                    )
                if item.role in non_reference_roles:
                    conflicting_roles_present = True
                if item.role in reference_roles:
                    reference_roles_present = True

        has_asset_references = (
            bool(self.reference_images)
            or bool(self.reference_video)
            or bool(self.reference_audio)
        )
        has_any_references = has_asset_references or reference_roles_present

        if has_any_references:
            supported_reference_models = {
                GenerationModelEnum.VEO_3_1_PREVIEW,
                GenerationModelEnum.VEO_3_1_GENERATE_001,
                GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
                GenerationModelEnum.VEO_3_1_FAST_GENERATE_001,
                GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            }
            if model not in supported_reference_models:
                supported = ", ".join(
                    sorted(m.value for m in supported_reference_models)
                )
                raise ValueError(
                    "Reference images/media are only supported by these "
                    f"models: {supported}.",
                )

            start_image_present = bool(self.start_image_asset_id)
            end_image_present = bool(self.end_image_asset_id)
            source_video_present = bool(self.source_video_asset_id)

            if (
                start_image_present
                or end_image_present
                or source_video_present
                or conflicting_roles_present
            ):
                raise ValueError(
                    "Reference media cannot be used at the same time as a start frame, end frame, or source video.",
                )

        # Validate model-specific resolution limits
        is_omni = model in OMNI_MODELS

        if is_omni:
            allowed_resolutions = {"1K"}
        elif model == GenerationModelEnum.VEO_3_1_LITE_GENERATE_001:
            allowed_resolutions = {"1K", "2K"}
        else:
            allowed_resolutions = {"1K", "2K", "4K"}

        if self.resolution not in allowed_resolutions:
            raise ValueError(
                f"Model '{model.value}' does not support resolution '{self.resolution}'. "
                f"Supported resolutions: {sorted(list(allowed_resolutions))}"
            )

        # Reference image counts differ per model. The field-level max_length
        # only enforces the widest bound any model allows, so narrow it here.
        max_reference_images = (
            OMNI_MAX_REFERENCE_IMAGES if is_omni else VEO_MAX_REFERENCE_IMAGES
        )
        if (
            self.reference_images
            and len(self.reference_images) > max_reference_images
        ):
            raise ValueError(
                f"Model '{model.value}' supports at most "
                f"{max_reference_images} reference images, "
                f"got {len(self.reference_images)}.",
            )

        # Duration also differs per model, and not just in bounds: Omni takes a
        # continuous range while Veo takes a fixed set of lengths.
        if is_omni:
            min_duration, max_duration = OMNI_DURATION_RANGE
            if not min_duration <= self.duration_seconds <= max_duration:
                raise ValueError(
                    f"Model '{model.value}' supports durations between "
                    f"{min_duration} and {max_duration} seconds, "
                    f"got {self.duration_seconds}.",
                )
        elif self.duration_seconds not in VEO_DURATION_CHOICES:
            allowed = ", ".join(str(d) for d in sorted(VEO_DURATION_CHOICES))
            raise ValueError(
                f"Model '{model.value}' supports durations of {allowed} "
                f"seconds, got {self.duration_seconds}.",
            )

        if is_omni:
            self._validate_omni_unsupported_inputs(model)
        elif self.edit_source:
            raise ValueError(
                f"Model '{model.value}' does not support video editing. "
                f"Use '{GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW.value}'.",
            )

        if self.edit_source and (
            self.start_image_asset_id
            or self.reference_images
            or self.reference_video
        ):
            raise ValueError(
                "edit_source cannot be combined with a start frame or "
                "reference media: an edit modifies one clip.",
            )

        return self

    def _validate_omni_unsupported_inputs(
        self,
        model: GenerationModelEnum,
    ) -> None:
        """Rejects inputs Gemini Omni accepts in its schema but cannot process.

        Omni does not support video extension, first+last frame interpolation,
        or audio references. The Interactions API accepts these parts without
        erroring and then silently ignores them, so validating here is the only
        way the caller learns the request would not do what they asked.
        """
        unsupported: list[str] = []

        use_veo = "use a Veo model instead"
        extension = "video extension"
        interpolation = "first+last frame interpolation"

        if self.source_video_asset_id:
            unsupported.append(
                f"{extension} (source_video_asset_id) — {use_veo}",
            )

        if self.end_image_asset_id:
            unsupported.append(
                f"{interpolation} (end_image_asset_id) — {use_veo}",
            )

        if self.reference_audio:
            unsupported.append(
                "audio references (reference_audio) — describe the "
                "audio in the prompt instead",
            )

        if self.source_media_items:
            roles = {item.role for item in self.source_media_items}
            if AssetRoleEnum.VIDEO_EXTENSION_SOURCE in roles:
                unsupported.append(
                    f"{extension} (video_extension_source role) — {use_veo}",
                )
            if AssetRoleEnum.END_FRAME in roles:
                unsupported.append(
                    f"{interpolation} (end_frame role) — {use_veo}",
                )

        if unsupported:
            raise ValueError(
                f"Model '{model.value}' does not support: "
                + "; ".join(unsupported),
            )

    @field_validator("aspect_ratio")
    def validate_video_aspect_ratio(
        cls, value: AspectRatioEnum
    ) -> AspectRatioEnum:
        """Ensures that only supported aspect ratios for video are used."""
        valid_video_ratios = [
            AspectRatioEnum.RATIO_16_9,
            AspectRatioEnum.RATIO_9_16,
        ]
        if value not in valid_video_ratios:
            raise ValueError(
                "Invalid aspect ratio for video. Only '16:9' and '9:16' are supported.",
            )
        return value

    @field_validator("generation_model")
    def validate_video_generation_model(
        cls,
        value: GenerationModelEnum,
    ) -> GenerationModelEnum:
        """Ensures that only supported generation models for video are used.

        GEMINI_OMNI is deliberately excluded: Vertex rejects it as an
        unsupported model interaction, so accepting it here only defers the
        failure to the background worker where the user sees a generic error.
        """
        valid_video_ratios = [
            GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            GenerationModelEnum.VEO_3_1_PREVIEW,
            GenerationModelEnum.VEO_3_1_GENERATE_001,
            GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
            GenerationModelEnum.VEO_3_1_FAST_GENERATE_001,
            GenerationModelEnum.VEO_3_FAST,
            GenerationModelEnum.VEO_3_QUALITY,
            GenerationModelEnum.VEO_3_FAST_PREVIEW,
            GenerationModelEnum.VEO_3_QUALITY_PREVIEW,
        ]
        if value not in valid_video_ratios:
            raise ValueError("Invalid generation model for video.")
        return value
