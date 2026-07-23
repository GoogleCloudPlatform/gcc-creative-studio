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
"""Tests for Media Templates Service."""


from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schema.media_item_model import (
    AspectRatioEnum,
    MediaItemModel,
    MimeTypeEnum,
    SourceAssetLink,
)
from src.media_templates.dto.template_search_dto import TemplateSearchDto
from src.media_templates.dto.update_template_dto import UpdateTemplateDto
from src.media_templates.media_templates_service import MediaTemplateService
from src.media_templates.schema.media_template_model import (
    GenerationParameters,
    MediaTemplateModel,
)
from src.users.user_model import UserModel


@pytest.fixture(name="service")
def fixture_service():
    mock_template_repo = AsyncMock()
    mock_media_item_repo = AsyncMock()
    mock_source_asset_repo = AsyncMock()
    mock_gemini_service = AsyncMock()
    mock_gemini_service.generate_structured_prompt = MagicMock()
    mock_iam_signer = MagicMock()

    mock_gcs_service = MagicMock()
    mock_source_asset_service = AsyncMock()
    mock_workspace_repo = AsyncMock()

    service = MediaTemplateService(
        template_repo=mock_template_repo,
        media_item_repo=mock_media_item_repo,
        source_asset_repo=mock_source_asset_repo,
        gemini_service=mock_gemini_service,
        iam_signer_credentials=mock_iam_signer,
        gcs_service=mock_gcs_service,
        source_asset_service=mock_source_asset_service,
        workspace_repo=mock_workspace_repo,
    )

    # Attach mocks for ease of use in tests
    service.mock_template_repo = mock_template_repo
    service.mock_media_item_repo = mock_media_item_repo
    service.mock_source_asset_repo = mock_source_asset_repo
    service.mock_gemini_service = mock_gemini_service
    service.mock_iam_signer = mock_iam_signer
    service.mock_gcs_service = mock_gcs_service
    service.mock_source_asset_service = mock_source_asset_service
    service.mock_workspace_repo = mock_workspace_repo

    return service


@pytest.mark.anyio
async def test_enrich_source_asset_link(service):
    link = SourceAssetLink(asset_id=123, role="input")
    asset_doc = MagicMock(gcs_uri="gs://b/a.jpg")
    service.mock_source_asset_repo.get_by_id.return_value = asset_doc
    service.mock_iam_signer.generate_presigned_url.return_value = (
        "https://signed.url"
    )

    result = await service._enrich_source_asset_link(link)
    assert result is not None
    assert result.presigned_url == "https://signed.url"


@pytest.mark.anyio
async def test_get_template_by_id(service):
    template = MediaTemplateModel(
        name="Test",
        description="Desc",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        gcs_uris=["gs://b/a.png"],
        thumbnail_uris=[],
        generation_parameters=GenerationParameters(prompt="test"),
    )

    service.mock_template_repo.get_by_id.return_value = template

    result = await service.get_template_by_id(1)
    assert result == template


@pytest.mark.anyio
async def test_find_all_templates(service):
    search_dto = TemplateSearchDto()
    mock_query_result = MagicMock()
    mock_query_result.data = [
        MediaTemplateModel(
            name="Test",
            description="Desc",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            gcs_uris=["gs://b/a.png"],
            thumbnail_uris=[],
            generation_parameters=GenerationParameters(prompt="test"),
        ),
    ]

    mock_query_result.count = 1
    mock_query_result.page = 1
    mock_query_result.page_size = 10
    mock_query_result.total_pages = 1
    service.mock_template_repo.query.return_value = mock_query_result
    service.mock_iam_signer.generate_presigned_url.return_value = (
        "https://signed.url"
    )

    result = await service.find_all_templates(search_dto)
    assert result.count == 1
    assert len(result.data) == 1


@pytest.mark.anyio
async def test_delete_template(service):
    service.mock_template_repo.delete.return_value = True
    result = await service.delete_template(1)
    assert result is True


@pytest.mark.anyio
async def test_update_template(service):
    update_dto = UpdateTemplateDto(name="New Name")
    template = MediaTemplateModel(
        name="New Name",
        description="Desc",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        gcs_uris=["gs://b/a.png"],
        thumbnail_uris=[],
        generation_parameters=GenerationParameters(prompt="test"),
    )

    service.mock_template_repo.update.return_value = template

    result = await service.update_template(1, update_dto)
    assert result == template


@pytest.mark.anyio
async def test_create_template_from_media_item_success(service):
    current_user = UserModel(id=1, email="admin@test.com", name="Admin")
    from src.common.base_dto import GenerationModelEnum

    media_item = MediaItemModel(
        workspace_id=99,
        user_email="admin@test.com",
        model=GenerationModelEnum.IMAGEN_3_001,
        prompt="Generate a dog",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://b/dog.png"],
        original_prompt="original dog",
    )

    service.mock_media_item_repo.get_by_id.return_value = media_item

    service.mock_gemini_service.generate_structured_prompt.return_value = '{"name": "Catchy Dog", "description": "A dog", "industry": "Automotive", "brand": "BrandX", "tags": ["dog"]}'

    mock_workspace = MagicMock(id=88)
    service.mock_workspace_repo.get_public_workspace.return_value = (
        mock_workspace
    )

    result = await service.create_template_from_media_item(123, current_user)
    assert result is not None
    assert result.name == "Catchy Dog"
    service.mock_template_repo.create.assert_called_once()


