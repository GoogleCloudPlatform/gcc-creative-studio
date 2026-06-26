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


from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

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
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.unified_gallery_response import (
    UnifiedGalleryItemResponse,
)
from src.galleries.gallery_service import GalleryService
from src.users.user_model import UserModel, UserRoleEnum


@pytest.fixture(name="service")
def fixture_service():
    mock_media_repo = AsyncMock()
    mock_source_asset_repo = AsyncMock()
    mock_unified_gallery_repo = AsyncMock()
    mock_user_repo = AsyncMock()
    mock_workspace_repo = AsyncMock()
    mock_iam_signer = MagicMock()
    mock_workspace_auth = AsyncMock()
    mock_imagen_service = AsyncMock()
    mock_gcs_service = MagicMock()
    mock_tags_repo = AsyncMock()

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

    return service


@pytest.mark.anyio
async def test_enrich_source_asset_link(service):
    # Setup link
    link = SourceAssetLink(asset_id=123, role=AssetRoleEnum.INPUT)

    # Mock source_asset_repo.get_by_id
    mock_asset = MagicMock()
    mock_asset.gcs_uri = "gs://bucket/asset.jpg"
    mock_asset.thumbnail_gcs_uri = "gs://bucket/thumb.jpg"
    mock_asset.mime_type = "image/jpeg"
    service.mock_source_asset_repo.get_by_id.return_value = mock_asset

    # Mock iam_signer_credentials
    service.mock_iam_signer.generate_presigned_url.side_effect = [
        "https://signed.url/asset.jpg",
        "https://signed.url/thumb.jpg",
    ]

    result = await service._enrich_source_asset_link(link)

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
    service.mock_iam_signer.generate_presigned_url.return_value = (
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

    service.mock_iam_signer.generate_presigned_url.return_value = (
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
    service.mock_iam_signer.generate_presigned_url.return_value = (
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

    source_asset = MagicMock()
    source_asset.gcs_uri = "gs://bucket/asset.jpg"
    source_asset.thumbnail_gcs_uri = "gs://bucket/thumb.jpg"
    source_asset.mime_type = "image/jpeg"

    def get_by_id_side_effect(id, **kwargs):
        if id == 123:
            return item
        if id == 456:
            return parent_sourced
        return None

    service.mock_media_repo.get_by_id.side_effect = get_by_id_side_effect
    service.mock_source_asset_repo.get_by_id.return_value = source_asset

    service.mock_workspace_repo.get_by_id.return_value = MagicMock()
    service.mock_iam_signer.generate_presigned_url.return_value = (
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
