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
"""Tests for Gallery Service."""


from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    SourceAssetLink,
)
from src.folders.dto.folder_dto import ConflictStrategyEnum
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.unified_gallery_response import (
    UnifiedGalleryItemResponse,
)
from src.galleries.gallery_service import GalleryService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)


@pytest.fixture(name="service")
def fixture_service():
    mock_media_repo = AsyncMock()
    mock_source_asset_repo = AsyncMock()
    mock_unified_gallery_repo = AsyncMock()
    mock_user_repo = AsyncMock()
    mock_workspace_repo = AsyncMock()
    mock_iam_signer = MagicMock(spec=IamSignerCredentials)
    mock_iam_signer.generate_presigned_url_async = AsyncMock()
    mock_workspace_auth = AsyncMock()
    default_ws = WorkspaceModel(
        id=88,
        name="Shared WS",
        owner_id=999,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    mock_workspace_auth.authorize.return_value = default_ws
    mock_workspace_auth.authorize_write.return_value = default_ws
    mock_imagen_service = AsyncMock()
    mock_gcs_service = MagicMock()
    mock_tags_repo = AsyncMock()
    mock_folder_repo = AsyncMock()
    mock_db = AsyncMock()

    @asynccontextmanager
    async def fake_begin_nested():
        yield

    mock_db.begin_nested = MagicMock(side_effect=fake_begin_nested)

    service = GalleryService(
        media_repo=mock_media_repo,
        source_asset_repo=mock_source_asset_repo,
        unified_gallery_repo=mock_unified_gallery_repo,
        user_repo=mock_user_repo,
        workspace_repo=mock_workspace_repo,
        iam_signer_credentials=mock_iam_signer,
        workspace_auth=locals().get("workspace_auth", mock_workspace_auth),
        imagen_service=mock_imagen_service,
        gcs_service=mock_gcs_service,
        tags_repo=mock_tags_repo,
        folder_repo=mock_folder_repo,
        db=mock_db,
    )

    # Attach mocks for ease of use in tests
    service.mock_media_repo = mock_media_repo
    service.mock_source_asset_repo = mock_source_asset_repo
    service.mock_unified_gallery_repo = mock_unified_gallery_repo
    service.mock_user_repo = mock_user_repo
    service.mock_workspace_repo = mock_workspace_repo
    service.mock_iam_signer = mock_iam_signer
    service.mock_workspace_auth = mock_workspace_auth
    service.mock_gcs_service = mock_gcs_service
    service.mock_tags_repo = mock_tags_repo
    service.mock_folder_repo = mock_folder_repo
    service.mock_db = mock_db

    return service


@pytest.mark.anyio
async def test_enrich_source_asset_link(service):
    from src.source_assets.schema.source_asset_model import AssetScopeEnum

    current_user = UserModel(
        id=1, email="user@test.com", name="User", roles=[UserRoleEnum.USER]
    )
    # Setup link
    link = SourceAssetLink(asset_id=123, role=AssetRoleEnum.INPUT)

    # Mock source_asset_repo.get_by_id
    mock_asset = MagicMock()
    mock_asset.workspace_id = 10
    mock_asset.scope = AssetScopeEnum.PRIVATE
    mock_asset.gcs_uri = "gs://bucket/asset.jpg"
    mock_asset.thumbnail_gcs_uri = "gs://bucket/thumb.jpg"
    mock_asset.mime_type = "image/jpeg"
    service.mock_source_asset_repo.get_by_id.return_value = mock_asset

    # Mock iam_signer_credentials
    service.mock_iam_signer.generate_presigned_url_async.side_effect = [
        "https://signed.url/asset.jpg",
        "https://signed.url/thumb.jpg",
    ]

    result = await service._enrich_source_asset_link(
        link, item_workspace_id=10, current_user=current_user
    )

    assert result is not None
    assert result.presigned_url == "https://signed.url/asset.jpg"
    assert result.presigned_thumbnail_url == "https://signed.url/thumb.jpg"
    service.mock_source_asset_repo.get_by_id.assert_called_once_with(123)


@pytest.mark.anyio
async def test_get_paginated_gallery_admin(service):
    # Setup User and Search DTO
    current_user = UserModel(
        id=1,
        email="admin@test.com",
        name="Admin",
        roles=[UserRoleEnum.ADMIN],
    )

    search_dto = GallerySearchDto(limit=10, offset=0)

    # Mock unified_gallery_repo.query
    mock_query_result = MagicMock()
    mock_item = UnifiedGalleryItemResponse(
        id=1,
        workspace_id=99,
        created_at=datetime.now(),
        item_type="media_item",
        gcs_uris=["gs://bucket/image.png"],
        thumbnail_uris=[],
    )

    mock_query_result.data = [mock_item]
    mock_query_result.count = 1
    mock_query_result.page = 1
    mock_query_result.page_size = 10
    mock_query_result.total_pages = 1

    service.mock_unified_gallery_repo.query.return_value = mock_query_result
    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://signed.url/image.png"
    )

    result = await service.get_paginated_gallery(search_dto, current_user)

    assert result.count == 1
    assert len(result.data) == 1
    assert result.data[0].presigned_urls[0] == "https://signed.url/image.png"


