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
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
        reference_video={"id": 10, "type": "media_item"},
        parent_media_item_id=15,
    )
    assert dto.generation_model == GenerationModelEnum.GEMINI_OMNI_1_2_FLASH
    assert dto.reference_video is None
    assert len(dto.reference_videos) == 1
    assert dto.reference_videos[0].id == 10
    assert dto.reference_videos[0].type == "media_item"
    assert dto.parent_media_item_id == 15


def test_validate_resolution_by_model():
    # Gemini Omni - 1K is OK
    CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI,
        resolution="1K",
    )

    # Gemini Omni - 2K is error
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI,
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


def test_validate_duration_seconds():
    # 10s is valid for Gemini Omni Flash Preview
    dto_flash = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
        duration_seconds=10,
    )
    assert dto_flash.duration_seconds == 10

    # 10s is valid for Gemini Omni 1.1 Flash Preview
    dto_flash_1_1 = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
        duration_seconds=10,
    )
    assert dto_flash_1_1.duration_seconds == 10

    # 10s is valid for Gemini Omni
    dto_omni = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI,
        duration_seconds=10,
    )
    assert dto_omni.duration_seconds == 10

    # 8s is valid for Veo models
    dto_veo = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
        duration_seconds=8,
    )
    assert dto_veo.duration_seconds == 8

    # 10s is invalid for Veo models (max 8s)
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
            duration_seconds=10,
        )
    assert "does not support duration '10s'" in str(exc_info.value)
    assert "Maximum supported duration: 8s" in str(exc_info.value)

    # 11s exceeds max limit
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
            duration_seconds=11,
        )
    assert "Maximum supported duration: 10s" in str(exc_info.value)


def test_validate_duration_seconds_omni_1_2_flash_mode_aware():
    # 15s allowed in Text to Video
    dto_t2v = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
        duration_seconds=15,
    )
    assert dto_t2v.duration_seconds == 15

    # 15s allowed in Frames to Video with Start frame only
    dto_start_only = CreateVeoDto(
        prompt="Test",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
        start_image_asset_id={"id": 1, "type": "source_asset"},
        duration_seconds=15,
    )
    assert dto_start_only.duration_seconds == 15

    # 16s exceeds Field ceiling
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            duration_seconds=16,
        )
    assert "less than or equal to 15" in str(exc_info.value)

    # Start + End frames cap at 10s
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            start_image_asset_id={"id": 1, "type": "source_asset"},
            end_image_asset_id={"id": 2, "type": "source_asset"},
            duration_seconds=12,
        )
    assert "Maximum supported duration: 10s" in str(exc_info.value)

    # Reference images cap at 10s
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            reference_images=[
                ReferenceImageDto(
                    asset_id=1,
                    reference_type=ReferenceImageTypeEnum.ASSET,
                )
            ],
            duration_seconds=12,
        )
    assert "Maximum supported duration: 10s" in str(exc_info.value)

    # Video extension caps at 10s
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            source_video_asset_id={"id": 1, "type": "source_asset"},
            duration_seconds=15,
        )
    assert "Maximum supported duration: 10s" in str(exc_info.value)


OMNI_MODELS = [
    GenerationModelEnum.GEMINI_OMNI,
    GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
    GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
    GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
]


@pytest.mark.parametrize(
    "model",
    [
        *OMNI_MODELS,
        GenerationModelEnum.VEO_3_1_GENERATE_001,
    ],
)
def test_audio_reference_rejected_across_all_models(model):
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Test with audio",
            workspace_id=1,
            generation_model=model,
            reference_audio={"id": 101, "type": "media_item"},
        )
    assert "Audio reference is not supported for video generation" in str(
        exc_info.value
    )

    with pytest.raises(ValidationError) as exc_info_role:
        CreateVeoDto(
            prompt="Test with audio role",
            workspace_id=1,
            generation_model=model,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=101,
                    media_index=0,
                    role="audio_reference",
                )
            ],
        )
    assert "Audio reference is not supported for video generation" in str(
        exc_info_role.value
    )


