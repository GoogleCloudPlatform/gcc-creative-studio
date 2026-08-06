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
"""Tests for Create Veo Dto."""

import pytest
from pydantic import ValidationError

from src.common.base_dto import (
    GenerationModelEnum,
    ReferenceImageTypeEnum,
)
from src.common.schema.media_item_model import SourceMediaItemLink
from src.videos.dto.create_veo_dto import CreateVeoDto, ReferenceImageDto


def test_create_veo_dto_valid():
    dto = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_QUALITY,
        aspect_ratio="16:9",
    )
    assert dto.prompt == "Test"


def test_validate_video_aspect_ratio_error():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test", workspace_id=1, aspect_ratio="1:1"
        )  # Invalid
    assert "Invalid aspect ratio for video" in str(exc_info.value)


def test_validate_source_media_items_invalid_role():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=1,
                    media_index=0,
                    role="invalid_role",
                ),
            ],
        )
    # Pydantic validation error or enum validation error
    assert "invalid_role" in str(exc_info.value)


def test_validate_source_media_items_model_conflict():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_QUALITY,
            reference_images=[
                ReferenceImageDto(
                    asset_id=1,
                    reference_type=ReferenceImageTypeEnum.ASSET,
                ),
            ],
            source_media_items=[],  # Force validator to run
        )
    assert "Reference images/media are only supported by" in str(exc_info.value)


def test_validate_source_media_items_conflicting_inputs():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_PREVIEW,
            start_image_asset_id={"id": 1, "type": "source_asset"},
            reference_images=[
                ReferenceImageDto(
                    asset_id=2,
                    reference_type=ReferenceImageTypeEnum.ASSET,
                ),
            ],
            source_media_items=[],  # Force validator to run
        )
    assert "Reference media cannot be used at the same time" in str(
        exc_info.value
    )


def test_validate_video_generation_model_error():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test", workspace_id=1, generation_model="invalid_model"
        )
    assert (
        "Invalid generation model for video" in str(exc_info.value)
        or "enum" in str(exc_info.value).lower()
    )


def test_create_veo_dto_with_omni_references():
    dto = CreateVeoDto(
        prompt="Test Omni",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        reference_video={"id": 10, "type": "media_item"},
        parent_media_item_id=15,
    )
    assert dto.generation_model == GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW
    assert dto.reference_video.id == 10
    assert dto.reference_video.type == "media_item"
    assert dto.parent_media_item_id == 15
    assert dto.parent_media_index == 0


def test_omni_rejects_audio_reference():
    """Omni cannot process audio references.

    The Interactions API accepts an audio content part without erroring and then
    ignores it, so the request has to be rejected here or the caller silently
    gets a video that ignored their audio.
    """
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test Omni",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            reference_audio={"id": 20, "type": "media_item"},
        )
    assert "audio references" in str(exc_info.value)


def test_omni_rejects_video_extension():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Extend this",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            source_video_asset_id={"id": 5, "type": "source_asset"},
        )
    assert "video extension" in str(exc_info.value)


def test_omni_rejects_last_frame_interpolation():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Interpolate",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            start_image_asset_id={"id": 5, "type": "source_asset"},
            end_image_asset_id={"id": 6, "type": "source_asset"},
        )
    assert "interpolation" in str(exc_info.value)


def test_veo_still_allows_extension_and_interpolation():
    """The Omni restrictions must not leak onto Veo, which supports both."""
    dto = CreateVeoDto(
        prompt="Extend this",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
        source_video_asset_id={"id": 5, "type": "source_asset"},
    )
    assert dto.source_video_asset_id.id == 5

    dto = CreateVeoDto(
        prompt="Interpolate",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
        start_image_asset_id={"id": 5, "type": "source_asset"},
        end_image_asset_id={"id": 6, "type": "source_asset"},
    )
    assert dto.end_image_asset_id.id == 6