@pytest.mark.anyio
async def test_get_paginated_gallery_regular_user(service):
    # Status should be forced to COMPLETED for regular user
    current_user = UserModel(
        id=2,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    search_dto = GallerySearchDto(
        limit=10, offset=0, status=JobStatusEnum.FAILED
    )

    mock_query_result = MagicMock()
    mock_query_result.data = []
    service.mock_unified_gallery_repo.query.return_value = mock_query_result

    await service.get_paginated_gallery(search_dto, current_user)

    # Verify status is overwritten
    assert search_dto.status == JobStatusEnum.COMPLETED


@pytest.mark.anyio
async def test_get_paginated_gallery_with_folder_id_success(service):
    current_user = UserModel(
        id=2,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )
    search_dto = GallerySearchDto(
        workspace_id=1, folder_id=10, limit=10, offset=0
    )

    mock_folder = MagicMock()
    mock_folder.id = 10
    mock_folder.workspace_id = 1
    mock_folder.name = "Folder 10"
    service.mock_folder_repo.get_folder_by_id.return_value = mock_folder

    mock_query_result = MagicMock()
    mock_query_result.data = []
    mock_query_result.count = 0
    mock_query_result.page = 1
    mock_query_result.page_size = 10
    mock_query_result.total_pages = 0
    service.mock_unified_gallery_repo.query.return_value = mock_query_result

    res = await service.get_paginated_gallery(search_dto, current_user)
    assert res.count == 0


@pytest.mark.anyio
async def test_get_paginated_gallery_with_folder_id_not_found(service):
    current_user = UserModel(
        id=2,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )
    search_dto = GallerySearchDto(
        workspace_id=1, folder_id=999, limit=10, offset=0
    )

    service.mock_folder_repo.get_folder_by_id.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await service.get_paginated_gallery(search_dto, current_user)
    assert exc_info.value.status_code == 404
    assert "not found in this workspace" in exc_info.value.detail


@pytest.mark.anyio
async def test_get_paginated_gallery_with_folder_id_workspace_mismatch(service):
    current_user = UserModel(
        id=2,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )
    search_dto = GallerySearchDto(
        workspace_id=1, folder_id=10, limit=10, offset=0
    )

    # Folder belongs to workspace 2 instead of workspace 1
    mock_folder = MagicMock()
    mock_folder.id = 10
    mock_folder.workspace_id = 2
    mock_folder.name = "Folder in WS2"
    service.mock_folder_repo.get_folder_by_id.return_value = mock_folder

    with pytest.raises(HTTPException) as exc_info:
        await service.get_paginated_gallery(search_dto, current_user)
    assert exc_info.value.status_code == 404
    assert "not found in this workspace" in exc_info.value.detail


@pytest.mark.anyio
async def test_get_media_by_id_success(service):
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    # Use real MediaItemModel
    item = MediaItemModel(
        workspace_id=99,
        user_email="user@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://bucket/img.jpg"],
    )
    service.mock_media_repo.get_by_id.return_value = item

    # Mock workspace repo
    mock_workspace = MagicMock()
    service.mock_workspace_repo.get_by_id.return_value = mock_workspace

    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://signed.url/img.jpg"
    )

    result = await service.get_media_by_id(123, current_user)

    assert result is not None
    service.mock_workspace_auth.authorize.assert_called_once_with(
        workspace_id=99,
        user=current_user,
    )
    assert result.presigned_urls[0] == "https://signed.url/img.jpg"