def test_validate_video_references_and_deduplication():
    # Omni 1.1 and 1.2 accept up to 3 reference videos
    for model in (
        GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
        GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
    ):
        dto = CreateVeoDto(
            prompt="Test multi video refs",
            workspace_id=1,
            generation_model=model,
            reference_videos=[
                {"id": 1, "type": "source_asset"},
                {"id": 2, "type": "media_item", "index": 0},
                {"id": 3, "type": "source_asset"},
            ],
            # Same media_item (id=2, index=0) in source_media_items must deduplicate, not 422
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=2,
                    media_index=0,
                    role="video_reference",
                )
            ],
        )
        assert len(dto.reference_videos) == 3

        # 4 distinct videos across reference_videos + source_media_items must fail
        with pytest.raises(ValidationError) as exc_info:
            CreateVeoDto(
                prompt="Too many videos",
                workspace_id=1,
                generation_model=model,
                reference_videos=[
                    {"id": 1, "type": "source_asset"},
                    {"id": 2, "type": "source_asset"},
                    {"id": 3, "type": "source_asset"},
                ],
                source_media_items=[
                    SourceMediaItemLink(
                        media_item_id=99,
                        media_index=0,
                        role="video_reference",
                    )
                ],
            )
        assert "supports up to 3 reference videos" in str(exc_info.value)

    # Veo 3.1 and retired Omni 1.0 reject video references
    for unsupported in (
        GenerationModelEnum.VEO_3_1_GENERATE_001,
        GenerationModelEnum.GEMINI_OMNI,
        GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
    ):
        with pytest.raises(ValidationError) as exc_info:
            CreateVeoDto(
                prompt="Test unsupported video ref",
                workspace_id=1,
                generation_model=unsupported,
                reference_videos=[{"id": 102, "type": "media_item"}],
            )
        assert "does not support Video as reference" in str(exc_info.value)


def test_validate_per_model_reference_image_limits():
    # Omni 1.2 supports 10 reference images, rejects 11
    dto_12 = CreateVeoDto(
        prompt="Omni 1.2 ten images",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
        reference_images=[
            ReferenceImageDto(
                asset_id=i, reference_type=ReferenceImageTypeEnum.ASSET
            )
            for i in range(1, 11)
        ],
    )
    assert len(dto_12.reference_images) == 10

    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Omni 1.2 eleven images",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            reference_images=[
                ReferenceImageDto(
                    asset_id=i, reference_type=ReferenceImageTypeEnum.ASSET
                )
                for i in range(1, 11)
            ],
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=50,
                    media_index=0,
                    role="image_reference_asset",
                )
            ],
        )
    assert "supports up to 10 reference images" in str(exc_info.value)

    # Omni 1.1 supports 5 reference images, rejects 6
    dto_11 = CreateVeoDto(
        prompt="Omni 1.1 five images",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
        reference_images=[
            ReferenceImageDto(
                asset_id=i, reference_type=ReferenceImageTypeEnum.ASSET
            )
            for i in range(1, 6)
        ],
    )
    assert len(dto_11.reference_images) == 5

    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Omni 1.1 six images",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
            reference_images=[
                ReferenceImageDto(
                    asset_id=i, reference_type=ReferenceImageTypeEnum.ASSET
                )
                for i in range(1, 7)
            ],
        )
    assert "supports up to 5 reference images" in str(exc_info.value)

    # Veo 3.1 supports 3 reference images, rejects 4
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Veo four images",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
            reference_images=[
                ReferenceImageDto(
                    asset_id=i, reference_type=ReferenceImageTypeEnum.ASSET
                )
                for i in range(1, 5)
            ],
        )
    assert "supports up to 3 reference images" in str(exc_info.value)


