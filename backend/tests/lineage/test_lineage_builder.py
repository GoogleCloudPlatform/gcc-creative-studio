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
"""Unit tests for lineage edge builder across all generation modalities."""

from src.common.schema.media_item_model import (
    AssetRoleEnum,
    SourceAssetLink,
    SourceMediaItemLink,
)
from src.lineage.lineage_builder import (
    ExplicitPrimarySpec,
    build_lineage_edges,
)
from src.lineage.schema.item_lineage_model import (
    LineageItemTypeEnum,
    LineageRoleEnum,
)


def test_single_input_image_edit_becomes_primary_with_upgraded_role():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=200,
        child_mime_type="image/png",
        user_prompt="  Make the sky dramatic sunset  ",
        source_media_items=[
            SourceMediaItemLink(
                media_item_id=100,
                media_index=2,
                role=AssetRoleEnum.INPUT,
            )
        ],
    )
    assert len(edges) == 1
    edge = edges[0]
    assert edge.parent_type == LineageItemTypeEnum.MEDIA_ITEM
    assert edge.parent_id == 100
    assert edge.parent_index == 2
    assert edge.role == LineageRoleEnum.IMAGE_EDIT_SOURCE.value
    assert edge.is_primary_parent is True
    assert edge.action_summary == "Make the sky dramatic sunset"


def test_single_input_image_edit_uses_default_summary_when_prompt_blank():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=201,
        child_mime_type="image/jpeg",
        user_prompt="   ",
        source_assets=[
            SourceAssetLink(asset_id=50, role=AssetRoleEnum.INPUT),
        ],
    )
    assert len(edges) == 1
    assert edges[0].is_primary_parent is True
    assert edges[0].role == LineageRoleEnum.IMAGE_EDIT_SOURCE.value
    assert edges[0].action_summary == "Edited image"


def test_single_input_cross_modal_start_frame_is_primary_parent():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=300,
        child_mime_type="video/mp4",
        user_prompt="Slow cinematic camera push in",
        source_media_items=[
            {
                "mediaItemId": 200,
                "mediaIndex": 1,
                "role": "start_frame",
            }
        ],
    )
    assert len(edges) == 1
    edge = edges[0]
    assert edge.parent_type == LineageItemTypeEnum.MEDIA_ITEM
    assert edge.parent_id == 200
    assert edge.parent_index == 1
    assert edge.role == LineageRoleEnum.START_FRAME.value
    assert edge.is_primary_parent is True
    assert edge.action_summary == "Slow cinematic camera push in"


def test_single_composition_only_role_remains_non_primary():
    for comp_role in (
        LineageRoleEnum.CONCATENATION_SOURCE.value,
        LineageRoleEnum.VTO_PERSON.value,
        LineageRoleEnum.MASK.value,
    ):
        edges = build_lineage_edges(
            child_type=LineageItemTypeEnum.MEDIA_ITEM,
            child_id=400,
            child_mime_type="image/png",
            user_prompt="Try on jacket",
            source_assets=[{"asset_id": 10, "role": comp_role}],
        )
        assert len(edges) == 1
        assert edges[0].is_primary_parent is False
        assert edges[0].action_summary is None


def test_multi_input_composition_marks_all_edges_non_primary():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=500,
        child_mime_type="image/png",
        user_prompt="Combine person with style reference",
        source_assets=[{"assetId": 11, "role": "input"}],
        source_media_items=[
            {"media_item_id": 22, "media_index": 0, "role": "style_reference"}
        ],
    )
    assert len(edges) == 2
    assert all(not e.is_primary_parent for e in edges)
    assert all(e.action_summary is None for e in edges)