@pytest.mark.anyio
async def test_bulk_delete_success(service):
    from src.galleries.dto.bulk_delete_dto import (
        BulkDeleteDto,
        BulkDeleteItemDto,
    )

    bulk_dto = BulkDeleteDto(
        workspace_id=99,
        items=[
            BulkDeleteItemDto(id=1, type="media_item"),
            BulkDeleteItemDto(id=2, type="source_asset"),
        ],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    mock_media = MagicMock(user_id=1, workspace_id=99)
    service.mock_media_repo.get_by_id.return_value = mock_media

    mock_asset = MagicMock(user_id=1, workspace_id=99)
    service.mock_source_asset_repo.get_by_id.return_value = mock_asset

    result = await service.bulk_delete(bulk_dto, current_user)

    assert result["deleted_count"] == 2
    service.mock_media_repo.soft_delete.assert_called_once_with(1, deleted_by=1)
    service.mock_source_asset_repo.soft_delete.assert_called_once_with(
        2, deleted_by=1
    )


@pytest.mark.anyio
async def test_bulk_copy_success(service):
    from pydantic import BaseModel

    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto

    # Create dummy models due to exclude fields setups
    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[BulkCopyItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    mock_media = DummyMedia(
        id=1,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.return_value = mock_media

    result = await service.bulk_copy(bulk_dto, current_user)

    assert result["copied_count"] == 1
    # Verify create was called with target_workspace_id and updated user references
    service.mock_media_repo.create.assert_called_once()
    args, kwargs = service.mock_media_repo.create.call_args
    assert args[0]["workspace_id"] == 88
    assert "folder_id" not in args[0]


@pytest.mark.anyio
async def test_bulk_download_success(service):
    from src.galleries.dto.bulk_download_dto import (
        BulkDownloadDto,
        BulkDownloadItemDto,
    )

    bulk_dto = BulkDownloadDto(
        workspace_id=99,
        items=[BulkDownloadItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    mock_media = MagicMock(id=1, gcs_uris=["gs://bucket/image.png"])
    # Return string representation like "image/png" to bypass validation splits
    mock_media.mime_type = "image/png"
    service.mock_media_repo.get_by_id.return_value = mock_media

    service.mock_gcs_service.download_bytes_from_gcs.return_value = (
        b"fake-content"
    )
    service.mock_workspace_auth.authorize.return_value = None

    response = await service.bulk_download(bulk_dto, current_user)

    assert response.status_code == 200
    assert "application/zip" in response.headers["Content-Type"]


@pytest.mark.anyio
async def test_get_media_by_id_with_source_media_items(service):
    from src.common.schema.media_item_model import SourceMediaItemLink

    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    item = MediaItemModel(
        workspace_id=99,
        user_email="user@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://bucket/img.jpg"],
        source_media_items=[
            SourceMediaItemLink(
                media_item_id=456,
                media_index=0,
                role=AssetRoleEnum.INPUT,
            ),
        ],
    )

    parent_sourced = MediaItemModel(
        id=456,
        workspace_id=99,
        user_email="u",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://bucket/parent.jpg"],
    )

    def get_by_id_side_effect(id, **kwargs):
        if id == 123:
            return item
        if id == 456:
            return parent_sourced
        return None

    service.mock_media_repo.get_by_id.side_effect = get_by_id_side_effect

    service.mock_workspace_repo.get_by_id.return_value = MagicMock()
    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://signed.url"
    )

    result = await service.get_media_by_id(123, current_user)

    assert result is not None
    assert len(result.enriched_source_media_items) == 1
    assert (
        result.enriched_source_media_items[0].presigned_url
        == "https://signed.url"
    )


@pytest.mark.anyio
async def test_restore_item_media_item(service):
    admin_user = UserModel(
        id=1,
        email="admin@test.com",
        name="Admin",
        roles=[UserRoleEnum.ADMIN],
    )
    service.mock_media_repo.restore.return_value = True

    result = await service.restore_item(1, "media_item", admin_user)
    assert result is True
    service.mock_media_repo.restore.assert_called_once_with(1)


@pytest.mark.anyio
async def test_restore_item_source_asset(service):
    admin_user = UserModel(
        id=1,
        email="admin@test.com",
        name="Admin",
        roles=[UserRoleEnum.ADMIN],
    )
    service.mock_source_asset_repo.restore.return_value = True

    result = await service.restore_item(1, "source_asset", admin_user)
    assert result is True
    service.mock_source_asset_repo.restore.assert_called_once_with(1)


@pytest.mark.anyio
async def test_restore_item_forbidden(service):
    regular_user = UserModel(
        id=2,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )
    with pytest.raises(HTTPException) as exc:
        await service.restore_item(1, "media_item", regular_user)
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_bulk_copy_source_asset(service):
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
        SourceAssetModel,
    )

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[BulkCopyItemDto(id=5, type="source_asset")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    asset = SourceAssetModel(
        id=5,
        workspace_id=99,
        folder_id=15,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h",
        scope=AssetScopeEnum.PRIVATE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
    )
    service.mock_source_asset_repo.get_by_id.return_value = asset

    result = await service.bulk_copy(bulk_dto, current_user)
    assert result["copied_count"] == 1
    service.mock_source_asset_repo.create.assert_called_once()
    args, kwargs = service.mock_source_asset_repo.create.call_args
    assert args[0]["workspace_id"] == 88
    assert "folder_id" not in args[0]


@pytest.mark.anyio
async def test_bulk_delete_different_workspace(service):
    from src.galleries.dto.bulk_delete_dto import (
        BulkDeleteDto,
        BulkDeleteItemDto,
    )

    bulk_dto = BulkDeleteDto(
        workspace_id=99,
        items=[BulkDeleteItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1, email="u@t.com", name="U", roles=[UserRoleEnum.USER]
    )

    # Item in DIFFERENT workspace (88 vs 99)
    mock_media = MagicMock(id=1, workspace_id=88, user_id=1)
    service.mock_media_repo.get_by_id.return_value = mock_media

    result = await service.bulk_delete(bulk_dto, current_user)
    assert result["deleted_count"] == 0
    assert not service.mock_media_repo.soft_delete.called


@pytest.mark.anyio
async def test_bulk_delete_unauthorized(service):
    from src.galleries.dto.bulk_delete_dto import (
        BulkDeleteDto,
        BulkDeleteItemDto,
    )

    bulk_dto = BulkDeleteDto(
        workspace_id=99,
        items=[BulkDeleteItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1, email="u@t.com", name="U", roles=[UserRoleEnum.USER]
    )

    # Item owned by someone else (2 vs 1)
    mock_media = MagicMock(id=1, workspace_id=99, user_id=2)
    service.mock_media_repo.get_by_id.return_value = mock_media

    result = await service.bulk_delete(bulk_dto, current_user)
    assert result["deleted_count"] == 0
    assert not service.mock_media_repo.soft_delete.called


@pytest.mark.anyio
async def test_restore_item_unsupported_type(service):
    admin_user = UserModel(
        id=1, email="a@t.com", name="A", roles=[UserRoleEnum.ADMIN]
    )
    with pytest.raises(HTTPException) as exc:
        await service.restore_item(1, "unknown_type", admin_user)
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_get_media_by_id_with_both_source_references(service):
    from src.common.schema.media_item_model import SourceMediaItemLink
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
        SourceAssetModel,
    )

    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    item = MediaItemModel(
        workspace_id=99,
        user_email="user@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://bucket/img.jpg"],
        source_assets=[
            SourceAssetLink(
                asset_id=123,
                role=AssetRoleEnum.INPUT,
            )
        ],
        source_media_items=[
            SourceMediaItemLink(
                media_item_id=456,
                media_index=0,
                role=AssetRoleEnum.INPUT,
            ),
        ],
    )

    parent_sourced = MediaItemModel(
        id=456,
        workspace_id=99,
        user_email="u",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://bucket/parent.jpg"],
    )

    source_asset = SourceAssetModel(
        id=789,
        workspace_id=99,
        user_id=1,
        gcs_uri="gs://bucket/asset.jpg",
        thumbnail_gcs_uri="gs://bucket/thumb.jpg",
        original_filename="asset.jpg",
        file_hash="hash_789",
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        mime_type=MimeTypeEnum.IMAGE_JPEG,
    )

    def get_by_id_side_effect(id, **kwargs):
        if id == 123:
            return item
        if id == 456:
            return parent_sourced
        return None

    service.mock_media_repo.get_by_id.side_effect = get_by_id_side_effect
    service.mock_source_asset_repo.get_by_id.return_value = source_asset

    service.mock_workspace_repo.get_by_id.return_value = MagicMock()
    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://signed.url"
    )

    result = await service.get_media_by_id(123, current_user)

    assert result is not None
    assert len(result.enriched_source_media_items) == 1
    assert (
        result.enriched_source_media_items[0].presigned_url
        == "https://signed.url"
    )
    assert len(result.enriched_source_assets) == 1
    assert (
        result.enriched_source_assets[0].presigned_url == "https://signed.url"
    )


@pytest.mark.anyio
async def test_enrich_unified_item_youtube_asset(service):
    mock_item = UnifiedGalleryItemResponse(
        id=10,
        workspace_id=99,
        created_at=datetime.now(),
        item_type="source_asset",
        gcs_uris=[],
        thumbnail_uris=[],
        metadata={
            "asset_type": "youtube_video",
            "external_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )

    enriched = await service._enrich_unified_item(mock_item)

    assert enriched.presigned_urls == [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ]
    assert enriched.presigned_thumbnail_urls == [
        "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
    ]


def test_unified_gallery_item_response_none_gcs_uris_filter():
    # Test that None elements in gcs_uris or thumbnail_uris are stripped out
    raw_data = {
        "id": 1,
        "workspace_id": 1,
        "created_at": datetime.now(),
        "item_type": "source_asset",
        "gcs_uris": [None],
        "thumbnail_uris": [None],
    }
    item = UnifiedGalleryItemResponse.model_validate(raw_data)
    assert item.gcs_uris == []
    assert item.thumbnail_uris == []


@pytest.mark.anyio
async def test_bulk_move_media_item_success(service):
    from pydantic import BaseModel

    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    mock_media = DummyMedia(
        id=1,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.return_value = mock_media

    result = await service.bulk_move(bulk_dto, current_user)

    assert result["moved_count"] == 1
    service.mock_tags_repo.clear_tags_for_media_item.assert_called_once_with(1)
    service.mock_media_repo.update.assert_not_called()
    assert service.mock_db.execute.call_count == 1
    assert service.mock_db.flush.call_count == 1
    service.mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_bulk_move_media_item_same_workspace(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list[str] = []

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    mock_media = DummyMedia(
        id=1,
        workspace_id=88,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.return_value = mock_media

    result = await service.bulk_move(bulk_dto, current_user)

    assert result["moved_count"] == 1
    service.mock_tags_repo.clear_tags_for_media_item.assert_not_called()
    service.mock_media_repo.update.assert_not_called()
    assert service.mock_db.execute.call_count == 1
    assert service.mock_db.flush.call_count == 1
    service.mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_bulk_move_source_asset_success(service):
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
        SourceAssetModel,
    )

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=5, type="source_asset")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    asset = SourceAssetModel(
        id=5,
        workspace_id=99,
        folder_id=15,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h",
        scope=AssetScopeEnum.PRIVATE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
    )
    service.mock_source_asset_repo.get_by_id.return_value = asset

    result = await service.bulk_move(bulk_dto, current_user)
    assert result["moved_count"] == 1
    service.mock_tags_repo.clear_tags_for_source_asset.assert_called_once_with(
        5
    )
    service.mock_source_asset_repo.update.assert_not_called()
    assert service.mock_db.execute.call_count == 1
    assert service.mock_db.flush.call_count == 1
    service.mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_bulk_move_source_asset_same_workspace(service):
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
        SourceAssetModel,
    )

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=5, type="source_asset")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    asset = SourceAssetModel(
        id=5,
        workspace_id=88,
        folder_id=15,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h",
        scope=AssetScopeEnum.PRIVATE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
    )
    service.mock_source_asset_repo.get_by_id.return_value = asset

    result = await service.bulk_move(bulk_dto, current_user)
    assert result["moved_count"] == 1
    service.mock_tags_repo.clear_tags_for_source_asset.assert_not_called()
    service.mock_source_asset_repo.update.assert_not_called()
    assert service.mock_db.execute.call_count == 1
    assert service.mock_db.flush.call_count == 1
    service.mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_bulk_move_folder_success(service):
    from src.folders.schema.folder_model import Folder
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=10, type="folder")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = Folder(
        id=10,
        workspace_id=99,
        user_id=1,
        user_email="user@test.com",
        name="Campaigns",
    )
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.subtree_has_foreign_content.return_value = False
    service.mock_folder_repo.get_existing_folders_map.return_value = {}
    service.mock_folder_repo.move_folder_to_workspace.return_value = {
        "folders_moved": 2,
        "media_moved": 3,
        "assets_moved": 1,
    }

    result = await service.bulk_move(bulk_dto, current_user)
    assert result["moved_count"] == 6
    service.mock_workspace_auth.authorize_write.assert_any_call(
        workspace_id=88, user=current_user
    )
    service.mock_workspace_auth.authorize_write.assert_any_call(
        workspace_id=99, user=current_user
    )
    service.mock_folder_repo.move_folder_to_workspace.assert_called_once_with(
        folder_id=10,
        target_workspace_id=88,
        user_id=1,
        conflict_strategy=ConflictStrategyEnum.KEEP_BOTH,
        commit=False,
    )


@pytest.mark.anyio
async def test_bulk_move_folder_same_workspace(service):
    from src.folders.schema.folder_model import Folder
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=10, type="folder")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = Folder(
        id=10,
        workspace_id=88,
        user_id=1,
        user_email="user@test.com",
        name="Campaigns",
    )
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.subtree_has_foreign_content.return_value = False

    result = await service.bulk_move(bulk_dto, current_user)
    assert result["moved_count"] == 0
    service.mock_folder_repo.move_folder_to_workspace.assert_not_called()


@pytest.mark.anyio
async def test_bulk_move_folder_conflict_detection_409(service):
    from src.folders.schema.folder_model import Folder
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=10, type="folder")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = Folder(
        id=10,
        workspace_id=99,
        user_id=1,
        user_email="user@test.com",
        name="Campaigns",
    )
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.subtree_has_foreign_content.return_value = False
    service.mock_folder_repo.get_existing_folders_map.return_value = {
        "campaigns": Folder(
            id=999,
            workspace_id=88,
            user_id=1,
            user_email="user@test.com",
            name="Campaigns",
        )
    }

    with pytest.raises(HTTPException) as exc_info:
        await service.bulk_move(bulk_dto, current_user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "FOLDER_COLLISION"
    assert len(exc_info.value.detail["conflicts"]) == 1
    assert exc_info.value.detail["conflicts"][0]["folder_name"] == "Campaigns"
    service.mock_folder_repo.move_folder_to_workspace.assert_not_called()


@pytest.mark.anyio
async def test_bulk_move_folder_merge_strategy(service):
    from src.folders.schema.folder_model import Folder
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=10, type="folder")],
        conflict_strategy=ConflictStrategyEnum.MERGE,
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = Folder(
        id=10,
        workspace_id=99,
        user_id=1,
        user_email="user@test.com",
        name="Campaigns",
    )
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.subtree_has_foreign_content.return_value = False
    service.mock_folder_repo.move_folder_to_workspace.return_value = {
        "folders_moved": 1,
        "media_moved": 2,
        "assets_moved": 0,
    }

    result = await service.bulk_move(bulk_dto, current_user)
    assert result["moved_count"] == 3
    service.mock_folder_repo.move_folder_to_workspace.assert_called_once_with(
        folder_id=10,
        target_workspace_id=88,
        user_id=1,
        conflict_strategy=ConflictStrategyEnum.MERGE,
        commit=False,
    )