def test_validate_video_extension_and_omni_min_duration():
    # Omni 1.1 and 1.2 allow video extension
    for model in (
        GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
        GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
    ):
        dto = CreateVeoDto(
            prompt="",
            workspace_id=1,
            generation_model=model,
            source_video_asset_id={"id": 7, "type": "media_item"},
            duration_seconds=8,
        )
        assert dto.source_video_asset_id.id == 7

    # Retired Omni 1.0 rejects video extension
    for retired in (
        GenerationModelEnum.GEMINI_OMNI,
        GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
    ):
        with pytest.raises(ValidationError) as exc_info:
            CreateVeoDto(
                prompt="",
                workspace_id=1,
                generation_model=retired,
                source_video_asset_id={"id": 7, "type": "media_item"},
            )
        assert "does not support video extension" in str(exc_info.value)

    # Omni requires >= 3s duration
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Too short",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            duration_seconds=2,
        )
    assert "requires a minimum duration of 3s" in str(exc_info.value)


@pytest.mark.parametrize("model", OMNI_MODELS)
def test_is_gemini_omni_model_true_for_omni(model):
    assert model.is_gemini_omni_model


@pytest.mark.parametrize(
    "model",
    [
        GenerationModelEnum.VEO_3_1_GENERATE_001,
        GenerationModelEnum.VEO_3_1_LITE_PREVIEW,
        GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE,
    ],
)
def test_is_gemini_omni_model_false_for_non_omni(model):
    assert not model.is_gemini_omni_model


def test_folder_id_defaults_to_root():
    assert CreateVeoDto(prompt="Test", workspace_id=1).folder_id is None


@pytest.mark.parametrize("folder_key", ["folderId", "folder_id"])
def test_folder_id_accepts_camel_and_snake_case(folder_key):
    dto = CreateVeoDto.model_validate(
        {"prompt": "Test", "workspace_id": 1, folder_key: 42}
    )
    assert dto.folder_id == 42


@pytest.mark.parametrize("folder_id", [0, -1, "abc"])
def test_folder_id_rejects_non_positive_and_non_numeric(folder_id):
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto.model_validate(
            {"prompt": "Test", "workspace_id": 1, "folderId": folder_id}
        )
    assert "folderId" in str(exc_info.value)


def test_end_frame_alone_caps_omni_1_2_duration_at_10s():
    dto_ok = CreateVeoDto(
        prompt="End frame only at 10s",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
        end_image_asset_id={"id": 9, "type": "source_asset"},
        duration_seconds=10,
    )
    assert dto_ok.duration_seconds == 10

    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="End frame only at 15s",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            end_image_asset_id={"id": 9, "type": "source_asset"},
            duration_seconds=15,
        )
    assert "Maximum supported duration: 10s" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_media:
        CreateVeoDto(
            prompt="End frame media item at 12s",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=14,
                    media_index=0,
                    role="end_frame",
                )
            ],
            duration_seconds=12,
        )
    assert "Maximum supported duration: 10s" in str(exc_media.value)


def test_negative_clip_index_and_invalid_asset_reference_type_rejected():
    with pytest.raises(ValidationError):
        CreateVeoDto(
            prompt="",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            source_video_asset_id={"id": 1, "type": "media_item", "index": -1},
        )

    with pytest.raises(ValidationError):
        CreateVeoDto(
            prompt="Invalid ref type",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
            start_image_asset_id={"id": 1, "type": "unknown_type"},
        )

    with pytest.raises(ValidationError):
        SourceMediaItemLink(
            media_item_id=1,
            media_index=-1,
            role="start_frame",
        )


def test_empty_prompt_rejected_without_source_video():
    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="   ",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_2_FLASH,
        )
    assert "Prompt is required unless extending a source video" in str(
        exc_info.value
    )