def test_multi_input_video_extension_marks_extension_source_primary():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=600,
        child_mime_type="video/mp4",
        user_prompt="Continue flying over the mountains",
        source_media_items=[
            {
                "media_item_id": 550,
                "media_index": 0,
                "role": LineageRoleEnum.VIDEO_EXTENSION_SOURCE.value,
            },
            {
                "media_item_id": 551,
                "media_index": 0,
                "role": LineageRoleEnum.VIDEO_EXTENSION_CHUNK.value,
            },
        ],
    )
    assert len(edges) == 2
    assert edges[0].is_primary_parent is True
    assert edges[0].action_summary == "Continue flying over the mountains"
    assert edges[1].is_primary_parent is False
    assert edges[1].action_summary is None


def test_explicit_primary_deduplicates_matching_candidate_and_keeps_secondary():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=700,
        child_mime_type="video/mp4",
        user_prompt="Replace background with neon Tokyo street",
        source_assets=[
            {"asset_id": 91, "role": "image_reference_asset"},
        ],
        source_media_items=[
            {
                "media_item_id": 650,
                "media_index": 1,
                "role": "video_reference",
            },
            {
                "media_item_id": 650,
                "media_index": 0,
                "role": "image_reference_style",
            },
        ],
        explicit_primary=ExplicitPrimarySpec(
            parent_type=LineageItemTypeEnum.MEDIA_ITEM,
            parent_id=650,
            parent_index=1,
            role=LineageRoleEnum.OMNI_EDIT_SOURCE.value,
        ),
    )
    assert len(edges) == 3
    primary = edges[0]
    assert primary.is_primary_parent is True
    assert primary.parent_type == LineageItemTypeEnum.MEDIA_ITEM
    assert primary.parent_id == 650
    assert primary.parent_index == 1
    assert primary.role == LineageRoleEnum.OMNI_EDIT_SOURCE.value
    assert primary.action_summary == "Replace background with neon Tokyo street"

    secondary = edges[1:]
    assert all(not e.is_primary_parent for e in secondary)
    assert (secondary[0].parent_type, secondary[0].parent_id) == (
        LineageItemTypeEnum.SOURCE_ASSET,
        91,
    )
    # Variation index 0 on item 650 is distinct from index 1, so it is preserved
    assert (
        secondary[1].parent_type,
        secondary[1].parent_id,
        secondary[1].parent_index,
    ) == (LineageItemTypeEnum.MEDIA_ITEM, 650, 0)


def test_self_loops_and_invalid_entries_are_ignored():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.SOURCE_ASSET,
        child_id=42,
        source_assets=[
            None,
            {"asset_id": "bad"},
            {"asset_id": 0},
            {"asset_id": 42, "role": "crop_source"},  # self-loop
            {"asset_id": 15, "role": "crop_source"},
            {"asset_id": 15, "role": "crop_source"},  # duplicate
        ],
        source_media_items=[
            None,
            {"media_item_id": "bad"},
            {"media_item_id": -5},
        ],
    )
    assert len(edges) == 1
    assert edges[0].parent_id == 15
    assert edges[0].is_primary_parent is True
    assert edges[0].action_summary == "Cropped & edited image"


def test_multi_input_video_promotes_sole_video_reference():
    edges = build_lineage_edges(
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=810,
        child_mime_type="video/mp4",
        user_prompt="Add rain and neon reflections",
        source_assets=[
            {"asset_id": 55, "role": "audio_reference"},
        ],
        source_media_items=[
            {
                "media_item_id": 809,
                "media_index": 0,
                "role": "video_reference",
            },
        ],
    )
    assert len(edges) == 2
    primary = [e for e in edges if e.is_primary_parent]
    secondary = [e for e in edges if not e.is_primary_parent]
    assert len(primary) == 1
    assert primary[0].parent_type == LineageItemTypeEnum.MEDIA_ITEM
    assert primary[0].parent_id == 809
    assert primary[0].role == "video_reference"
    assert primary[0].action_summary == "Add rain and neon reflections"
    assert len(secondary) == 1
    assert secondary[0].parent_type == LineageItemTypeEnum.SOURCE_ASSET
    assert secondary[0].parent_id == 55