@pytest.mark.anyio
async def test_bulk_move_partial_failure_with_savepoint(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[
            BulkMoveItemDto(id=1, type="media_item"),
            BulkMoveItemDto(id=2, type="media_item"),
        ],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    media_1 = DummyMedia(
        id=1,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    media_2 = DummyMedia(
        id=2,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.side_effect = [media_1, media_2]
    service.mock_db.execute.side_effect = [
        Exception("DB IntegrityError"),
        MagicMock(),
    ]

    result = await service.bulk_move(bulk_dto, current_user)

    assert result["moved_count"] == 1
    assert service.mock_db.begin_nested.call_count == 2
    assert service.mock_db.execute.call_count == 2
    assert service.mock_db.flush.call_count == 1
    service.mock_db.commit.assert_called_once()
    service.mock_media_repo.update.assert_not_called()


@pytest.mark.anyio
async def test_bulk_copy_folder_success(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto

    class DummyFolder(BaseModel):
        id: int
        workspace_id: int
        name: str

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[BulkCopyItemDto(id=10, type="folder")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = DummyFolder(id=10, workspace_id=99, name="Campaigns")
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.get_existing_folders_map.return_value = {}
    service.mock_folder_repo.copy_folder_to_workspace.return_value = {
        "folders_copied": 2,
        "media_copied": 3,
        "assets_copied": 1,
    }

    result = await service.bulk_copy(bulk_dto, current_user)
    assert result["copied_count"] == 6
    service.mock_workspace_auth.authorize_write.assert_any_call(
        workspace_id=88, user=current_user
    )
    service.mock_workspace_auth.authorize.assert_any_call(
        workspace_id=99, user=current_user
    )
    service.mock_folder_repo.copy_folder_to_workspace.assert_called_once_with(
        folder_id=10,
        target_workspace_id=88,
        user_id=1,
        user_email="user@test.com",
        conflict_strategy=ConflictStrategyEnum.KEEP_BOTH,
        commit=False,
    )


@pytest.mark.anyio
async def test_bulk_copy_folder_conflict_detection_409(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto

    class DummyFolder(BaseModel):
        id: int
        workspace_id: int
        name: str

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[BulkCopyItemDto(id=10, type="folder")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = DummyFolder(id=10, workspace_id=99, name="Campaigns")
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.get_existing_folders_map.return_value = {
        "campaigns": DummyFolder(id=999, workspace_id=88, name="Campaigns")
    }

    with pytest.raises(HTTPException) as exc_info:
        await service.bulk_copy(bulk_dto, current_user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "FOLDER_COLLISION"
    assert len(exc_info.value.detail["conflicts"]) == 1
    assert exc_info.value.detail["conflicts"][0]["folder_name"] == "Campaigns"
    service.mock_folder_repo.copy_folder_to_workspace.assert_not_called()


@pytest.mark.anyio
async def test_bulk_copy_folder_merge_strategy(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto

    class DummyFolder(BaseModel):
        id: int
        workspace_id: int
        name: str

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[BulkCopyItemDto(id=10, type="folder")],
        conflict_strategy=ConflictStrategyEnum.MERGE,
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    folder = DummyFolder(id=10, workspace_id=99, name="Campaigns")
    service.mock_folder_repo.get_folders_by_ids.return_value = [folder]
    service.mock_folder_repo.copy_folder_to_workspace.return_value = {
        "folders_copied": 1,
        "media_copied": 2,
        "assets_copied": 0,
    }

    result = await service.bulk_copy(bulk_dto, current_user)
    assert result["copied_count"] == 3
    service.mock_folder_repo.copy_folder_to_workspace.assert_called_once_with(
        folder_id=10,
        target_workspace_id=88,
        user_id=1,
        user_email="user@test.com",
        conflict_strategy=ConflictStrategyEnum.MERGE,
        commit=False,
    )


@pytest.mark.anyio
async def test_bulk_copy_partial_failure_with_savepoint(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto

    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[
            BulkCopyItemDto(id=1, type="media_item"),
            BulkCopyItemDto(id=2, type="media_item"),
        ],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    media_1 = DummyMedia(
        id=1,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    media_2 = DummyMedia(
        id=2,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.side_effect = [media_1, media_2]
    service.mock_media_repo.create.side_effect = [
        Exception("DB IntegrityError"),
        MagicMock(id=200),
    ]

    result = await service.bulk_copy(bulk_dto, current_user)

    assert result["copied_count"] == 1
    assert service.mock_db.begin_nested.call_count == 2
    service.mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_bulk_copy_reraises_http_exception(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto

    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkCopyDto(
        target_workspace_id=88,
        items=[BulkCopyItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    media_1 = DummyMedia(
        id=1,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.return_value = media_1

    async def fake_authorize(workspace_id, user):
        if workspace_id == 99:
            raise HTTPException(status_code=403, detail="Forbidden")
        return WorkspaceModel(
            id=workspace_id,
            name="Target WS",
            owner_id=user.id,
            scope=WorkspaceScopeEnum.PRIVATE,
        )

    service.mock_workspace_auth.authorize.side_effect = fake_authorize

    with pytest.raises(HTTPException) as exc_info:
        await service.bulk_copy(bulk_dto, current_user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Forbidden"


@pytest.mark.anyio
async def test_bulk_move_reraises_http_exception(service):
    from pydantic import BaseModel
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    class DummyMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=1, type="media_item")],
    )
    current_user = UserModel(
        id=1,
        email="user@test.com",
        name="User",
        roles=[UserRoleEnum.USER],
    )

    media_1 = DummyMedia(
        id=1,
        workspace_id=99,
        folder_id=12,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )
    service.mock_media_repo.get_by_id.return_value = media_1

    async def fake_authorize(workspace_id, user):
        if workspace_id == 99:
            raise HTTPException(status_code=403, detail="Forbidden")
        return WorkspaceModel(
            id=workspace_id,
            name="Target WS",
            owner_id=user.id,
            scope=WorkspaceScopeEnum.PRIVATE,
        )

    service.mock_workspace_auth.authorize_write.side_effect = fake_authorize

    with pytest.raises(HTTPException) as exc_info:
        await service.bulk_move(bulk_dto, current_user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Forbidden"


@pytest.mark.anyio
async def test_sign_uri_delegates_to_async_signer(service):
    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://async-signed.url/img.webp"
    )

    result = await service._sign_uri("gs://bucket/img.webp")

    assert result == "https://async-signed.url/img.webp"
    service.mock_iam_signer.generate_presigned_url_async.assert_awaited_once_with(
        "gs://bucket/img.webp"
    )


@pytest.mark.anyio
async def test_bulk_copy_sanitizes_cross_workspace_references_and_clears_lineage(
    service,
):
    from src.galleries.dto.bulk_copy_dto import BulkCopyDto, BulkCopyItemDto
    from src.common.schema.media_item_model import SourceMediaItemLink

    current_user = UserModel(
        id=1, email="user@test.com", name="User", roles=[UserRoleEnum.USER]
    )
    src_item = MediaItemModel(
        id=50,
        workspace_id=10,
        user_id=1,
        user_email="user@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_FAST,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://b/out.png"],
        revision_root_id=40,
        revision_parent_id=49,
        revision_number=3,
        source_assets=[
            SourceAssetLink(asset_id=1, role=AssetRoleEnum.INPUT),
            SourceAssetLink(asset_id=2, role=AssetRoleEnum.STYLE_REFERENCE),
        ],
        source_media_items=[
            SourceMediaItemLink(
                media_item_id=3, media_index=0, role=AssetRoleEnum.INPUT
            ),
            SourceMediaItemLink(
                media_item_id=4, media_index=0, role=AssetRoleEnum.INPUT
            ),
        ],
    )
    service.mock_media_repo.get_by_id.return_value = src_item
    mock_allowed_assets = MagicMock()
    mock_allowed_assets.fetchall.return_value = [(2,)]
    mock_allowed_media = MagicMock()
    mock_allowed_media.fetchall.return_value = [(4,)]
    service.mock_db.execute.side_effect = [
        mock_allowed_assets,
        mock_allowed_media,
    ]
    service.mock_media_repo.create.return_value = MediaItemModel(
        id=200,
        workspace_id=88,
        user_id=1,
        user_email="user@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_FAST,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://b/out.png"],
    )

    res = await service.bulk_copy(
        BulkCopyDto(
            target_workspace_id=88,
            items=[BulkCopyItemDto(id=50, type="media_item")],
        ),
        current_user,
    )

    assert res["copied_count"] == 1
    created_kwargs = service.mock_media_repo.create.call_args.args[0]
    assert created_kwargs["revision_number"] == 1
    assert "revision_root_id" not in created_kwargs
    assert "revision_parent_id" not in created_kwargs
    assert [a["asset_id"] for a in created_kwargs["source_assets"]] == [2]
    assert [
        m["media_item_id"] for m in created_kwargs["source_media_items"]
    ] == [4]


@pytest.mark.anyio
async def test_bulk_move_out_of_personal_workspace_rejected_400(service):
    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    user = UserModel(
        id=1, email="u@test.com", name="U", roles=[UserRoleEnum.USER]
    )
    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=1,
        scope=WorkspaceScopeEnum.PERSONAL,
    )
    target_ws = WorkspaceModel(
        id=88, name="Shared", owner_id=1, scope=WorkspaceScopeEnum.PRIVATE
    )
    service.mock_workspace_auth.authorize_write.side_effect = (
        lambda workspace_id, user: (
            personal_ws if workspace_id == 10 else target_ws
        )
    )
    service.mock_media_repo.get_by_id.return_value = MediaItemModel(
        id=5,
        workspace_id=10,
        user_id=1,
        user_email="u@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_FAST,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://b/m5.png"],
    )

    with pytest.raises(HTTPException) as exc:
        await service.bulk_move(
            BulkMoveDto(
                target_workspace_id=88,
                items=[BulkMoveItemDto(id=5, type="media_item")],
            ),
            user,
        )
    assert exc.value.status_code == 400
    assert "cannot be moved directly to another workspace" in exc.value.detail


@pytest.mark.anyio
async def test_restore_item_global_admin_blocked_from_foreign_personal_workspace(
    service,
):
    admin = UserModel(
        id=1, email="admin@test.com", name="A", roles=[UserRoleEnum.ADMIN]
    )
    service.mock_media_repo.get_by_id.return_value = MediaItemModel(
        id=77,
        workspace_id=10,
        user_id=1,
        user_email="other@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_FAST,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://b/m77.png"],
    )
    service.mock_workspace_auth.authorize_write.side_effect = HTTPException(
        status_code=403, detail="Forbidden"
    )

    with pytest.raises(HTTPException) as exc:
        await service.restore_item(77, "media_item", admin)
    assert exc.value.status_code == 403
    service.mock_media_repo.restore.assert_not_awaited()


@pytest.mark.anyio
async def test_enrich_source_links_skip_inaccessible_foreign_workspace(service):
    from src.common.schema.media_item_model import SourceMediaItemLink
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
        SourceAssetModel,
    )

    caller = UserModel(
        id=2, email="colleague@test.com", name="C", roles=[UserRoleEnum.USER]
    )
    service.mock_workspace_auth.authorize.side_effect = HTTPException(
        status_code=403, detail="Forbidden"
    )

    foreign_asset = SourceAssetModel(
        id=11,
        workspace_id=10,
        user_id=1,
        gcs_uri="gs://b/private.png",
        original_filename="private.png",
        file_hash="h1",
        scope=AssetScopeEnum.PRIVATE,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    system_asset = SourceAssetModel(
        id=12,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b/sys.png",
        original_filename="sys.png",
        file_hash="h2",
        scope=AssetScopeEnum.SYSTEM,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    foreign_media = MediaItemModel(
        id=21,
        workspace_id=10,
        user_email="owner@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://b/private_gen.png"],
    )

    service.mock_source_asset_repo.get_by_id.return_value = foreign_asset
    blocked_asset = await service._enrich_source_asset_link(
        SourceAssetLink(asset_id=11, role=AssetRoleEnum.INPUT),
        item_workspace_id=99,
        current_user=caller,
    )
    assert blocked_asset is None
    service.mock_iam_signer.generate_presigned_url_async.assert_not_awaited()

    service.mock_media_repo.get_by_id.return_value = foreign_media
    blocked_media = await service._enrich_source_media_item_link(
        SourceMediaItemLink(
            media_item_id=21, media_index=0, role=AssetRoleEnum.INPUT
        ),
        item_workspace_id=99,
        current_user=caller,
    )
    assert blocked_media is None
    service.mock_iam_signer.generate_presigned_url_async.assert_not_awaited()

    service.mock_source_asset_repo.get_by_id.return_value = system_asset
    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://signed/sys.png"
    )
    allowed_system = await service._enrich_source_asset_link(
        SourceAssetLink(asset_id=12, role=AssetRoleEnum.INPUT),
        item_workspace_id=99,
        current_user=caller,
    )
    assert allowed_system is not None
    assert allowed_system.presigned_url == "https://signed/sys.png"


@pytest.mark.anyio
async def test_hydrate_media_items_batches_tags_and_user_pictures(service):
    from src.tags.schema.tags_model import Tag

    caller = UserModel(
        id=1, email="user@test.com", name="User", roles=[UserRoleEnum.USER]
    )
    service.mock_iam_signer.generate_presigned_url_async.return_value = (
        "https://signed"
    )
    items = [
        MediaItemModel(
            id=11,
            workspace_id=10,
            user_id=1,
            user_email="a@test.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.IMAGEN_3_001,
            aspect_ratio="1:1",
            gcs_uris=["gs://bucket/img-1.png"],
        ),
        MediaItemModel(
            id=12,
            workspace_id=10,
            user_id=2,
            user_email="b@test.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.IMAGEN_3_001,
            aspect_ratio="1:1",
            gcs_uris=["gs://bucket/img-2.png"],
        ),
    ]
    tag_res = MagicMock()
    now_dt = datetime.now()
    tag_res.all.return_value = [
        (
            11,
            Tag(
                id=5,
                workspace_id=10,
                name="hero",
                color="#112233",
                created_at=now_dt,
                updated_at=now_dt,
            ),
        )
    ]
    user_res = MagicMock()
    user_res.all.return_value = [(1, "https://pic/1"), (2, "https://pic/2")]
    service.mock_db.execute.side_effect = [tag_res, user_res]

    assert await service.hydrate_media_items([], caller) == []
    hydrated = await service.hydrate_media_items(items, caller)

    assert len(hydrated) == 2
    assert service.mock_db.execute.await_count == 2
    assert [t.name for t in hydrated[0].tags] == ["hero"]
    assert hydrated[1].tags == []
    assert hydrated[0].user_picture == "https://pic/1"
    assert hydrated[1].user_picture == "https://pic/2"


@pytest.mark.anyio
async def test_authorize_move_source_forbidden_for_foreign_folder(service):
    from src.folders.schema.folder_model import Folder
    from src.workspaces.schema.workspace_model import (
        WorkspaceModel,
        WorkspaceRoleEnum,
        WorkspaceScopeEnum,
    )

    caller = UserModel(
        id=2, email="colleague@test.com", name="C", roles=[UserRoleEnum.USER]
    )
    service.mock_workspace_auth.authorize_write.return_value = WorkspaceModel(
        id=10,
        name="Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    foreign_folder = Folder(
        id=55, workspace_id=10, user_id=1, user_email="owner@test.com", name="F"
    )
    with pytest.raises(HTTPException) as exc:
        await service._authorize_move_source(
            10, 10, foreign_folder, "folder", caller
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_bulk_move_same_workspace_colocates_stack_to_root(service):
    from pydantic import BaseModel

    from src.galleries.dto.bulk_move_dto import BulkMoveDto, BulkMoveItemDto

    class DummyStackMedia(BaseModel):
        id: int
        workspace_id: int
        folder_id: int | None = None
        revision_root_id: int | None = None
        user_id: int
        user_email: str
        gcs_uris: list

    bulk_dto = BulkMoveDto(
        target_workspace_id=88,
        items=[BulkMoveItemDto(id=202, type="media_item")],
    )
    current_user = UserModel(
        id=1, email="user@test.com", name="User", roles=[UserRoleEnum.USER]
    )
    service.mock_media_repo.get_by_id.return_value = DummyStackMedia(
        id=202,
        workspace_id=88,
        folder_id=12,
        revision_root_id=101,
        user_id=1,
        user_email="user@test.com",
        gcs_uris=[],
    )

    result = await service.bulk_move(bulk_dto, current_user)

    assert result["moved_count"] == 1
    executed_stmt = service.mock_db.execute.call_args[0][0]
    stmt_text = str(executed_stmt)
    assert "revision_root_id" in stmt_text
    assert "deleted_at IS NULL" in stmt_text
    service.mock_tags_repo.clear_tags_for_media_item.assert_not_called()
