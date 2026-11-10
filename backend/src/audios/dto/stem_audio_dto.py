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
"""DTOs for interactive audio stem extraction and stem-mix saving."""

from enum import Enum
from typing import Annotated

from pydantic import Field, PositiveInt, field_validator, model_validator

from src.common.base_dto import AssetReferenceDto, BaseDto


class StemNameEnum(str, Enum):
    """Supported instrument stems produced by ``htdemucs_6s``."""

    VOCALS = "vocals"
    DRUMS = "drums"
    BASS = "bass"
    GUITAR = "guitar"
    PIANO = "piano"
    OTHER = "other"


class StemSaveModeEnum(str, Enum):
    """How selected stems should be persisted on the resulting MediaItem."""

    COMBINED = "combined"
    SEPARATE = "separate"


def _validate_audio_source_ref(source: AssetReferenceDto) -> AssetReferenceDto:
    if source.type not in {"source_asset", "media_item"}:
        raise ValueError("source.type must be 'source_asset' or 'media_item'.")
    if source.id <= 0:
        raise ValueError("source.id must be a positive integer.")
    if source.index is not None and source.index < 0:
        raise ValueError("source.index must be non-negative.")
    return source


class ExtractStemsDto(BaseDto):
    """Request payload for separating a reference or generated audio into stems."""

    workspace_id: int = Field(
        description="The ID of the workspace owning the audio.",
    )
    source: AssetReferenceDto = Field(
        description="Reference to the source_asset or media_item to separate.",
    )

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: AssetReferenceDto) -> AssetReferenceDto:
        return _validate_audio_source_ref(value)


class StemPreviewItemDto(BaseDto):
    """Metadata and temporary playback URL for a single separated stem."""

    name: StemNameEnum
    label: str
    gcs_uri: str
    presigned_url: str
    waveform: list[float] | None = None
    duration_seconds: float | None = None
    peak_level: float = 0.0
    has_energy: bool = True


class StemJobStatusEnum(str, Enum):
    """Lifecycle status of an audio stem extraction job."""

    PROCESSING = "processing"
    COMPLETED = "completed"


class ExtractStemsResponseDto(BaseDto):
    """Response returned when starting or polling audio stem extraction."""

    status: StemJobStatusEnum = StemJobStatusEnum.COMPLETED
    cache_hit: bool
    source_name: str
    duration_seconds: float | None = None
    stems: list[StemPreviewItemDto] = Field(default_factory=list)


class SaveStemMixDto(BaseDto):
    """Request payload to save selected stems to a new gallery MediaItem."""

    workspace_id: int = Field(
        description="The ID of the workspace for the resulting MediaItem.",
    )
    source: AssetReferenceDto = Field(
        description="Reference to the source_asset or media_item being stemmed.",
    )
    selected_stems: Annotated[
        list[StemNameEnum], Field(min_length=1, max_length=6)
    ] = Field(
        description="Ordered list of instrument stems to include in the result.",
    )
    save_mode: StemSaveModeEnum = Field(
        default=StemSaveModeEnum.COMBINED,
        description=(
            "'combined' mixes selected stems into 1 track; 'separate' saves "
            "each selected stem as its own track on the MediaItem."
        ),
    )
    folder_id: PositiveInt | None = Field(
        default=None,
        description="Optional gallery folder (same workspace) to save into.",
    )
    file_name: str | None = Field(
        default=None,
        max_length=200,
        description="Optional custom title/name for the saved MediaItem.",
    )

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: AssetReferenceDto) -> AssetReferenceDto:
        return _validate_audio_source_ref(value)

    @model_validator(mode="after")
    def deduplicate_stems(self) -> "SaveStemMixDto":
        seen: set[StemNameEnum] = set()
        unique: list[StemNameEnum] = []
        for stem in self.selected_stems:
            if stem not in seen:
                seen.add(stem)
                unique.append(stem)
        if not unique:
            raise ValueError("selected_stems must contain at least one stem.")
        self.selected_stems = unique
        return self