@pytest.mark.anyio
async def test_create_template_from_media_item_no_item(service):
    current_user = UserModel(id=1, email="admin@test.com", name="Admin")
    service.mock_media_item_repo.get_by_id.return_value = None

    result = await service.create_template_from_media_item(123, current_user)
    assert result is None


@pytest.mark.anyio
async def test_create_template_from_media_item_with_source_assets(service):
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
    )

    current_user = UserModel(id=1, email="admin@test.com", name="Admin")
    from src.common.base_dto import GenerationModelEnum

    source_asset = MagicMock(
        gcs_uri="gs://bucket/asset1.png",
        original_filename="asset1.png",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
    )
    service.mock_source_asset_repo.get_by_id.return_value = source_asset

    blob_mock = MagicMock()
    blob_mock.download_as_bytes.return_value = b"fake_bytes"
    service.mock_gcs_service.bucket_name = "bucket"
    service.mock_gcs_service.bucket.blob.return_value = blob_mock

    mock_uploaded_asset = MagicMock(id=500)
    service.mock_source_asset_service.upload_asset.return_value = (
        mock_uploaded_asset
    )

    media_item = MediaItemModel(
        workspace_id=99,
        user_email="admin@test.com",
        model=GenerationModelEnum.IMAGEN_3_001,
        prompt="Generate dog with asset",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
        gcs_uris=["gs://bucket/dog.png"],
        source_assets=[SourceAssetLink(asset_id=10, role="input")],
    )
    service.mock_media_item_repo.get_by_id.return_value = media_item
    service.mock_gemini_service.generate_structured_prompt.return_value = (
        '{"name": "Dog with Asset", "description": "Desc"}'
    )

    mock_workspace = MagicMock(id=88)
    service.mock_workspace_repo.get_public_workspace.return_value = (
        mock_workspace
    )

    result = await service.create_template_from_media_item(123, current_user)
    assert result is not None
    service.mock_source_asset_service.upload_asset.assert_called_once_with(
        user=current_user,
        file_bytes=b"fake_bytes",
        filename="asset1.png",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        workspace_id=88,
        scope=AssetScopeEnum.SYSTEM,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        aspect_ratio=AspectRatioEnum.RATIO_1_1,
    )


@pytest.mark.anyio
async def test_create_template_from_media_item_with_source_media_items(
    service,
):
    from src.common.schema.media_item_model import SourceMediaItemLink
    from src.source_assets.schema.source_asset_model import (
        AssetScopeEnum,
        AssetTypeEnum,
    )

    current_user = UserModel(id=1, email="admin@test.com", name="Admin")
    from src.common.base_dto import GenerationModelEnum

    source_media_item = MagicMock(
        id=20,
        gcs_uris=["gs://bucket/media20.png"],
        mime_type=MimeTypeEnum.IMAGE_PNG,
        aspect_ratio=AspectRatioEnum.RATIO_16_9,
    )

    media_item = MediaItemModel(
        workspace_id=99,
        user_email="admin@test.com",
        model=GenerationModelEnum.IMAGEN_3_001,
        prompt="Generate dog with media item",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        aspect_ratio=AspectRatioEnum.RATIO_16_9,
        gcs_uris=["gs://bucket/dog.png"],
        source_media_items=[
            SourceMediaItemLink(media_item_id=20, media_index=0, role="input")
        ],
    )

    service.mock_media_item_repo.get_by_id.side_effect = lambda media_id: (
        media_item if media_id == 123 else source_media_item
    )

    blob_mock = MagicMock()
    blob_mock.download_as_bytes.return_value = b"media_bytes"
    service.mock_gcs_service.bucket_name = "bucket"
    service.mock_gcs_service.bucket.blob.return_value = blob_mock

    mock_uploaded_asset = MagicMock(id=600)
    service.mock_source_asset_service.upload_asset.return_value = (
        mock_uploaded_asset
    )

    service.mock_gemini_service.generate_structured_prompt.return_value = (
        '{"name": "Dog with Media", "description": "Desc"}'
    )

    mock_workspace = MagicMock(id=88)
    service.mock_workspace_repo.get_public_workspace.return_value = (
        mock_workspace
    )

    result = await service.create_template_from_media_item(123, current_user)
    assert result is not None
    service.mock_source_asset_service.upload_asset.assert_called_once_with(
        user=current_user,
        file_bytes=b"media_bytes",
        filename="20_0.png",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        workspace_id=88,
        scope=AssetScopeEnum.SYSTEM,
        asset_type=AssetTypeEnum.GENERIC_IMAGE,
        aspect_ratio=AspectRatioEnum.RATIO_16_9,
    )
