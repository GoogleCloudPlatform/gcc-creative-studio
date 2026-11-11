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

from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field

from src.common.base_dto import BaseDto


class PromptTargetEnum(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class RewritePromptRequestDto(BaseDto):
    """Request body for the /rewrite-prompt endpoint."""

    target_type: Annotated[
        PromptTargetEnum,
        Field(
            description="The target media type to tailor the prompt for (e.g., 'image', 'video', or 'audio').",
        ),
    ]
    user_prompt: Annotated[
        str,
        Field(
            description="The simple, user-provided prompt to be rewritten and enhanced.",
            min_length=2,
        ),
    ]


class RandomPromptRequestDto(BaseDto):
    """Request body for the /random-prompt endpoint."""

    target_type: Annotated[
        PromptTargetEnum,
        Field(
            description="The target media type for which to generate a random prompt.",
        ),
    ]


class RewrittenOrRandomPromptResponse(BaseDto):
    prompt: str


class GenerateTitleRequestDto(BaseDto):
    """Request body for the /generate-title endpoint."""

    text: Annotated[
        str,
        Field(
            description="The text to generate a title for.",
            min_length=1,
        ),
    ]


class GenerateTitleResponseDto(BaseDto):
    title: str
    summary: str | None = None


class MusicalProfileDto(BaseDto):
    """Structured acoustic / musical DNA extracted per generated music take."""

    model_config = ConfigDict(extra="ignore")

    bpm: int | float | None = Field(
        default=None, description="Estimated tempo in BPM."
    )
    key_signature: str | None = Field(
        default=None, description="Musical key and mode (e.g., 'Bb Major')."
    )
    time_signature: str | None = Field(
        default=None, description="Meter / time signature (e.g., '4/4', '6/8')."
    )
    chord_progression: str | None = Field(
        default=None, description="Summary of the harmonic / chord progression."
    )
    groove: str | None = Field(
        default=None, description="Rhythmic feel, pocket, and energy profile."
    )
    instrumentation: list[str] = Field(
        default_factory=list,
        description="Prominent instruments heard in this specific take.",
    )
    vocal_profile: str | None = Field(
        default=None,
        description=(
            "Canonical vocal range/timbre (e.g., 'Female Soprano', 'Female "
            "Alto', 'Male Tenor', 'Male Baritone', 'Weathered Rocker'), "
            "delivery, harmonies, and language, or 'instrumental'."
        ),
    )


class MediaItemMetadataItemDto(BaseDto):
    title: str = Field(description="Title for this specific media variation.")
    description: str = Field(
        description="Description for this specific media variation."
    )


class AudioMediaItemMetadataItemDto(MediaItemMetadataItemDto):
    musical_profile: MusicalProfileDto | None = Field(
        default=None,
        description="Acoustic and harmonic profile analyzed from this take.",
    )


class GenerateMediaMetadataResponseDto(BaseDto):
    items: list[MediaItemMetadataItemDto] = Field(
        default_factory=list,
        description=(
            "List of title and description objects corresponding to each media"
            " item in order."
        ),
    )


class GenerateAudioMediaMetadataResponseDto(BaseDto):
    items: list[AudioMediaItemMetadataItemDto] = Field(
        default_factory=list,
        description="Title, description, and musical profile per audio item.",
    )