@pytest.mark.parametrize("duration", [3, 7, 10])
def test_omni_accepts_its_full_duration_range(duration):
    dto = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        duration_seconds=duration,
    )
    assert dto.duration_seconds == duration


@pytest.mark.parametrize("duration", [2, 11])
def test_omni_rejects_out_of_range_durations(duration):
    with pytest.raises(ValidationError):
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            duration_seconds=duration,
        )


@pytest.mark.parametrize("duration", [4, 6, 8])
def test_veo_accepts_its_discrete_durations(duration):
    dto = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
        duration_seconds=duration,
    )
    assert dto.duration_seconds == duration


@pytest.mark.parametrize("duration", [5, 7, 10])
def test_veo_rejects_durations_outside_its_fixed_set(duration):
    """Veo offers discrete lengths, so in-range values can still be invalid.

    5 and 7 fall between supported lengths; 10 is above them and must not be
    allowed through by Omni's wider range.
    """
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
            duration_seconds=duration,
        )
    assert "supports durations of" in str(exc_info.value)


def test_omni_accepts_seven_reference_images():
    dto = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        reference_images=[{"asset_id": i} for i in range(7)],
    )
    assert len(dto.reference_images) == 7


def test_veo_reference_ceiling_not_widened_by_omni():
    """Relaxing max_length to 7 must not let Veo past its own limit of 3."""
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
            reference_images=[{"asset_id": i} for i in range(4)],
        )
    assert "reference images" in str(exc_info.value)


def test_validate_resolution_by_model():
    # Gemini Omni - 1K is OK
    CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        resolution="1K",
    )

    # Gemini Omni - 2K is error
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            resolution="2K",
        )
    assert "does not support resolution '2K'" in str(exc_info.value)

    # Veo 3.1 Lite - 2K is OK
    CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
        resolution="2K",
    )

    # Veo 3.1 Lite - 4K is error
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_LITE_GENERATE_001,
            resolution="4K",
        )
    assert "does not support resolution '4K'" in str(exc_info.value)

    # Veo 3.1 Generate 001 - 4K is OK
    CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
        resolution="4K",
    )


def test_omni_accepts_edit_source():
    """Editing an uploaded clip is distinct from extending one.

    Extension is unsupported by Omni and rejected; editing is supported and
    verified against the live API, so the two must not share a field.
    """
    dto = CreateVeoDto(
        prompt="Make the balloon blue",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        edit_source={"id": 7, "type": "source_asset"},
    )
    assert dto.edit_source.id == 7
    assert dto.edit_source.type == "source_asset"


def test_veo_rejects_edit_source():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Make the balloon blue",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
            edit_source={"id": 7, "type": "source_asset"},
        )
    assert "does not support video editing" in str(exc_info.value)


def test_edit_source_allows_reference_images():
    """Compositing a character into existing footage is a supported pattern.

    Google's Vertex sample sends text + image + video with task=edit, and it
    was confirmed working against the live API. An earlier version of this
    validator rejected the combination and blocked the use case outright.
    """
    dto = CreateVeoDto(
        prompt="Place the woman from the reference into this scene",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        edit_source={"id": 7, "type": "source_asset"},
        reference_images=[{"asset_id": 1}],
    )
    assert dto.edit_source.id == 7
    assert len(dto.reference_images) == 1
    # Omni refuses to edit a clip containing speech when references are also
    # supplied, and its own output always has audio, so this defaults on.
    assert dto.strip_source_audio is True


def test_edit_source_rejects_a_second_video():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Edit this",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            edit_source={"id": 7, "type": "source_asset"},
            reference_video={"id": 8, "type": "source_asset"},
        )
    assert "two videos" in str(exc_info.value)


def test_edit_source_rejects_a_start_frame():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Edit this",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            edit_source={"id": 7, "type": "source_asset"},
            start_image_asset_id={"id": 9, "type": "source_asset"},
        )
    assert "start frame" in str(exc_info.value)
