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
"""Tests for UnifiedGalleryRepository using mocks."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.base_dto import GenerationModelEnum, MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.repository.unified_gallery_repository import (
    UnifiedGalleryRepository,
)


class MockItem:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture(name="mock_db")
def fixture_mock_db():
    return AsyncMock()


@pytest.mark.anyio
async def test_query_various_filters(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    # Mock the count and data results
    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 5

    mock_data_result = MagicMock()
    # Use real object instead of mock to satisfy Pydantic validation
    mock_item = MockItem(
        id=1,
        workspace_id=10,
        user_id=1,
        created_at=datetime.datetime.now(),
        item_type="media_item",
        status="completed",
        gcs_uris=["gs://b/1"],
        thumbnail_uris=[],
        deleted_at=None,
        metadata_={"mime_type": "image/png"},
    )

    mock_data_result.scalars.return_value.all.return_value = [mock_item]

    mock_db.execute.side_effect = [mock_count_result, mock_data_result]

    # 1. Test query with many filters to hit all branches
    search_dto = GallerySearchDto(
        workspace_id=10,
        status=JobStatusEnum.COMPLETED,
        user_email="test@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        start_date=datetime.date(2025, 1, 1),
        end_date=datetime.date(2025, 1, 31),
        query="sunset",
        limit=10,
        offset=0,
    )
    # Give it an item_type if it supports it
    search_dto.item_type = "media_item"

    res = await repo.query(search_dto, user_id=1)

    assert res.count == 5
    assert len(res.data) == 1
    assert mock_db.execute.call_count == 2


@pytest.mark.anyio
async def test_query_mime_type_wildcard(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 2
    mock_data_result = MagicMock()
    mock_data_result.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [mock_count_result, mock_data_result]

    search_dto = GallerySearchDto(
        mime_type="image/*",
        limit=10,
        offset=0,
    )

    await repo.query(search_dto)
    assert mock_db.execute.call_count == 2


@pytest.mark.anyio
async def test_query_tags_and_deleted(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1
    mock_data_result = MagicMock()
    mock_item = MockItem(
        id=2,
        workspace_id=10,
        user_id=1,
        created_at=datetime.datetime.now(),
        item_type="source_asset",
        status="completed",
        gcs_uris=["gs://b/2"],
        thumbnail_uris=[],
        deleted_at=datetime.datetime.now(),
        metadata_={
            "mime_type": "image/png",
            "tags": [{"name": "tag1", "workspace_id": 10}],
        },
    )
    mock_data_result.scalars.return_value.all.return_value = [mock_item]
    mock_db.execute.side_effect = [mock_count_result, mock_data_result]

    search_dto = GallerySearchDto(
        workspace_id=10,
        include_deleted=True,
        tags=["tag1"],
        limit=10,
        offset=0,
    )

    res = await repo.query(search_dto)
    assert res.count == 1
    assert len(res.data) == 1
    assert mock_db.execute.call_count == 2


@pytest.mark.anyio
async def test_query_include_external(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1
    mock_data_result = MagicMock()
    mock_item = MockItem(
        id=3,
        workspace_id=10,
        user_id=1,
        created_at=datetime.datetime.now(),
        item_type="source_asset",
        status="completed",
        gcs_uris=[],
        thumbnail_uris=[],
        deleted_at=None,
        metadata_={
            "mime_type": "video/mp4",
            "external_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    mock_data_result.scalars.return_value.all.return_value = [mock_item]
    mock_db.execute.side_effect = [mock_count_result, mock_data_result]

    search_dto = GallerySearchDto(
        workspace_id=10,
        include_external=True,
        limit=10,
        offset=0,
    )

    res = await repo.query(search_dto)
    assert res.count == 1
    assert len(res.data) == 1
    assert mock_db.execute.call_count == 2


@pytest.mark.anyio
async def test_list_folder_loop_items_is_scoped_and_ordered(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 250
    rows_result = MagicMock()
    rows_result.__iter__.return_value = iter(
        [("media_item", 3), ("source_asset", 4)]
    )
    mock_db.execute.side_effect = [count_result, rows_result]

    rows, total = await repo.list_folder_loop_items(
        workspace_id=10, folder_id=5, mime_type_prefix="video", limit=100
    )

    assert (rows, total) == ([("media_item", 3), ("source_asset", 4)], 250)
    sqls = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in mock_db.execute.await_args_list
    ]
    for sql in sqls:
        assert "workspace_id = 10" in sql
        assert "folder_id = 5" in sql
        assert "'media_item'" in sql and "'completed'" in sql
        assert "'source_asset'" in sql
        assert "deleted_at IS NULL" in sql
        assert "'video/%'" in sql
        assert "external_url" in sql
    assert "created_at ASC" in sqls[1]
    assert "LIMIT 100" in sqls[1]


def _compiled_sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.anyio
async def test_filter_linked_loop_items_is_one_scoped_query(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)
    result = MagicMock()
    result.__iter__.return_value = iter(
        [("media_item", 3), ("source_asset", 4)]
    )
    mock_db.execute.return_value = result

    found = await repo.filter_linked_loop_items(
        workspace_id=10,
        media_item_ids=[3, 9, 3],
        source_asset_ids=[4],
        mime_type_prefix="audio",
    )

    assert found == {("media_item", 3), ("source_asset", 4)}
    mock_db.execute.assert_awaited_once()
    sql = _compiled_sql(mock_db.execute.await_args.args[0])
    assert "workspace_id = 10" in sql
    assert "deleted_at IS NULL" in sql
    assert "'audio/%'" in sql
    assert "external_url" in sql
    assert "'completed'" in sql
    assert "IN (3, 9)" in sql
    assert "IN (4)" in sql
    assert "folder_id" not in sql


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("media_item_ids", "source_asset_ids", "expected_filter"),
    [
        (
            [5],
            [],
            "item_type = 'media_item' AND unified_gallery_view.id IN (5)",
        ),
        (
            [],
            [6],
            "item_type = 'source_asset' AND unified_gallery_view.id IN (6)",
        ),
    ],
    ids=["media-items-only", "source-assets-only"],
)
async def test_filter_linked_loop_items_filters_only_given_kinds(
    mock_db, media_item_ids, source_asset_ids, expected_filter
):
    repo = UnifiedGalleryRepository(db=mock_db)
    result = MagicMock()
    result.__iter__.return_value = iter([])
    mock_db.execute.return_value = result

    found = await repo.filter_linked_loop_items(
        workspace_id=10,
        media_item_ids=media_item_ids,
        source_asset_ids=source_asset_ids,
        mime_type_prefix="image",
    )

    assert found == set()
    sql = _compiled_sql(mock_db.execute.await_args.args[0])
    assert expected_filter in sql
    assert sql.count(" IN (") == 1


@pytest.mark.anyio
async def test_filter_linked_loop_items_without_ids_skips_query(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    found = await repo.filter_linked_loop_items(
        workspace_id=10,
        media_item_ids=[],
        source_asset_ids=[],
        mime_type_prefix="image",
    )

    assert found == set()
    mock_db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_query_two_stage_sql_structure_and_tiebreaker(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    count_res = MagicMock()
    count_res.scalar_one.return_value = 30
    data_res = MagicMock()
    data_res.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [count_res, data_res]

    await repo.query(GallerySearchDto(workspace_id=10, limit=12, offset=24))

    assert mock_db.execute.await_count == 2
    count_sql = _compiled_sql(mock_db.execute.await_args_list[0].args[0])
    data_sql = _compiled_sql(mock_db.execute.await_args_list[1].args[0])

    assert "FROM media_items" in count_sql
    assert "FROM source_assets" in count_sql
    assert "UNION ALL" in count_sql
    assert "unified_gallery_view" not in count_sql
    assert "WITH page_keys AS" in data_sql
    assert (
        "JOIN page_keys ON unified_gallery_view.id = page_keys.id" in data_sql
    )
    assert "unified_gallery_view.item_type = page_keys.item_type" in data_sql
    assert (
        "ORDER BY filtered_keys.created_at DESC, filtered_keys.id DESC, filtered_keys.item_type DESC"
        in data_sql
    )
    assert "LIMIT 12" in data_sql
    assert "OFFSET 24" in data_sql


@pytest.mark.anyio
async def test_query_branch_pruning_and_base_table_filters(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    # 1. Filtering by model or non-completed status prunes source_assets.
    c1, d1 = MagicMock(), MagicMock()
    c1.scalar_one.return_value = 1
    d1.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [c1, d1]

    await repo.query(
        GallerySearchDto(
            workspace_id=10,
            status=JobStatusEnum.PROCESSING,
            query="sunset",
            tags=["hero"],
            user_email="creator@example.com",
            limit=10,
            offset=0,
        )
    )
    sql1 = _compiled_sql(mock_db.execute.await_args_list[0].args[0])
    assert "FROM media_items" in sql1
    assert "source_assets" not in sql1
    assert "media_items.comment" in sql1
    assert "media_items.prompt" in sql1
    assert "JOIN users ON media_items.user_id = users.id" in sql1
    assert "media_item_tags JOIN tags" in sql1

    # 2. Filtering by item_type='source_asset' prunes media_items.
    mock_db.reset_mock()
    c2, d2 = MagicMock(), MagicMock()
    c2.scalar_one.return_value = 1
    d2.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [c2, d2]
    await repo.query(
        GallerySearchDto(
            workspace_id=10,
            item_type="source_asset",
            query="logo.png",
            tags=["brand"],
            limit=10,
            offset=0,
        )
    )
    sql2 = _compiled_sql(mock_db.execute.await_args_list[0].args[0])
    assert "FROM source_assets" in sql2
    assert "media_items" not in sql2
    assert "source_assets.original_filename" in sql2
    assert "source_asset_tags JOIN tags" in sql2

    # 3. Contradictory filters prune both branches cleanly with zero queries.
    mock_db.reset_mock()
    empty = await repo.query(
        GallerySearchDto(
            workspace_id=10,
            item_type="source_asset",
            model=GenerationModelEnum.IMAGEN_3_001,
            limit=10,
            offset=0,
        )
    )
    assert empty.count == 0
    assert empty.data == []
    mock_db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_query_short_circuits_stage2_when_empty(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    zero_count = MagicMock()
    zero_count.scalar_one.return_value = 0
    mock_db.execute.return_value = zero_count

    res_empty = await repo.query(
        GallerySearchDto(workspace_id=10, limit=10, offset=0)
    )
    assert res_empty.count == 0
    assert res_empty.total_pages == 0
    assert res_empty.data == []
    assert mock_db.execute.await_count == 1

    mock_db.reset_mock()
    past_end = MagicMock()
    past_end.scalar_one.return_value = 5
    mock_db.execute.return_value = past_end

    res_oob = await repo.query(
        GallerySearchDto(workspace_id=10, limit=10, offset=10)
    )
    assert res_oob.count == 5
    assert res_oob.total_pages == 1
    assert res_oob.data == []
    assert mock_db.execute.await_count == 1


@pytest.mark.anyio
async def test_query_multi_tag_and_semantics_and_folder_scoping(mock_db):
    repo = UnifiedGalleryRepository(db=mock_db)

    c1, d1 = MagicMock(), MagicMock()
    c1.scalar_one.return_value = 2
    d1.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [c1, d1]

    await repo.query(
        GallerySearchDto(
            workspace_id=10,
            tags=["hero", "summer"],
            is_root=True,
            limit=10,
            offset=0,
        )
    )
    sql_root = _compiled_sql(mock_db.execute.await_args_list[0].args[0])
    assert sql_root.count("EXISTS (") == 4
    assert "'hero'" in sql_root and "'summer'" in sql_root
    assert "media_items.folder_id IS NULL" in sql_root
    assert "source_assets.folder_id IS NULL" in sql_root

    mock_db.reset_mock()
    c2, d2 = MagicMock(), MagicMock()
    c2.scalar_one.return_value = 2
    d2.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [c2, d2]

    await repo.query(
        GallerySearchDto(workspace_id=10, folder_id=7, limit=10, offset=0)
    )
    sql_folder = _compiled_sql(mock_db.execute.await_args_list[0].args[0])
    assert "media_items.folder_id = 7" in sql_folder
    assert "source_assets.folder_id = 7" in sql_folder
