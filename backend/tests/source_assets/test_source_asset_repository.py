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
"""Tests for Source Asset Repository."""


import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.source_assets.dto.source_asset_search_dto import SourceAssetSearchDto
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
)


def get_dummy_source_asset(**kwargs):
    now = datetime.datetime.now(datetime.UTC)
    defaults = {
        "id": 1,
        "workspace_id": 1,
        "user_id": 1,
        "gcs_uri": "gs://bucket/asset.png",
        "original_filename": "asset.png",
        "mime_type": "image/png",
        "aspect_ratio": "1:1",
        "file_hash": "hash123",
        "scope": "private",
        "asset_type": "generic_image",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    defaults.update(kwargs)
    return SourceAsset(**defaults)


@pytest.mark.anyio
async def test_find_by_hash_success():
    mock_db = AsyncMock()
    mock_result = MagicMock()

    mock_asset = get_dummy_source_asset(id=1, file_hash="hash123")
    mock_result.scalar_one_or_none.return_value = mock_asset
    mock_db.execute.return_value = mock_result

    repo = SourceAssetRepository(db=mock_db)
    response = await repo.find_by_hash(
        user_id=1, file_hash="hash123", workspace_id=1
    )

    assert response is not None
    assert response.id == 1
    assert response.file_hash == "hash123"


@pytest.mark.anyio
async def test_find_by_hash_not_found():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    repo = SourceAssetRepository(db=mock_db)
    response = await repo.find_by_hash(
        user_id=1, file_hash="absent", workspace_id=1
    )

    assert response is None


@pytest.mark.anyio
async def test_query_success():
    mock_db = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1

    # Needs items returned
    mock_asset = get_dummy_source_asset(id=2)
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [mock_asset]

    mock_db.execute.side_effect = [mock_count_result, mock_result]

    repo = SourceAssetRepository(db=mock_db)
    search_dto = SourceAssetSearchDto(limit=10, offset=0, mime_type="image/*")

    response = await repo.query(search_dto=search_dto, target_user_id=1)

    assert response.count == 1
    assert len(response.data) == 1


@pytest.mark.anyio
async def test_find_by_scope_and_types_success():
    mock_db = AsyncMock()
    # Use valid AssetTypeEnum value
    mock_asset = get_dummy_source_asset(
        id=3, scope="system", asset_type="vto_product"
    )
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [mock_asset]
    mock_db.execute.return_value = mock_result

    repo = SourceAssetRepository(db=mock_db)
    response = await repo.find_by_scope_and_types(
        scope=AssetScopeEnum.SYSTEM,
        asset_types=[AssetTypeEnum.VTO_PRODUCT],
    )

    assert len(response) == 1
    assert response[0].id == 3


@pytest.mark.anyio
async def test_find_private_by_user_and_types_success():
    mock_db = AsyncMock()
    mock_asset = get_dummy_source_asset(
        id=4,
        scope="private",
        user_id=1,
        asset_type="vto_product",
    )
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [mock_asset]
    mock_db.execute.return_value = mock_result

    repo = SourceAssetRepository(db=mock_db)
    response = await repo.find_private_by_user_and_types(
        user_id=1,
        asset_types=[AssetTypeEnum.VTO_PRODUCT],
    )

    assert len(response) == 1


@pytest.mark.anyio
async def test_get_by_gcs_uri_success():
    mock_db = AsyncMock()
    mock_asset = get_dummy_source_asset(id=5, gcs_uri="gs://b/5.png")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_asset
    mock_db.execute.return_value = mock_result

    repo = SourceAssetRepository(db=mock_db)
    response = await repo.get_by_gcs_uri(gcs_uri="gs://b/5.png")

    assert response is not None


@pytest.mark.anyio
async def test_find_system_and_private_assets_by_types_success():
    mock_db = AsyncMock()
    mock_asset = get_dummy_source_asset(
        id=6, scope="system", asset_type="vto_product"
    )
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [mock_asset]
    mock_db.execute.return_value = mock_result

    repo = SourceAssetRepository(db=mock_db)
    response = await repo.find_system_and_private_assets_by_types(
        user_id=1,
        asset_types=[AssetTypeEnum.VTO_PRODUCT],
    )

    assert len(response) == 1