def test_duplicate_reference_images_deduplicated_in_place():
    dto_veo = CreateVeoDto(
        prompt="Veo duplicate image entries",
        workspace_id=1,
        generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
        reference_images=[
            ReferenceImageDto(
                asset_id=7, reference_type=ReferenceImageTypeEnum.ASSET
            )
            for _ in range(4)
        ],
    )
    assert len(dto_veo.reference_images) == 1
    assert dto_veo.reference_images[0].asset_id == 7

    dto_omni11 = CreateVeoDto(
        prompt="Omni 1.1 ten entries of four unique assets plus duplicate media item",
        workspace_id=1,
        generation_model=GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
        reference_images=[
            ReferenceImageDto(
                asset_id=(i % 4) + 1,
                reference_type=ReferenceImageTypeEnum.ASSET,
            )
            for i in range(10)
        ],
        source_media_items=[
            SourceMediaItemLink(
                media_item_id=88,
                media_index=0,
                role="image_reference_asset",
            ),
            SourceMediaItemLink(
                media_item_id=88,
                media_index=0,
                role="image_reference_asset",
            ),
        ],
    )
    assert len(dto_omni11.reference_images) == 4
    assert len(dto_omni11.source_media_items) == 1

    with pytest.raises(ValidationError) as exc_info:
        CreateVeoDto(
            prompt="Omni 1.1 six unique images fails",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_OMNI_1_1_FLASH_PREVIEW,
            reference_images=[
                ReferenceImageDto(
                    asset_id=i + 1,
                    reference_type=ReferenceImageTypeEnum.ASSET,
                )
                for i in range(5)
            ],
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=88,
                    media_index=0,
                    role="image_reference_asset",
                )
            ],
        )
    assert "supports up to 5 reference images" in str(exc_info.value)


def test_frontend_and_backend_video_model_capabilities_stay_in_sync():
    from pathlib import Path
    import re

    repo_root = Path(__file__).resolve().parents[3]
    ts_path = (
        repo_root
        / "frontend"
        / "src"
        / "app"
        / "common"
        / "config"
        / "model-config.ts"
    )
    ts_text = ts_path.read_text(encoding="utf-8")

    # Extract each object block inside MODEL_CONFIGS where type: 'VIDEO'
    block_pattern = re.compile(
        r"\{\s*\n\s*value:\s*'([^']+)',\s*\n\s*viewValue:\s*'[^']+',\s*\n\s*type:\s*'VIDEO',[\s\S]*?capabilities:\s*\{([\s\S]*?)\},\s*\n\s*\}",
    )
    video_blocks = block_pattern.findall(ts_text)
    assert len(video_blocks) >= 6

    for model_value, cap_body in video_blocks:
        enum_member = GenerationModelEnum(model_value)
        max_img_match = re.search(r"maxReferenceImages:\s*(\d+)", cap_body)
        max_vid_match = re.search(r"maxReferenceVideos:\s*(\d+)", cap_body)
        durations_match = re.search(
            r"supportedDurations:\s*\[([^\]]+)\]", cap_body
        )
        modes_match = re.search(r"supportedModes:\s*\[([^\]]+)\]", cap_body)

        assert (
            max_img_match is not None
        ), f"Missing maxReferenceImages for {model_value}"
        assert (
            max_vid_match is not None
        ), f"Missing maxReferenceVideos for {model_value}"
        assert (
            durations_match is not None
        ), f"Missing supportedDurations for {model_value}"
        assert (
            modes_match is not None
        ), f"Missing supportedModes for {model_value}"

        fe_max_images = int(max_img_match.group(1))
        fe_max_videos = int(max_vid_match.group(1))
        fe_durations = [
            int(x.strip())
            for x in durations_match.group(1).split(",")
            if x.strip()
        ]
        fe_supports_extend = "'Extend Video'" in modes_match.group(1)

        assert fe_max_images == enum_member.max_reference_images
        assert fe_max_videos == enum_member.max_reference_videos
        assert fe_supports_extend == enum_member.supports_video_extension
        assert max(fe_durations) == enum_member.max_video_duration()
