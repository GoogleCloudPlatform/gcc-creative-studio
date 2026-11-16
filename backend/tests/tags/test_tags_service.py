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
"""Tests for Tags Service."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException

from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.tags.tags_service import TagsService
from src.tags.schema.tags_model import TagModel
from src.tags.dto.tags_dto import TagCreateDto, BulkAssignTagsDto


@pytest.fixture(name="mock_tags_repo")
def fixture_mock_tags_repo():
    """Provides a mocked TagsRepository."""
    return AsyncMock()


@pytest.fixture(name="tags_service")
def fixture_tags_service(mock_tags_repo):
    """Provides a TagsService with a mocked repository."""
    return TagsService(repo=mock_tags_repo)


class TestListTags:
    """Tests for TagsService.list_tags."""

    @pytest.mark.anyio
    async def test_list_tags_with_workspace(self, tags_service, mock_tags_repo):
        mock_tags_repo.get_by_workspace.return_value = [
            TagModel(id=1, name="tag1", workspace_id=1)
        ]

        result = await tags_service.list_tags(workspace_id=1)

        assert len(result) == 1
        assert result[0].name == "tag1"
        mock_tags_repo.get_by_workspace.assert_called_once_with(
            1, None, 10, 0, None
        )

    @pytest.mark.anyio
    async def test_list_tags_without_workspace(
        self, tags_service, mock_tags_repo
    ):
        mock_tags_repo.list_global_tags.return_value = PaginationResponseDto(
            count=1,
            page=1,
            page_size=10,
            total_pages=1,
            data=[TagModel(id=1, name="tag1", workspace_id=1)],
        )

        result = await tags_service.list_tags(requesting_user_id=7)

        assert len(result.data) == 1
        assert result.data[0].name == "tag1"
        mock_tags_repo.list_global_tags.assert_awaited_once_with(
            requesting_user_id=7,
            search=None,
            limit=10,
            offset=0,
            user_id=None,
        )


class TestCreateTag:
    """Tests for TagsService.create_tag."""

    @pytest.mark.anyio
    async def test_create_tag_success(self, tags_service, mock_tags_repo):
        mock_tags_repo.find_by_name.return_value = None
        mock_tags_repo.create.return_value = TagModel(
            id=1, name="new_tag", workspace_id=1
        )

        dto = TagCreateDto(name="new_tag", workspace_id=1)
        result = await tags_service.create_tag(dto, user_id=1)

        assert result.name == "new_tag"
        mock_tags_repo.find_by_name.assert_called_once_with("new_tag", 1)
        mock_tags_repo.create.assert_called_once()

    @pytest.mark.anyio
    async def test_create_tag_already_exists(
        self, tags_service, mock_tags_repo
    ):
        mock_tags_repo.find_by_name.return_value = TagModel(
            id=1, name="existing", workspace_id=1
        )

        dto = TagCreateDto(name="existing", workspace_id=1)
        with pytest.raises(HTTPException) as exc_info:
            await tags_service.create_tag(dto, user_id=1)

        assert exc_info.value.status_code == 400
        assert "already exists" in exc_info.value.detail


class TestDeleteTag:
    """Tests for TagsService.delete_tag."""

    @pytest.mark.anyio
    async def test_delete_tag(self, tags_service, mock_tags_repo):
        mock_tags_repo.delete.return_value = True

        result = await tags_service.delete_tag(id=1, user_id=1, is_admin=True)

        assert result is True
        mock_tags_repo.delete.assert_called_once_with(1)

    @pytest.mark.anyio
    async def test_update_and_delete_foreign_tag_manager_vs_editor(
        self, tags_service, mock_tags_repo
    ):
        from src.tags.dto.tags_dto import TagUpdateDto

        foreign_tag = TagModel(id=7, name="tag", workspace_id=10, user_id=999)
        mock_tags_repo.get_by_id.return_value = foreign_tag
        mock_tags_repo.update_tag.return_value = foreign_tag
        mock_tags_repo.delete.return_value = True

        # Non-creator manager (is_admin=True from is_workspace_manager) succeeds.
        assert (
            await tags_service.update_tag(
                7, TagUpdateDto(name="renamed"), user_id=1, is_admin=True
            )
            == foreign_tag
        )
        assert (
            await tags_service.delete_tag(7, user_id=1, is_admin=True) is True
        )

        # Non-creator non-manager (EDITOR) gets 403.
        with pytest.raises(HTTPException) as exc_upd:
            await tags_service.update_tag(
                7, TagUpdateDto(name="renamed"), user_id=1, is_admin=False
            )
        assert exc_upd.value.status_code == 403

        with pytest.raises(HTTPException) as exc_del:
            await tags_service.delete_tag(7, user_id=1, is_admin=False)
        assert exc_del.value.status_code == 403


class TestBulkAssign:
    """Tests for TagsService.bulk_assign."""

    @pytest.mark.anyio
    async def test_bulk_assign_media_item(self, tags_service, mock_tags_repo):
        dto = BulkAssignTagsDto(
            item_ids=[1, 2],
            tag_names=["tag10", "tag20"],
            item_type="media_item",
            workspace_id=1,
        )

        mock_tags_repo.get_item_workspaces.return_value = {1: 1, 2: 1}
        mock_tags_repo.find_by_name.side_effect = (
            lambda name, workspace_id: TagModel(
                id=10 if name == "tag10" else 20,
                name=name,
                workspace_id=workspace_id,
            )
        )

        result = await tags_service.bulk_assign(dto, user_id=1)

        assert result is True
        mock_tags_repo.get_item_workspaces.assert_awaited_once_with(
            [1, 2], "media_item"
        )
        mock_tags_repo.clear_tags_for_items.assert_called_once_with(
            [1, 2], "media_item"
        )
        mock_tags_repo.assign_tags_to_items.assert_called_once_with(
            [1, 2], [10, 20], "media_item"
        )

    @pytest.mark.anyio
    async def test_bulk_assign_source_asset(self, tags_service, mock_tags_repo):
        dto = BulkAssignTagsDto(
            item_ids=[1],
            tag_names=["tag10"],
            item_type="source_asset",
            workspace_id=1,
        )

        mock_tags_repo.get_item_workspaces.return_value = {1: 1}
        mock_tags_repo.find_by_name.return_value = TagModel(
            id=10, name="tag10", workspace_id=1
        )

        result = await tags_service.bulk_assign(dto, user_id=1)

        assert result is True
        mock_tags_repo.clear_tags_for_items.assert_called_once_with(
            [1], "source_asset"
        )
        mock_tags_repo.assign_tags_to_items.assert_called_once_with(
            [1], [10], "source_asset"
        )

    @pytest.mark.anyio
    async def test_bulk_assign_invalid_type(self, tags_service):
        dto = BulkAssignTagsDto(
            item_ids=[1],
            tag_names=["tag10"],
            item_type="invalid",
            workspace_id=1,
        )

        with pytest.raises(HTTPException) as exc_info:
            await tags_service.bulk_assign(dto, user_id=1)

        assert exc_info.value.status_code == 400
        assert "Invalid item_type" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_bulk_assign_rejects_missing_404_and_foreign_workspace_403(
        self, tags_service, mock_tags_repo
    ):
        mock_tags_repo.get_item_workspaces.return_value = {}
        with pytest.raises(HTTPException) as exc_404:
            await tags_service.bulk_assign(
                BulkAssignTagsDto(
                    item_ids=[99],
                    tag_names=["t"],
                    item_type="media_item",
                    workspace_id=1,
                ),
                user_id=1,
            )
        assert exc_404.value.status_code == 404

        mock_tags_repo.get_item_workspaces.return_value = {99: 2}
        with pytest.raises(HTTPException) as exc_403:
            await tags_service.bulk_assign(
                BulkAssignTagsDto(
                    item_ids=[99],
                    tag_names=["t"],
                    item_type="media_item",
                    workspace_id=1,
                ),
                user_id=1,
            )
        assert exc_403.value.status_code == 403
