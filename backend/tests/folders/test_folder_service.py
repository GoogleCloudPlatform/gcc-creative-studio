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

"""Tests for Folder Service."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException, status

from src.folders.dto.folder_dto import (
    FolderBreadcrumbDto,
    FolderCreateDto,
    FolderResponseDto,
    FolderTreeNodeDto,
    FolderUpdateDto,
    MoveItemsDto,
)
from src.folders.folder_service import FolderService
from src.folders.schema.folder_model import Folder
from src.users.user_model import UserModel, UserRoleEnum


@pytest.fixture(name="mock_folder_repo")
def fixture_mock_folder_repo():
    """Provides a mocked FolderRepository."""
    mock = AsyncMock()
    mock.db = AsyncMock()
    mock.is_folder_name_taken.return_value = False
    return mock


@pytest.fixture(name="folder_service")
def fixture_folder_service(mock_folder_repo):
    """Provides a FolderService instance."""
    return FolderService(folder_repo=mock_folder_repo)


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=10,
        email="test@example.com",
        roles=[UserRoleEnum.USER],
        name="Test User",
    )


class TestCreateFolder:
    """Tests for FolderService.create_folder."""

    @pytest.mark.anyio
    async def test_create_root_folder_success(
        self, folder_service, mock_folder_repo, sample_user
    ):
        dto = FolderCreateDto(
            name="My Folder",
            workspace_id=1,
            parent_id=None,
            color="#FF5500",
        )

        async def fake_refresh(f):
            f.id = 100

        mock_folder_repo.db.refresh.side_effect = fake_refresh

        result = await folder_service.create_folder(dto, sample_user)

        assert result.id == 100
        assert result.name == "My Folder"
        assert result.workspace_id == 1
        assert result.color == "#FF5500"
        mock_folder_repo.db.add.assert_called_once()
        mock_folder_repo.db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_create_subfolder_success(
        self, folder_service, mock_folder_repo, sample_user
    ):
        dto = FolderCreateDto(
            name="Subfolder",
            workspace_id=1,
            parent_id=5,
        )
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=5, workspace_id=1, user_email="a@b.com", name="Parent"
        )

        async def fake_refresh(f):
            f.id = 101

        mock_folder_repo.db.refresh.side_effect = fake_refresh

        result = await folder_service.create_folder(dto, sample_user)
        assert result.id == 101
        assert result.parent_id == 5

    @pytest.mark.anyio
    async def test_create_folder_duplicate_conflict(
        self, folder_service, mock_folder_repo, sample_user
    ):
        dto = FolderCreateDto(
            name="Existing Folder",
            workspace_id=1,
            parent_id=None,
        )
        mock_folder_repo.is_folder_name_taken.return_value = True

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.create_folder(dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_create_folder_empty_name_error(
        self, folder_service, sample_user
    ):
        dto = FolderCreateDto(
            name="   ",
            workspace_id=1,
            parent_id=None,
        )
        with pytest.raises(HTTPException) as exc_info:
            await folder_service.create_folder(dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.anyio
    async def test_create_subfolder_parent_not_found(
        self, folder_service, mock_folder_repo, sample_user
    ):
        dto = FolderCreateDto(
            name="Subfolder",
            workspace_id=1,
            parent_id=999,
        )
        mock_folder_repo.get_folder_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.create_folder(dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestGetFolder:
    """Tests for FolderService get operations."""

    @pytest.mark.anyio
    async def test_get_folders_list(self, folder_service, mock_folder_repo):
        mock_folder_repo.list_by_parent.return_value = [
            FolderResponseDto(
                id=1,
                workspace_id=1,
                user_email="a@b.com",
                name="F1",
                parent_id=None,
            )
        ]
        result = await folder_service.get_folders(
            workspace_id=1, parent_id=None
        )
        assert len(result) == 1
        assert result[0].name == "F1"

    @pytest.mark.anyio
    async def test_get_folder_by_id_found(
        self, folder_service, mock_folder_repo
    ):
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="a@b.com",
            name="F1",
            parent_id=None,
        )
        mock_folder_repo.list_by_parent.return_value = [
            FolderResponseDto(
                id=1,
                workspace_id=1,
                user_email="a@b.com",
                name="F1",
                parent_id=None,
                item_count=10,
            )
        ]

        result = await folder_service.get_folder_by_id(folder_id=1)
        assert result.id == 1
        assert result.item_count == 10

    @pytest.mark.anyio
    async def test_get_folder_by_id_not_found(
        self, folder_service, mock_folder_repo
    ):
        mock_folder_repo.get_folder_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.get_folder_by_id(folder_id=999)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.anyio
    async def test_get_folder_by_id_workspace_mismatch(
        self, folder_service, mock_folder_repo
    ):
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=1, workspace_id=2, user_email="a@b.com", name="Folder in WS2"
        )

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.get_folder_by_id(folder_id=1, workspace_id=1)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "not found in this workspace" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_get_breadcrumbs(self, folder_service, mock_folder_repo):
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=2, workspace_id=1, user_email="a@b.com", name="Sub"
        )
        mock_folder_repo.get_breadcrumbs.return_value = [
            FolderBreadcrumbDto(id=1, name="Root", parent_id=None),
            FolderBreadcrumbDto(id=2, name="Sub", parent_id=1),
        ]

        result = await folder_service.get_breadcrumbs(
            folder_id=2, workspace_id=1
        )
        assert len(result) == 2
        assert result[0].name == "Root"

    @pytest.mark.anyio
    async def test_get_breadcrumbs_not_found(
        self, folder_service, mock_folder_repo
    ):
        mock_folder_repo.get_folder_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.get_breadcrumbs(folder_id=999)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.anyio
    async def test_get_breadcrumbs_workspace_mismatch(
        self, folder_service, mock_folder_repo
    ):
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=2, workspace_id=2, user_email="a@b.com", name="Sub"
        )

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.get_breadcrumbs(folder_id=2, workspace_id=1)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "not found in this workspace" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_get_tree(self, folder_service, mock_folder_repo):
        mock_folder_repo.get_tree.return_value = [
            FolderTreeNodeDto(id=1, name="Root", parent_id=None, children=[])
        ]
        result = await folder_service.get_folder_tree(workspace_id=1)
        assert len(result) == 1
        assert result[0].name == "Root"


class TestUpdateFolder:
    """Tests for FolderService.update_folder."""

    @pytest.mark.anyio
    async def test_update_name_success(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Old Name"
        )
        mock_folder_repo.get_folder_by_id.return_value = folder
        mock_folder_repo.is_folder_name_taken.return_value = False
        mock_folder_repo.list_by_parent.return_value = [
            FolderResponseDto(
                id=1,
                workspace_id=1,
                user_email="a@b.com",
                name="New Name",
                parent_id=None,
            )
        ]

        dto = FolderUpdateDto(name="New Name")
        result = await folder_service.update_folder(1, dto, sample_user)
        assert folder.name == "New Name"
        assert result.name == "New Name"

    @pytest.mark.anyio
    async def test_update_name_conflict_error(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Old Name"
        )
        mock_folder_repo.get_folder_by_id.return_value = folder
        mock_folder_repo.is_folder_name_taken.return_value = True

        dto = FolderUpdateDto(name="Existing Name")
        with pytest.raises(HTTPException) as exc_info:
            await folder_service.update_folder(1, dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_update_name_empty_error(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Old Name"
        )
        mock_folder_repo.get_folder_by_id.return_value = folder

        dto = FolderUpdateDto(name="   ")
        with pytest.raises(HTTPException) as exc_info:
            await folder_service.update_folder(1, dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.anyio
    async def test_update_folder_move_auto_disambiguation(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(
            id=1,
            workspace_id=1,
            user_email="a@b.com",
            name="Colliding",
            parent_id=None,
        )
        target_parent = Folder(
            id=5,
            workspace_id=1,
            user_email="a@b.com",
            name="TargetParent",
            parent_id=None,
        )
        mock_folder_repo.get_folder_by_id.side_effect = lambda fid: (
            folder if fid == 1 else target_parent
        )
        mock_folder_repo.get_descendant_ids.return_value = []
        mock_folder_repo.get_unique_folder_name.return_value = "Colliding (1)"
        mock_folder_repo.list_by_parent.return_value = [
            FolderResponseDto(
                id=1,
                workspace_id=1,
                user_email="a@b.com",
                name="Colliding (1)",
                parent_id=5,
            )
        ]

        dto = FolderUpdateDto(parent_id=5)
        result = await folder_service.update_folder(1, dto, sample_user)
        assert folder.parent_id == 5
        assert folder.name == "Colliding (1)"
        assert result.name == "Colliding (1)"

    @pytest.mark.anyio
    async def test_update_parent_cycle_error(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Parent"
        )
        mock_folder_repo.get_folder_by_id.side_effect = lambda fid: (
            folder
            if fid == 1
            else Folder(
                id=3, workspace_id=1, user_email="a@b.com", name="Child"
            )
        )
        # Child 3 is a descendant of 1
        mock_folder_repo.get_descendant_ids.return_value = [1, 2, 3]

        dto = FolderUpdateDto(parent_id=3)
        with pytest.raises(HTTPException) as exc_info:
            await folder_service.update_folder(1, dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.anyio
    async def test_update_parent_itself_error(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Parent"
        )
        mock_folder_repo.get_folder_by_id.return_value = folder

        dto = FolderUpdateDto(parent_id=1)
        with pytest.raises(HTTPException) as exc_info:
            await folder_service.update_folder(1, dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


class TestDeleteFolder:
    """Tests for FolderService.delete_folder."""

    @pytest.mark.anyio
    async def test_delete_folder_success(
        self, folder_service, mock_folder_repo, sample_user
    ):
        folder = Folder(id=1, workspace_id=1, user_email="a@b.com", name="F")
        mock_folder_repo.get_folder_by_id.return_value = folder
        mock_folder_repo.soft_delete.return_value = True

        result = await folder_service.delete_folder(1, sample_user)
        assert result["success"] is True
        mock_folder_repo.soft_delete.assert_called_once_with(
            folder_id=1, user_id=sample_user.id
        )


class TestMoveItems:
    """Tests for FolderService.move_items."""

    @pytest.mark.anyio
    async def test_move_items_success(
        self, folder_service, mock_folder_repo, sample_user
    ):
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=5, workspace_id=1, user_email="a@b.com", name="Target"
        )
        mock_folder_repo.get_descendant_ids.return_value = [2]
        mock_folder_repo.move_media_items.return_value = 2
        mock_folder_repo.move_source_assets.return_value = 1
        mock_folder_repo.move_folders.return_value = 1

        dto = MoveItemsDto(
            workspace_id=1,
            media_item_ids=[10, 11],
            source_asset_ids=[20],
            folder_ids=[2],
            destination_folder_id=5,
        )

        result = await folder_service.move_items(dto, sample_user)
        assert result["total_moved"] == 4
        assert result["media_items_moved"] == 2
        assert result["source_assets_moved"] == 1
        assert result["folders_moved"] == 1

    @pytest.mark.anyio
    async def test_move_items_into_itself_error(
        self, folder_service, mock_folder_repo, sample_user
    ):
        mock_folder_repo.get_folder_by_id.return_value = Folder(
            id=5, workspace_id=1, user_email="a@b.com", name="Target"
        )

        dto = MoveItemsDto(
            workspace_id=1,
            folder_ids=[5],
            destination_folder_id=5,
        )

        with pytest.raises(HTTPException) as exc_info:
            await folder_service.move_items(dto, sample_user)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
