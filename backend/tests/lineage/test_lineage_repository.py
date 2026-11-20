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
"""Unit tests for LineageRepository."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.lineage.lineage_builder import LineageEdgeSpec
from src.lineage.repository.lineage_repository import LineageRepository
from src.lineage.schema.item_lineage_model import (
    ItemLineage,
    LineageItemTypeEnum,
    LineageRoleEnum,
)


@pytest.mark.anyio
async def test_has_any_edges_for_child_true_and_false():
    db = AsyncMock()
    present_result = MagicMock()
    present_result.scalar_one_or_none.return_value = 99
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [present_result, empty_result]

    repo = LineageRepository(db=db)
    assert (
        await repo.has_any_edges_for_child(
            workspace_id=1,
            child_type=LineageItemTypeEnum.MEDIA_ITEM,
            child_id=50,
        )
        is True
    )
    assert (
        await repo.has_any_edges_for_child(
            workspace_id=1,
            child_type=LineageItemTypeEnum.MEDIA_ITEM,
            child_id=51,
        )
        is False
    )


@pytest.mark.anyio
async def test_replace_child_edges_inserts_non_self_loops_and_commits():
    db = AsyncMock()
    repo = LineageRepository(db=db)

    await repo.replace_child_edges(
        workspace_id=7,
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=20,
        edges=[
            LineageEdgeSpec(
                parent_type=LineageItemTypeEnum.MEDIA_ITEM,
                parent_id=20,  # self-loop -> filtered out
                parent_index=0,
                role=LineageRoleEnum.INPUT.value,
                is_primary_parent=True,
            ),
            LineageEdgeSpec(
                parent_type=LineageItemTypeEnum.SOURCE_ASSET,
                parent_id=5,
                parent_index=0,
                role=LineageRoleEnum.IMAGE_EDIT_SOURCE.value,
                is_primary_parent=True,
                action_summary="Add clouds",
            ),
        ],
    )
    # 1 delete + 1 bulk insert
    assert db.execute.await_count == 2
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_replace_child_edges_empty_only_deletes_and_commits():
    db = AsyncMock()
    repo = LineageRepository(db=db)

    await repo.replace_child_edges(
        workspace_id=7,
        child_type=LineageItemTypeEnum.MEDIA_ITEM,
        child_id=20,
        edges=[],
    )
    assert db.execute.await_count == 1
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_get_primary_ancestor_chain_maps_rows():
    db = AsyncMock()
    query_result = MagicMock()
    query_result.fetchall.return_value = [
        SimpleNamespace(
            id=1,
            child_type="media_item",
            child_id=10,
            child_index=None,
            parent_type="source_asset",
            parent_id=3,
            parent_index=0,
            role="image_edit_source",
            action_summary="Turn into oil painting",
            depth=2,
        ),
        SimpleNamespace(
            id=2,
            child_type="media_item",
            child_id=20,
            child_index=None,
            parent_type="media_item",
            parent_id=10,
            parent_index=1,
            role="start_frame",
            action_summary="Gentle breeze through trees",
            depth=1,
        ),
    ]
    db.execute.return_value = query_result

    repo = LineageRepository(db=db)
    rows = await repo.get_primary_ancestor_chain(
        workspace_id=1,
        item_type=LineageItemTypeEnum.MEDIA_ITEM,
        item_id=20,
    )
    assert len(rows) == 2
    assert rows[0].parent_type == "source_asset"
    assert rows[0].parent_id == 3
    assert rows[1].parent_index == 1
    assert rows[1].action_summary == "Gentle breeze through trees"


@pytest.mark.anyio
async def test_get_direct_derivative_edges_returns_scalars():
    db = AsyncMock()
    edge_obj = ItemLineage(
        id=9,
        workspace_id=1,
        child_type="media_item",
        child_id=77,
        parent_type="media_item",
        parent_id=10,
        parent_index=0,
        role="omni_edit_source",
        is_primary_parent=True,
        action_summary="Make it snow",
    )
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [edge_obj]
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars_mock
    db.execute.return_value = exec_result

    repo = LineageRepository(db=db)
    derivatives = await repo.get_direct_derivative_edges(
        workspace_id=1,
        parent_type=LineageItemTypeEnum.MEDIA_ITEM,
        parent_id=10,
    )
    assert derivatives == [edge_obj]
