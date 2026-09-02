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

"""Tests for Folder Repository."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.folders.repository.folder_repository import (
    FolderRepository,
    generate_disambiguated_name,
)
from src.folders.schema.folder_model import Folder


@pytest.fixture(name="mock_db")
def fixture_mock_db():
    """Provides a mocked AsyncSession."""
    session = AsyncMock()
    return session


@pytest.fixture(name="folder_repo")
def fixture_folder_repo(mock_db):
    """Provides a FolderRepository instance."""
    return FolderRepository(db=mock_db)


class TestDisambiguationHelper:
    """Unit tests for generate_disambiguated_name helper."""

    def test_no_collision(self):
        result = generate_disambiguated_name("Campaigns", {"other", "reports"})
        assert result == "Campaigns"

    def test_first_collision_adds_1(self):
        result = generate_disambiguated_name("Campaigns", {"campaigns"})
        assert result == "Campaigns (1)"

    def test_second_collision_adds_2(self):
        result = generate_disambiguated_name(
            "Campaigns", {"campaigns", "campaigns (1)"}
        )
        assert result == "Campaigns (2)"

    def test_existing_numbered_suffix_increments(self):
        result = generate_disambiguated_name("Campaigns (1)", {"campaigns (1)"})
        assert result == "Campaigns (2)"

    def test_higher_numbered_suffix_increments(self):
        result = generate_disambiguated_name("Campaigns (2)", {"campaigns (2)"})
        assert result == "Campaigns (3)"


class TestFolderRepository:
    """Tests for FolderRepository methods."""

    @pytest.mark.anyio
    async def test_is_folder_name_taken(self, folder_repo, mock_db):
        mock_result = MagicMock()
        mock_result.first.return_value = (1,)
        mock_db.execute.return_value = mock_result

        taken = await folder_repo.is_folder_name_taken(
            workspace_id=1,
            parent_id=None,
            name="  Marketing  ",
        )
        assert taken is True

    @pytest.mark.anyio
    async def test_get_existing_folder_names(self, folder_repo, mock_db):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("folder a",), ("folder b",)]
        mock_db.execute.return_value = mock_result

        names = await folder_repo.get_existing_folder_names(
            workspace_id=1, parent_id=5
        )
        assert names == {"folder a", "folder b"}

    @pytest.mark.anyio
    async def test_get_unique_folder_name(self, folder_repo, mock_db):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("assets",)]
        mock_db.execute.return_value = mock_result

        unique_name = await folder_repo.get_unique_folder_name(
            workspace_id=1, parent_id=None, base_name="Assets"
        )
        assert unique_name == "Assets (1)"

    @pytest.mark.anyio
    async def test_get_folder_by_id(self, folder_repo, mock_db):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Folder"
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = folder
        mock_db.execute.return_value = mock_result

        res = await folder_repo.get_folder_by_id(1)
        assert res is not None
        assert res.id == 1
        assert res.name == "Folder"

    @pytest.mark.anyio
    async def test_list_by_parent(self, folder_repo, mock_db):
        folder = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Folder 1"
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (
                folder,
                3,
                2,
                1,
            )  # folder, media_count, asset_count, subfolder_count
        ]
        mock_db.execute.return_value = mock_result

        res = await folder_repo.list_by_parent(workspace_id=1, parent_id=None)
        assert len(res) == 1
        assert res[0].name == "Folder 1"
        assert res[0].item_count == 5
        assert res[0].subfolder_count == 1

    @pytest.mark.anyio
    async def test_get_breadcrumbs(self, folder_repo, mock_db):
        mock_row1 = SimpleNamespace(id=1, name="Root", parent_id=None)
        mock_row2 = SimpleNamespace(id=2, name="Child", parent_id=1)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row1, mock_row2]
        mock_db.execute.return_value = mock_result

        res = await folder_repo.get_breadcrumbs(2)
        assert len(res) == 2
        assert res[0].name == "Root"
        assert res[1].name == "Child"

    @pytest.mark.anyio
    async def test_get_descendant_ids(self, folder_repo, mock_db):
        mock_row1 = MagicMock(id=1)
        mock_row2 = MagicMock(id=2)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row1, mock_row2]
        mock_db.execute.return_value = mock_result

        res = await folder_repo.get_descendant_ids(1)
        assert res == [1, 2]

    @pytest.mark.anyio
    async def test_get_tree(self, folder_repo, mock_db):
        f1 = Folder(
            id=1,
            workspace_id=1,
            user_email="a@b.com",
            name="Root",
            parent_id=None,
        )
        f2 = Folder(
            id=2,
            workspace_id=1,
            user_email="a@b.com",
            name="Child",
            parent_id=1,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [f1, f2]
        mock_db.execute.return_value = mock_result

        tree = await folder_repo.get_tree(workspace_id=1)
        assert len(tree) == 1
        assert tree[0].id == 1
        assert len(tree[0].children) == 1
        assert tree[0].children[0].id == 2

    @pytest.mark.anyio
    async def test_soft_delete(self, folder_repo, mock_db):
        mock_row1 = MagicMock(id=1)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row1]
        mock_db.execute.return_value = mock_result

        res = await folder_repo.soft_delete(folder_id=1, user_id=10)
        assert res is True
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_media_items(self, folder_repo, mock_db):
        mock_result = MagicMock(rowcount=2)
        mock_db.execute.return_value = mock_result

        count = await folder_repo.move_media_items(
            [1, 2], workspace_id=1, destination_folder_id=3
        )
        assert count == 2
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_source_assets(self, folder_repo, mock_db):
        mock_result = MagicMock(rowcount=1)
        mock_db.execute.return_value = mock_result

        count = await folder_repo.move_source_assets(
            [10], workspace_id=1, destination_folder_id=3
        )
        assert count == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_folders_disambiguation(self, folder_repo, mock_db):
        f5 = Folder(
            id=5,
            workspace_id=1,
            user_email="a@b.com",
            name="Colliding",
            parent_id=None,
        )
        mock_folders_res = MagicMock()
        mock_folders_res.scalars.return_value.all.return_value = [f5]

        mock_existing_names_res = MagicMock()
        mock_existing_names_res.fetchall.return_value = [("colliding",)]

        mock_db.execute.side_effect = [
            mock_folders_res,
            mock_existing_names_res,
        ]

        count = await folder_repo.move_folders(
            [5], workspace_id=1, destination_folder_id=3
        )
        assert count == 1
        assert f5.parent_id == 3
        assert f5.name == "Colliding (1)"
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_folder_to_workspace(self, folder_repo, mock_db):
        root_folder = Folder(
            id=1,
            workspace_id=1,
            user_email="a@b.com",
            name="ExistingRoot",
            parent_id=None,
        )
        mock_get_root = MagicMock()
        mock_get_root.scalars.return_value.first.return_value = root_folder

        mock_row1 = MagicMock(id=1)
        mock_row2 = MagicMock(id=2)
        mock_desc_res = MagicMock()
        mock_desc_res.fetchall.return_value = [mock_row1, mock_row2]

        mock_existing_root_res = MagicMock()
        mock_existing_root_res.fetchall.return_value = [("existingroot",)]

        mock_media_res = MagicMock(rowcount=3)
        mock_asset_res = MagicMock(rowcount=2)
        mock_other_res = MagicMock(rowcount=1)

        mock_db.execute.side_effect = [
            mock_get_root,
            mock_desc_res,
            mock_existing_root_res,
            mock_media_res,
            mock_asset_res,
            mock_other_res,
            mock_other_res,
        ]

        result = await folder_repo.move_folder_to_workspace(
            folder_id=1, target_workspace_id=99
        )
        assert result["folders_moved"] == 2
        assert result["media_moved"] == 3
        assert result["assets_moved"] == 2
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_folder_to_workspace_empty(self, folder_repo, mock_db):
        mock_get_root = MagicMock()
        mock_get_root.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = mock_get_root

        result = await folder_repo.move_folder_to_workspace(
            folder_id=999, target_workspace_id=99
        )
        assert result["folders_moved"] == 0
        assert result["media_moved"] == 0
        assert result["assets_moved"] == 0

    @pytest.mark.anyio
    async def test_copy_folder_to_workspace(self, folder_repo, mock_db):
        root_folder = Folder(
            id=1,
            workspace_id=1,
            user_email="a@b.com",
            name="ExistingRoot",
            parent_id=None,
            color="#fff",
        )
        mock_get_root = MagicMock()
        mock_get_root.scalars.return_value.first.return_value = root_folder

        mock_row1 = MagicMock(
            id=1, name="ExistingRoot", color="#fff", parent_id=None
        )
        mock_row2 = MagicMock(id=2, name="Subfolder", color="#fff", parent_id=1)
        mock_desc_res = MagicMock()
        mock_desc_res.fetchall.return_value = [mock_row1, mock_row2]

        mock_existing_root_res = MagicMock()
        mock_existing_root_res.fetchall.return_value = [("existingroot",)]

        mock_media1 = MagicMock(
            id=10,
            folder_id=1,
            user_email="a@b.com",
            mime_type="image/png",
            model="imagen",
            titles=[],
            descriptions=[],
            prompt="p",
            original_prompt="op",
            rewritten_prompt="rp",
            num_media=1,
            generation_time=1.0,
            error_message=None,
            thumbnail_uris=[],
            aspect_ratio="1:1",
            style=None,
            lighting=None,
            color_and_tone=None,
            composition=None,
            negative_prompt=None,
            add_watermark=False,
            status="completed",
            source_assets=None,
            source_media_items=None,
            gcs_uris=[],
            original_gcs_uris=[],
            duration_seconds=None,
            comment=None,
            seed=None,
            critique=None,
            google_search=None,
            resolution=None,
            grounding_metadata=None,
            audio_analysis=None,
            voice_name=None,
            language_code=None,
            raw_data=None,
            created_from_template_id=None,
        )
        mock_media_res = MagicMock()
        mock_media_res.scalars.return_value.all.return_value = [mock_media1]

        mock_asset1 = MagicMock(
            id=20,
            folder_id=2,
            gcs_uri="gs://bucket/file.png",
            original_filename="file.png",
            titles=[],
            descriptions=[],
            mime_type="image/png",
            aspect_ratio="1:1",
            file_hash="hash",
            scope="private",
            asset_type="generic_image",
            thumbnail_gcs_uri=None,
            original_gcs_uri=None,
            external_url=None,
        )
        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = [mock_asset1]

        mock_db.execute.side_effect = [
            mock_get_root,
            mock_desc_res,
            mock_existing_root_res,
            mock_media_res,
            mock_asset_res,
        ]

        result = await folder_repo.copy_folder_to_workspace(
            folder_id=1,
            target_workspace_id=99,
            user_id=1,
            user_email="tester@test.com",
        )
        assert result["folders_copied"] == 2
        assert result["media_copied"] == 1
        assert result["assets_copied"] == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_copy_folder_to_workspace_empty(self, folder_repo, mock_db):
        mock_get_root = MagicMock()
        mock_get_root.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = mock_get_root

        result = await folder_repo.copy_folder_to_workspace(
            folder_id=999,
            target_workspace_id=99,
            user_id=1,
        )
        assert result["folders_copied"] == 0
        assert result["media_copied"] == 0
        assert result["assets_copied"] == 0
