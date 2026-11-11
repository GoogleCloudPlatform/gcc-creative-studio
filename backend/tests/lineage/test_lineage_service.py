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
"""Unit tests for LineageService and record_lineage_safely."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import pytest

from src.common.base_dto import MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.lineage.lineage_builder import ExplicitPrimarySpec
from src.lineage.lineage_service import LineageService, record_lineage_safely
from src.lineage.repository.lineage_repository import AncestorChainRow
from src.lineage.schema.item_lineage_model import (
    ItemLineage,
    LineageItemTypeEnum,
    LineageRoleEnum,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
)
from src.users.user_model import UserModel, UserRoleEnum


def _make_user(*, is_admin: bool = False) -> UserModel:
    return UserModel(
        id=1,
        email="creator@example.com",
        name="Creator",
        roles=[UserRoleEnum.ADMIN] if is_admin else [UserRoleEnum.USER],
    )


def _scalars_result(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


@pytest.mark.anyio
async def test_record_lineage_safely_guards_and_error_recovery():
    # Invalid child_id / workspace_id -> immediate no-op
    mock_db = AsyncMock()
    await record_lineage_safely(
        mock_db,
        workspace_id=0,
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=10,
        source_assets=[{"asset_id": 1}],
    )
    mock_db.execute.assert_not_called()

    # Non-async MagicMock DB -> safely skipped without awaiting non-coroutines
    sync_mock_db = MagicMock()
    await record_lineage_safely(
        sync_mock_db,
        workspace_id=1,
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=10,
        source_assets=[{"asset_id": 1}],
    )
    sync_mock_db.execute.assert_not_called()

    # skip_if_exists=True short-circuits when edges already present
    with patch(
        "src.lineage.lineage_service.LineageRepository"
    ) as repo_cls_mock:
        repo_inst = AsyncMock()
        repo_inst.has_any_edges_for_child.return_value = True
        repo_cls_mock.return_value = repo_inst

        await record_lineage_safely(
            mock_db,
            workspace_id=1,
            child_type=LineageItemTypeEnum.MEDIA_ITEM,
            child_id=10,
            source_assets=[{"asset_id": 1}],
            skip_if_exists=True,
        )
        repo_inst.has_any_edges_for_child.assert_awaited_once()
        repo_inst.replace_child_edges.assert_not_called()

    # Database failure triggers rollback and never raises
    failing_db = AsyncMock()
    with patch(
        "src.lineage.lineage_service.LineageRepository"
    ) as repo_cls_mock:
        repo_inst = AsyncMock()
        repo_inst.replace_child_edges.side_effect = RuntimeError("DB boom")
        repo_cls_mock.return_value = repo_inst

        await record_lineage_safely(
            failing_db,
            workspace_id=1,
            child_type=LineageItemTypeEnum.MEDIA_ITEM,
            child_id=10,
            explicit_primary=ExplicitPrimarySpec(
                parent_type=LineageItemTypeEnum.SOURCE_ASSET,
                parent_id=5,
                role=LineageRoleEnum.CROP_SOURCE.value,
            ),
        )
        failing_db.rollback.assert_awaited_once()


def _fake_sign_gcs_uri(uri: str) -> str:
    prefix = "gs://"
    trimmed = uri.removeprefix(prefix)
    return f"https://signed.example/{trimmed}"


@pytest.mark.anyio
async def test_get_item_lineage_multi_hop_cross_modal_spine_and_derivatives():
    now = datetime.datetime(2026, 5, 1, 12, 0, tzinfo=datetime.UTC)
    lineage_repo = AsyncMock()
    workspace_repo = AsyncMock()
    workspace_repo.get_by_id.return_value = MagicMock(id=7)
    workspace_auth = AsyncMock()
    iam_signer = MagicMock()
    iam_signer.generate_presigned_url.side_effect = _fake_sign_gcs_uri
    db = AsyncMock()

    # Spine:
    # SourceAsset #10 (uploaded photo)
    #   -> MediaItem #20 (4 image variations; variation #2 chosen next!)
    #   -> SourceAsset #30 (cropped & annotated asset)
    #   -> MediaItem #40 (Start Frame -> Video)
    #   -> MediaItem #50 (Edited with Omni - target item)
    lineage_repo.get_primary_ancestor_chain.return_value = [
        AncestorChainRow(
            id=1,
            child_type="media_item",
            child_id=20,
            child_index=None,
            parent_type="source_asset",
            parent_id=10,
            parent_index=0,
            role="image_edit_source",
            action_summary="Place product on marble pedestal",
            depth=4,
        ),
        AncestorChainRow(
            id=2,
            child_type="source_asset",
            child_id=30,
            child_index=0,
            parent_type="media_item",
            parent_id=20,
            parent_index=2,  # Picks variation #2 of MediaItem #20!
            role="crop_source",
            action_summary="Cropped & annotated",
            depth=3,
        ),
        AncestorChainRow(
            id=3,
            child_type="media_item",
            child_id=40,
            child_index=None,
            parent_type="source_asset",
            parent_id=30,
            parent_index=0,
            role="start_frame",
            action_summary="Camera orbits around pedestal",
            depth=2,
        ),
        AncestorChainRow(
            id=4,
            child_type="media_item",
            child_id=50,
            child_index=None,
            parent_type="media_item",
            parent_id=40,
            parent_index=0,
            role="omni_edit_source",
            action_summary="Add golden hour light rays",
            depth=1,
        ),
    ]

    # Derivatives of MediaItem #50:
    # - MediaItem #60 has both passive + primary edge -> deduplicated to primary
    # - MediaItem #61 is PROCESSING -> filtered out
    # - MediaItem #62 is soft-deleted -> filtered out
    # - SourceAsset #63 is an active cropped asset -> included!
    lineage_repo.get_direct_derivative_edges.return_value = [
        ItemLineage(
            id=10,
            workspace_id=7,
            child_type="media_item",
            child_id=60,
            parent_type="media_item",
            parent_id=50,
            parent_index=0,
            role="video_reference",
            is_primary_parent=False,
        ),
        ItemLineage(
            id=11,
            workspace_id=7,
            child_type="media_item",
            child_id=60,
            parent_type="media_item",
            parent_id=50,
            parent_index=0,
            role="omni_edit_source",
            is_primary_parent=True,
            action_summary="Add rain reflections",
        ),
        ItemLineage(
            id=12,
            workspace_id=7,
            child_type="media_item",
            child_id=61,
            parent_type="media_item",
            parent_id=50,
            parent_index=0,
            role="omni_edit_source",
            is_primary_parent=True,
            action_summary="In progress edit",
        ),
        ItemLineage(
            id=13,
            workspace_id=7,
            child_type="media_item",
            child_id=62,
            parent_type="media_item",
            parent_id=50,
            parent_index=0,
            role="omni_edit_source",
            is_primary_parent=True,
            action_summary="Deleted edit",
        ),
        ItemLineage(
            id=14,
            workspace_id=7,
            child_type="source_asset",
            child_id=63,
            parent_type="media_item",
            parent_id=50,
            parent_index=0,
            role="crop_source",
            is_primary_parent=True,
            action_summary="Cropped frame",
        ),
    ]

    m20 = MediaItem(
        id=20,
        workspace_id=7,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model="gemini-2.5-flash-image",
        original_prompt="Place product on marble pedestal",
        gcs_uris=[
            "gs://b/m20_0.png",
            "gs://b/m20_1.png",
            "gs://b/m20_2.png",
        ],
        status=JobStatusEnum.COMPLETED,
        created_at=now,
    )
    m40 = MediaItem(
        id=40,
        workspace_id=7,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        model="veo-3.1-generate-001",
        original_prompt="Camera orbits around pedestal",
        gcs_uris=["gs://b/m40.mp4"],
        thumbnail_uris=["gs://b/m40_thumb.jpg"],
        status=JobStatusEnum.COMPLETED,
        created_at=now,
    )
    m50 = MediaItem(
        id=50,
        workspace_id=7,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        model="veo-3.1-lite-generate-001",
        original_prompt="Add golden hour light rays",
        gcs_uris=["gs://b/m50.mp4"],
        thumbnail_uris=["gs://b/m50_thumb.jpg"],
        status=JobStatusEnum.COMPLETED,
        created_at=now,
    )
    m60 = MediaItem(
        id=60,
        workspace_id=7,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        model="veo-3.1-lite-generate-001",
        original_prompt="Add rain reflections",
        gcs_uris=["gs://b/m60.mp4"],
        thumbnail_uris=["gs://b/m60_thumb.jpg"],
        status=JobStatusEnum.COMPLETED,
        created_at=now,
    )
    m61_processing = MediaItem(
        id=61,
        workspace_id=7,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        status=JobStatusEnum.PROCESSING,
    )
    m62_deleted = MediaItem(
        id=62,
        workspace_id=7,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        status=JobStatusEnum.COMPLETED,
        deleted_at=now,
    )

    a10 = SourceAsset(
        id=10,
        workspace_id=7,
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        mime_type=MimeTypeEnum.IMAGE_JPEG,
        original_filename="bottle.jpg",
        gcs_uri="gs://b/a10.jpg",
        created_at=now,
    )
    a30 = SourceAsset(
        id=30,
        workspace_id=7,
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        original_filename="cropped.png",
        gcs_uri="gs://b/a30.png",
        created_at=now,
    )
    a63 = SourceAsset(
        id=63,
        workspace_id=7,
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        original_filename="frame_crop.png",
        gcs_uri="gs://b/a63.png",
        created_at=now,
    )

    # 1st: target lookup; 2nd: batch media lookup; 3rd: batch asset lookup
    db.execute.side_effect = [
        _scalars_result([m50]),
        _scalars_result([m20, m40, m50, m60, m61_processing, m62_deleted]),
        _scalars_result([a10, a30, a63]),
    ]

    svc = LineageService(
        lineage_repo=lineage_repo,
        workspace_repo=workspace_repo,
        workspace_auth=workspace_auth,
        iam_signer_credentials=iam_signer,
        db=db,
    )
    resp = await svc.get_item_lineage(
        item_type=LineageItemTypeEnum.MEDIA_ITEM,
        item_id=50,
        current_user=_make_user(),
    )

    assert [(n.item_type, n.id, n.media_index) for n in resp.spine] == [
        (LineageItemTypeEnum.SOURCE_ASSET, 10, 0),
        (LineageItemTypeEnum.MEDIA_ITEM, 20, 2),
        (LineageItemTypeEnum.SOURCE_ASSET, 30, 0),
        (LineageItemTypeEnum.MEDIA_ITEM, 40, 0),
        (LineageItemTypeEnum.MEDIA_ITEM, 50, 0),
    ]
    assert resp.spine[0].prompt == "Uploaded: bottle.jpg"
    assert resp.spine[1].thumbnail_url == "https://signed.example/b/m20_2.png"
    assert resp.spine[2].prompt == "Cropped & annotated"
    assert resp.spine[3].role == "start_frame"
    assert resp.spine[4].prompt == "Add golden hour light rays"

    assert [(d.item_type, d.id, d.role) for d in resp.derivatives] == [
        (LineageItemTypeEnum.MEDIA_ITEM, 60, "omni_edit_source"),
        (LineageItemTypeEnum.SOURCE_ASSET, 63, "crop_source"),
    ]


@pytest.mark.anyio
async def test_get_item_lineage_tombstones_youtube_and_system_asset_auth():
    lineage_repo = AsyncMock()
    workspace_repo = AsyncMock()
    workspace_auth = AsyncMock()
    iam_signer = MagicMock()
    iam_signer.generate_presigned_url.side_effect = _fake_sign_gcs_uri
    db = AsyncMock()

    # Target is a SYSTEM SourceAsset -> skips workspace_repo and workspace_auth
    sys_target = SourceAsset(
        id=99,
        workspace_id=1,
        scope=AssetScopeEnum.SYSTEM,
        asset_type=AssetTypeEnum.YOUTUBE_VIDEO,
        mime_type=MimeTypeEnum.VIDEO_MP4,
        original_filename="demo_yt",
        external_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    deleted_parent = MediaItem(
        id=11,
        workspace_id=1,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        original_prompt="Deleted root prompt",
        gcs_uris=["gs://b/secret.png"],
        status=JobStatusEnum.COMPLETED,
        deleted_at=datetime.datetime.now(datetime.UTC),
    )

    lineage_repo.get_primary_ancestor_chain.return_value = [
        AncestorChainRow(
            id=1,
            child_type="media_item",
            child_id=12,  # missing row altogether
            child_index=None,
            parent_type="media_item",
            parent_id=11,  # soft-deleted row
            parent_index=0,
            role="image_edit_source",
            action_summary="Missing step edit",
            depth=2,
        ),
        AncestorChainRow(
            id=2,
            child_type="source_asset",
            child_id=99,
            child_index=0,
            parent_type="media_item",
            parent_id=12,
            parent_index=0,
            role="crop_source",
            action_summary="Extracted clip",
            depth=1,
        ),
    ]
    lineage_repo.get_direct_derivative_edges.return_value = []

    db.execute.side_effect = [
        _scalars_result([sys_target]),
        _scalars_result([deleted_parent]),
        _scalars_result([sys_target]),
    ]

    svc = LineageService(
        lineage_repo=lineage_repo,
        workspace_repo=workspace_repo,
        workspace_auth=workspace_auth,
        iam_signer_credentials=iam_signer,
        db=db,
    )
    resp = await svc.get_item_lineage(
        item_type=LineageItemTypeEnum.SOURCE_ASSET,
        item_id=99,
        current_user=_make_user(is_admin=False),
    )
    workspace_auth.authorize.assert_not_called()

    # Step 0: soft-deleted root -> tombstone without presigned URLs
    assert resp.spine[0].deleted is True
    assert resp.spine[0].thumbnail_url is None
    assert resp.spine[0].prompt == "Deleted root prompt"
    # Step 1: missing row -> tombstone with edge summary preserved
    assert resp.spine[1].deleted is True
    assert resp.spine[1].prompt == "Missing step edit"
    # Step 2: YouTube asset -> YouTube thumbnail + external preview URL
    assert (
        resp.spine[2].thumbnail_url
        == "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
    )
    assert (
        resp.spine[2].preview_url
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )


@pytest.mark.anyio
async def test_get_item_lineage_raises_404_for_missing_targets():
    lineage_repo = AsyncMock()
    workspace_repo = AsyncMock()
    workspace_auth = AsyncMock()
    iam_signer = MagicMock()
    db = AsyncMock()
    db.execute.return_value = _scalars_result([])

    svc = LineageService(
        lineage_repo=lineage_repo,
        workspace_repo=workspace_repo,
        workspace_auth=workspace_auth,
        iam_signer_credentials=iam_signer,
        db=db,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_item_lineage(
            item_type=LineageItemTypeEnum.MEDIA_ITEM,
            item_id=404,
            current_user=_make_user(),
        )
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as asset_exc:
        await svc.get_item_lineage(
            item_type=LineageItemTypeEnum.SOURCE_ASSET,
            item_id=404,
            current_user=_make_user(),
        )
    assert asset_exc.value.status_code == 404
