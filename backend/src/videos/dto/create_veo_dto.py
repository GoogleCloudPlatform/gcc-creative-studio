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
from pydantic import Field, PositiveInt, field_validator, model_validator

from src.common.base_dto import (
    AspectRatioEnum,
    AssetReferenceDto,
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


class ReferenceImageDto(BaseDto):
    asset_id: int = Field(
        description="The ID of the SourceAsset to use as a reference.",
    )
    reference_type: ReferenceImageTypeEnum = Field(
        default=ReferenceImageTypeEnum.ASSET
    )


def reference_image_key(img: ReferenceImageDto) -> tuple[int, str]:
    """Returns the identity of a reference image.

    The role is part of the identity, so the same image used once as an
    ASSET and once as a STYLE reference counts as two distinct references.
    """
    return (img.asset_id, ReferenceImageTypeEnum(img.reference_type).value)


def dedupe_reference_images(
    images: list[ReferenceImageDto] | None,
) -> list[ReferenceImageDto]:
    """Drops exact duplicate reference images while preserving order."""
    seen: set[tuple[int, str]] = set()
    unique: list[ReferenceImageDto] = []
    for img in images or []:
        key = reference_image_key(img)
        if key not in seen:
            seen.add(key)
            unique.append(img)
    return unique


def reference_video_key(ref: AssetReferenceDto) -> tuple[str, int, int]:
    """Returns the identity of a reference video.

    Gallery media items can hold several videos, so their index is part of
    the identity; source assets hold one video and ignore the index.
    """
    index = (ref.index or 0) if ref.type == "media_item" else 0
    return (ref.type, ref.id, index)


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

    metadata_generation_model: GenerationModelEnum | str | None = Field(
        default=GenerationModelEnum.GEMINI_3_5_FLASH,
        description="The Gemini model to use for synchronous metadata generation.",
    )
    titles: list[str] | None = Field(
        default=None,
        description="Optional titles for the generated video.",
    )
    descriptions: list[str] | None = Field(
        default=None,
        description="Optional descriptions for the generated video.",
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
        le=15,
        description="Duration in seconds for the videos to generate (between 1 and 15 secs; the per-model maximum is enforced in validate_cross_fields).",
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
        max_length=10,
        description="A list of reference images, each with an ID and a type (ASSET or STYLE).",
    )
    reference_videos: list[AssetReferenceDto] | None = Field(
        default=None,
        max_length=3,
        description="A list of up to 3 reference videos (source assets or gallery media items).",
    )
    reference_video: AssetReferenceDto | None = Field(
        default=None,
        description="Deprecated singular reference video; normalized into reference_videos.",
    )
    reference_audio: AssetReferenceDto | None = Field(
        default=None,
        description="Deprecated reference audio field; audio references are rejected for video generation.",
    )
    parent_media_item_id: int | None = Field(
        default=None,
        description="The ID of the parent media item for multi-turn conversation editing.",
    )
    file_name: str | None = Field(
        default=None,
        description="Optional name for the generated media.",
    )
    resolution: Literal["1K", "2K", "4K"] = Field(
        default="1K",
        description="Resolution of the generated videos.",
    )
    folder_id: PositiveInt | None = Field(
        default=None,
        description="Optional gallery folder (same workspace) to save the generated media into. Defaults to the root folder.",
    )

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "CreateVeoDto":
        """Performs several validations:
        1. Rejects unsupported audio references across all models.
        2. Ensures that source_media_items have a valid role.
        3. Ensures references are not used with start/end frames or source videos.
        4. Enforces per-model reference image, reference video, and extension support.
        5. Validates model-specific resolution and mode-aware duration limits.
        """
        conflicting_roles_present = False
        reference_roles_present = False
        model = self.generation_model

        has_audio_role = any(
            item.role == AssetRoleEnum.AUDIO_REFERENCE
            for item in (self.source_media_items or [])
        )
        if self.reference_audio is not None or has_audio_role:
            raise ValueError(
                "Audio reference is not supported for video generation."
            )

        if self.source_media_items:
            non_reference_roles = {
                AssetRoleEnum.START_FRAME,
                AssetRoleEnum.END_FRAME,
                AssetRoleEnum.VIDEO_EXTENSION_SOURCE,
            }
            reference_roles = {
                AssetRoleEnum.IMAGE_REFERENCE_ASSET,
                AssetRoleEnum.IMAGE_REFERENCE_STYLE,
                AssetRoleEnum.VIDEO_REFERENCE,
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

        # Normalize and deduplicate reference videos across reference_videos,
        # legacy reference_video, and VIDEO_REFERENCE source_media_items.
        normalized_ref_videos: list[AssetReferenceDto] = []
        seen_video_keys: set[tuple[str, int, int]] = set()
        raw_video_refs = list(self.reference_videos or [])
        if self.reference_video is not None:
            raw_video_refs.append(self.reference_video)

        for ref in raw_video_refs:
            key = reference_video_key(ref)
            if key not in seen_video_keys:
                seen_video_keys.add(key)
                normalized_ref_videos.append(ref)

        self.reference_videos = normalized_ref_videos or None
        self.reference_video = None

        for item in self.source_media_items or []:
            if item.role == AssetRoleEnum.VIDEO_REFERENCE:
                seen_video_keys.add(
                    ("media_item", item.media_item_id, item.media_index or 0)
                )

        # Deduplicate reference images in-place across reference_images and source_media_items.
        # The role is part of the key so the same image used as both
        # ASSET and STYLE is kept twice; exact duplicates still collapse.
        # Keys are namespaced by origin so both lists share one counter.
        seen_image_keys: set[tuple] = set()
        if self.reference_images is not None:
            dedup_ref_images: list[ReferenceImageDto] = []
            for img in self.reference_images:
                key = ("source_asset", *reference_image_key(img))
                if key not in seen_image_keys:
                    seen_image_keys.add(key)
                    dedup_ref_images.append(img)
            self.reference_images = dedup_ref_images or None

        if self.source_media_items is not None:
            dedup_media_items: list[SourceMediaItemLink] = []
            for item in self.source_media_items:
                if item.role in {
                    AssetRoleEnum.IMAGE_REFERENCE_ASSET,
                    AssetRoleEnum.IMAGE_REFERENCE_STYLE,
                }:
                    key = (
                        "media_item",
                        item.media_item_id,
                        item.media_index or 0,
                        AssetRoleEnum(item.role).value,
                    )
                    if key in seen_image_keys:
                        continue
                    seen_image_keys.add(key)
                dedup_media_items.append(item)
            self.source_media_items = dedup_media_items or None

        total_reference_images = len(seen_image_keys)
        total_reference_videos = len(seen_video_keys)

        has_asset_references = (
            total_reference_images > 0 or total_reference_videos > 0
        )
        has_any_references = has_asset_references or reference_roles_present

        has_start_frame = bool(self.start_image_asset_id) or any(
            i.role == AssetRoleEnum.START_FRAME
            for i in (self.source_media_items or [])
        )
        has_end_frame = bool(self.end_image_asset_id) or any(
            i.role == AssetRoleEnum.END_FRAME
            for i in (self.source_media_items or [])
        )
        has_source_video = bool(self.source_video_asset_id) or any(
            i.role == AssetRoleEnum.VIDEO_EXTENSION_SOURCE
            for i in (self.source_media_items or [])
        )

        if not has_source_video and not self.prompt.strip():
            raise ValueError(
                "Prompt is required unless extending a source video."
            )

        if has_any_references:
            if model.max_reference_images == 0:
                supported = ", ".join(
                    f"'{m.value}'"
                    for m in GenerationModelEnum
                    if m.max_reference_images > 0
                )
                raise ValueError(
                    f"Model '{model.value}' does not support reference "
                    "images/media. Reference images/media are only "
                    f"supported by: {supported}.",
                )

            if (
                has_start_frame
                or has_end_frame
                or has_source_video
                or conflicting_roles_present
            ):
                raise ValueError(
                    "Reference media cannot be used at the same time as a start frame, end frame, or source video.",
                )

        max_reference_videos = model.max_reference_videos
        if total_reference_videos > 0:
            if max_reference_videos == 0:
                raise ValueError(
                    f"Model '{model.value}' does not support Video as reference. "
                    "Video reference is only supported by Gemini Omni 1.1 Flash and 1.2 Flash models."
                )
            if total_reference_videos > max_reference_videos:
                raise ValueError(
                    f"Model '{model.value}' supports up to {max_reference_videos} reference videos "
                    f"(got {total_reference_videos})."
                )

        if has_source_video and not model.supports_video_extension:
            raise ValueError(
                f"Model '{model.value}' does not support video extension."
            )

        max_reference_images = model.max_reference_images
        if total_reference_images > max_reference_images:
            raise ValueError(
                f"Model '{model.value}' supports up to {max_reference_images} reference images "
                f"(got {total_reference_images})."
            )

        # Validate model-specific resolution limits
        if model.is_gemini_omni_model:
            allowed_resolutions = {"1K"}
        elif model in (
            GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
            GenerationModelEnum.VEO_3_1_LITE_PREVIEW,
        ):
            allowed_resolutions = {"1K", "2K"}
        else:
            allowed_resolutions = {"1K", "2K", "4K"}

        if self.resolution not in allowed_resolutions:
            raise ValueError(
                f"Model '{model.value}' does not support resolution '{self.resolution}'. "
                f"Supported resolutions: {sorted(list(allowed_resolutions))}"
            )

        # Validate model-specific duration limits
        if model.is_gemini_omni_model and self.duration_seconds < 3:
            raise ValueError(
                f"Model '{model.value}' requires a minimum duration of 3s "
                f"(got '{self.duration_seconds}s')."
            )

        max_duration = model.max_video_duration(
            has_any_references=has_any_references,
            has_source_video=has_source_video,
            has_end_frame=has_end_frame,
        )

        if self.duration_seconds > max_duration:
            raise ValueError(
                f"Model '{model.value}' does not support duration '{self.duration_seconds}s'. "
                f"Maximum supported duration: {max_duration}s."
            )

        return self

    @field_validator("aspect_ratio")
    @classmethod
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
    @classmethod
    def validate_video_generation_model(
        cls,
        value: GenerationModelEnum,
    ) -> GenerationModelEnum:
        """Ensures that only supported generation models for video are used."""
        valid_video_ratios = [
            GenerationModelEnum.GEMINI_OMNI,
            GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
            GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            GenerationModelEnum.VEO_3_1_PREVIEW,
            GenerationModelEnum.VEO_3_1_GENERATE_001,
            GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
            GenerationModelEnum.VEO_3_1_LITE_PREVIEW,
            GenerationModelEnum.VEO_3_1_FAST_GENERATE_001,
            GenerationModelEnum.VEO_3_FAST,
            GenerationModelEnum.VEO_3_QUALITY,
            GenerationModelEnum.VEO_3_FAST_PREVIEW,
            GenerationModelEnum.VEO_3_QUALITY_PREVIEW,
        ]
        if value not in valid_video_ratios:
            raise ValueError("Invalid generation model for video.")
        return value
