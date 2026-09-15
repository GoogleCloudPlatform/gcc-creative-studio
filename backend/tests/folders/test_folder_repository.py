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

from src.common.schema.media_item_model import MediaItem
from src.folders.dto.folder_dto import ConflictStrategyEnum
from src.folders.repository.folder_repository import (
    FolderRepository,
    generate_disambiguated_name,
)
from src.folders.schema.folder_model import Folder
from src.source_assets.schema.source_asset_model import SourceAsset


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
    async def test_get_folders_by_ids_empty(self, folder_repo, mock_db):
        res = await folder_repo.get_folders_by_ids([])
        assert res == []
        mock_db.execute.assert_not_called()

    @pytest.mark.anyio
    async def test_get_folders_by_ids_with_workspace(
        self, folder_repo, mock_db
    ):
        folder1 = Folder(
            id=1, workspace_id=1, user_email="a@b.com", name="Folder 1"
        )
        folder2 = Folder(
            id=2, workspace_id=1, user_email="a@b.com", name="Folder 2"
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [folder1, folder2]
        mock_db.execute.return_value = mock_result

        res = await folder_repo.get_folders_by_ids([1, 2], workspace_id=1)
        assert len(res) == 2
        assert res[0].id == 1
        assert res[1].id == 2
        mock_db.execute.assert_called_once()

    @pytest.mark.anyio
    async def test_get_folder_counts(self, folder_repo, mock_db):
        mock_result = MagicMock()
        mock_result.one.return_value = (
            3,
            2,
            1,
        )  # media_count, asset_count, subfolder_count
        mock_db.execute.return_value = mock_result

        item_count, subfolder_count = await folder_repo.get_folder_counts(
            folder_id=1
        )
        assert item_count == 5
        assert subfolder_count == 1
        mock_db.execute.assert_called_once()

    @pytest.mark.anyio
    async def test_get_folder_counts_none(self, folder_repo, mock_db):
        mock_result = MagicMock()
        mock_result.one.return_value = (None, None, None)
        mock_db.execute.return_value = mock_result

        item_count, subfolder_count = await folder_repo.get_folder_counts(
            folder_id=1
        )
        assert item_count == 0
        assert subfolder_count == 0
        mock_db.execute.assert_called_once()

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
        mock_row1 = SimpleNamespace(
            id=1, name="Root", parent_id=None, workspace_id=1
        )
        mock_row2 = SimpleNamespace(
            id=2, name="Child", parent_id=1, workspace_id=1
        )
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
    async def test_get_folder_depth(self, folder_repo, mock_db):
        mock_row1 = SimpleNamespace(
            id=1, name="Root", parent_id=None, workspace_id=1
        )
        mock_row2 = SimpleNamespace(
            id=2, name="Child", parent_id=1, workspace_id=1
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row1, mock_row2]
        mock_db.execute.return_value = mock_result

        depth = await folder_repo.get_folder_depth(2)
        assert depth == 2

    @pytest.mark.anyio
    async def test_get_subtree_depth(self, folder_repo, mock_db):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_result

        depth = await folder_repo.get_subtree_depth(1)
        assert depth == 3

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
        # Executes: 1) CTE get descendants, 2) media soft-delete, 3) asset soft-delete, 4) folder soft-delete
        assert mock_db.execute.call_count == 4
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
        executed_stmt = mock_db.execute.call_args[0][0]
        assert "media_items.deleted_at IS NULL" in str(executed_stmt)

    @pytest.mark.anyio
    async def test_move_media_items_without_commit(self, folder_repo, mock_db):
        mock_result = MagicMock(rowcount=2)
        mock_db.execute.return_value = mock_result

        count = await folder_repo.move_media_items(
            [1, 2], workspace_id=1, destination_folder_id=3, commit=False
        )
        assert count == 2
        mock_db.commit.assert_not_called()
        executed_stmt = mock_db.execute.call_args[0][0]
        assert "media_items.deleted_at IS NULL" in str(executed_stmt)

    @pytest.mark.anyio
    async def test_move_source_assets(self, folder_repo, mock_db):
        mock_result = MagicMock(rowcount=1)
        mock_db.execute.return_value = mock_result

        count = await folder_repo.move_source_assets(
            [10], workspace_id=1, destination_folder_id=3
        )
        assert count == 1
        mock_db.commit.assert_called_once()
        executed_stmt = mock_db.execute.call_args[0][0]
        assert "source_assets.deleted_at IS NULL" in str(executed_stmt)

    @pytest.mark.anyio
    async def test_move_source_assets_without_commit(
        self, folder_repo, mock_db
    ):
        mock_result = MagicMock(rowcount=1)
        mock_db.execute.return_value = mock_result

        count = await folder_repo.move_source_assets(
            [10], workspace_id=1, destination_folder_id=3, commit=False
        )
        assert count == 1
        mock_db.commit.assert_not_called()
        executed_stmt = mock_db.execute.call_args[0][0]
        assert "source_assets.deleted_at IS NULL" in str(executed_stmt)

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
    async def test_move_folders_without_commit(self, folder_repo, mock_db):
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
            [5], workspace_id=1, destination_folder_id=3, commit=False
        )
        assert count == 1
        assert f5.parent_id == 3
        mock_db.commit.assert_not_called()

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

        mock_delete_media_tags = MagicMock()
        mock_delete_asset_tags = MagicMock()
        mock_media_res = MagicMock(rowcount=3)
        mock_asset_res = MagicMock(rowcount=2)
        mock_other_res = MagicMock(rowcount=1)

        mock_db.execute.side_effect = [
            mock_get_root,
            mock_desc_res,
            mock_existing_root_res,
            mock_delete_media_tags,
            mock_delete_asset_tags,
            mock_media_res,
            mock_asset_res,
            mock_other_res,
        ]

        result = await folder_repo.move_folder_to_workspace(
            folder_id=1, target_workspace_id=99
        )
        assert result["folders_moved"] == 2
        assert result["media_moved"] == 3
        assert result["assets_moved"] == 2
        assert root_folder.workspace_id == 99
        assert root_folder.parent_id is None
        assert root_folder.name == "ExistingRoot (1)"
        assert mock_db.execute.call_count == 8
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_folder_to_workspace_no_commit(
        self, folder_repo, mock_db
    ):
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
        mock_desc_res = MagicMock()
        mock_desc_res.fetchall.return_value = [mock_row1]

        mock_existing_root_res = MagicMock()
        mock_existing_root_res.fetchall.return_value = []

        mock_media_res = MagicMock(rowcount=1)
        mock_asset_res = MagicMock(rowcount=1)

        mock_db.execute.side_effect = [
            mock_get_root,
            mock_desc_res,
            mock_existing_root_res,
            MagicMock(),  # delete media tags
            MagicMock(),  # delete asset tags
            mock_media_res,
            mock_asset_res,
        ]

        result = await folder_repo.move_folder_to_workspace(
            folder_id=1, target_workspace_id=99, commit=False
        )
        assert result["folders_moved"] == 1
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_move_folder_to_workspace_same_workspace(
        self, folder_repo, mock_db
    ):
        root_folder = Folder(
            id=1,
            workspace_id=99,
            user_email="a@b.com",
            name="Root",
            parent_id=None,
        )
        mock_get_root = MagicMock()
        mock_get_root.scalars.return_value.first.return_value = root_folder

        mock_row1 = MagicMock(id=1)
        mock_desc_res = MagicMock()
        mock_desc_res.fetchall.return_value = [mock_row1]

        mock_existing_root_res = MagicMock()
        mock_existing_root_res.fetchall.return_value = []

        mock_media_res = MagicMock(rowcount=1)
        mock_asset_res = MagicMock(rowcount=1)

        mock_db.execute.side_effect = [
            mock_get_root,
            mock_desc_res,
            mock_existing_root_res,
            mock_media_res,
            mock_asset_res,
        ]

        result = await folder_repo.move_folder_to_workspace(
            folder_id=1, target_workspace_id=99
        )
        assert result["folders_moved"] == 1
        assert mock_db.execute.call_count == 5
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

        mock_row1 = SimpleNamespace(
            id=1, name="ExistingRoot", color="#fff", parent_id=None, depth=0
        )
        mock_row2 = SimpleNamespace(
            id=2, name="Subfolder", color="#fff", parent_id=1, depth=1
        )
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
            titles=["copied_media_title"],
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
            titles=["copied_asset_title"],
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
        assert mock_db.flush.call_count == 2
        mock_db.commit.assert_called_once()

        added_entities = [call.args[0] for call in mock_db.add.call_args_list]
        added_media = [e for e in added_entities if isinstance(e, MediaItem)]
        added_assets = [e for e in added_entities if isinstance(e, SourceAsset)]
        assert len(added_media) == 1
        assert len(added_assets) == 1
        assert added_media[0].titles == ["copied_media_title"]
        assert added_media[0].titles is not mock_media1.titles
        assert added_assets[0].titles == ["copied_asset_title"]
        assert added_assets[0].titles is not mock_asset1.titles

    @pytest.mark.anyio
    async def test_copy_folder_to_workspace_no_commit(
        self, folder_repo, mock_db
    ):
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

        mock_row1 = SimpleNamespace(
            id=1, name="ExistingRoot", color="#fff", parent_id=None, depth=0
        )
        mock_desc_res = MagicMock()
        mock_desc_res.fetchall.return_value = [mock_row1]

        mock_existing_root_res = MagicMock()
        mock_existing_root_res.fetchall.return_value = []

        mock_media_res = MagicMock()
        mock_media_res.scalars.return_value.all.return_value = []

        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = []

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
            commit=False,
        )
        assert result["folders_copied"] == 1
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_copy_folder_to_workspace_batches_flush_by_depth(
        self, folder_repo, mock_db
    ):
        root_folder = Folder(
            id=1,
            workspace_id=1,
            user_email="a@b.com",
            name="BatchRoot",
            parent_id=None,
            color="#fff",
        )
        mock_get_root = MagicMock()
        mock_get_root.scalars.return_value.first.return_value = root_folder

        # 6 folders across 3 depth levels:
        # Depth 0: Root (id 1)
        # Depth 1: Subfolder 1 (id 2), Subfolder 2 (id 3), Subfolder 3 (id 4)
        # Depth 2: Sub-subfolder 1 (id 5, parent 2), Sub-subfolder 2 (id 6, parent 3)
        mock_rows = [
            SimpleNamespace(
                id=1, name="BatchRoot", color="#fff", parent_id=None, depth=0
            ),
            SimpleNamespace(
                id=2, name="Sub 1", color="#fff", parent_id=1, depth=1
            ),
            SimpleNamespace(
                id=3, name="Sub 2", color="#fff", parent_id=1, depth=1
            ),
            SimpleNamespace(
                id=4, name="Sub 3", color="#fff", parent_id=1, depth=1
            ),
            SimpleNamespace(
                id=5, name="Sub-sub 1", color="#fff", parent_id=2, depth=2
            ),
            SimpleNamespace(
                id=6, name="Sub-sub 2", color="#fff", parent_id=3, depth=2
            ),
        ]
        mock_desc_res = MagicMock()
        mock_desc_res.fetchall.return_value = mock_rows

        mock_existing_root_res = MagicMock()
        mock_existing_root_res.fetchall.return_value = []

        mock_media_res = MagicMock()
        mock_media_res.scalars.return_value.all.return_value = []

        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_get_root,
            mock_desc_res,
            mock_existing_root_res,
            mock_media_res,
            mock_asset_res,
        ]

        # Simulate DB assigning auto-increment primary key ID on flush
        next_id = 100
        added_folders: list[Folder] = []

        def mock_add(obj):
            if isinstance(obj, Folder):
                added_folders.append(obj)

        mock_db.add = MagicMock(side_effect=mock_add)

        async def fake_flush():
            nonlocal next_id
            for folder in added_folders:
                if getattr(folder, "id", None) is None:
                    next_id += 1
                    folder.id = next_id

        mock_db.flush.side_effect = fake_flush

        result = await folder_repo.copy_folder_to_workspace(
            folder_id=1,
            target_workspace_id=99,
            user_id=1,
            user_email="tester@test.com",
        )

        assert result["folders_copied"] == 6
        # Crucial check: flush must be called exactly 3 times (depth 0, depth 1, depth 2), NOT 6 times!
        assert mock_db.flush.call_count == 3

        # Verify parent-child ID chaining
        # Root (depth 0) -> ID 101, parent_id is None
        assert added_folders[0].name == "BatchRoot"
        assert added_folders[0].parent_id is None
        assert added_folders[0].id == 101

        # Depth 1: folders 1, 2, 3 -> IDs 102, 103, 104, parent_id is 101
        for folder in added_folders[1:4]:
            assert folder.parent_id == 101

        # Depth 2: folder 5 has parent_id 102 (from folder 2), folder 6 has parent_id 103 (from folder 3)
        assert added_folders[4].name == "Sub-sub 1"
        assert added_folders[4].parent_id == 102
        assert added_folders[5].name == "Sub-sub 2"
        assert added_folders[5].parent_id == 103

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

    @pytest.mark.anyio
    async def test_copy_media_items_within_workspace(
        self, folder_repo, mock_db
    ):
        mock_item = MagicMock(
            id=10,
            titles=["test"],
            descriptions=["desc"],
            original_file_name="test.png",
            mime_type="image/png",
            thumbnail_uris=[],
            gcs_uris=[],
            original_gcs_uris=[],
            user_id=1,
            user_email="a@b.com",
            aspect_ratio="1:1",
            generation_time=1.0,
            error_message=None,
            style=None,
            lighting=None,
            color_and_tone=None,
            composition=None,
            negative_prompt=None,
            add_watermark=False,
            status="completed",
            source_assets=None,
            source_media_items=None,
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
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_item]

        mock_tag_row = MagicMock(media_item_id=10, tag_id=42)
        mock_tag_res = MagicMock()
        mock_tag_res.fetchall.return_value = [mock_tag_row]

        mock_db.execute.side_effect = [mock_res, mock_tag_res, MagicMock()]

        # Assign ID on flush
        def fake_flush():
            for call in mock_db.add.call_args_list:
                added = call.args[0]
                if (
                    isinstance(added, MediaItem)
                    and getattr(added, "id", None) is None
                ):
                    added.id = 100

        mock_db.flush.side_effect = fake_flush

        copied = await folder_repo.copy_media_items(
            media_item_ids=[10],
            workspace_id=1,
            destination_folder_id=5,
            user_id=2,
            user_email="b@b.com",
        )
        assert copied == 1
        assert mock_db.add.called
        added_media = [
            call.args[0]
            for call in mock_db.add.call_args_list
            if isinstance(call.args[0], MediaItem)
        ]
        assert len(added_media) == 1
        assert added_media[0].workspace_id == 1
        assert added_media[0].folder_id == 5
        assert added_media[0].user_id == 2
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_copy_source_assets_within_workspace(
        self, folder_repo, mock_db
    ):
        mock_asset = MagicMock(
            id=20,
            gcs_uri="gs://b/a.png",
            original_filename="a.png",
            titles=["asset"],
            descriptions=[],
            mime_type="image/png",
            aspect_ratio="1:1",
            file_hash="h",
            scope="private",
            asset_type="generic_image",
            thumbnail_gcs_uri=None,
            original_gcs_uri=None,
            external_url=None,
            user_id=1,
        )
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_asset]

        mock_tag_row = MagicMock(source_asset_id=20, tag_id=99)
        mock_tag_res = MagicMock()
        mock_tag_res.fetchall.return_value = [mock_tag_row]

        mock_db.execute.side_effect = [mock_res, mock_tag_res, MagicMock()]

        def fake_flush():
            for call in mock_db.add.call_args_list:
                added = call.args[0]
                if (
                    isinstance(added, SourceAsset)
                    and getattr(added, "id", None) is None
                ):
                    added.id = 200

        mock_db.flush.side_effect = fake_flush

        copied = await folder_repo.copy_source_assets(
            source_asset_ids=[20],
            workspace_id=1,
            destination_folder_id=5,
            user_id=2,
        )
        assert copied == 1
        added_assets = [
            call.args[0]
            for call in mock_db.add.call_args_list
            if isinstance(call.args[0], SourceAsset)
        ]
        assert len(added_assets) == 1
        assert added_assets[0].workspace_id == 1
        assert added_assets[0].folder_id == 5
        assert added_assets[0].user_id == 2
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_copy_items_aggregates_counts(self, folder_repo, mock_db):
        folder_repo.copy_media_items = AsyncMock(return_value=2)
        folder_repo.copy_source_assets = AsyncMock(return_value=1)
        folder_repo.copy_folders = AsyncMock(
            return_value={
                "folders_copied": 3,
                "media_copied": 4,
                "assets_copied": 5,
            }
        )

        result = await folder_repo.copy_items(
            workspace_id=1,
            media_item_ids=[1, 2],
            source_asset_ids=[10],
            folder_ids=[5],
            destination_folder_id=8,
        )
        assert result["media_items_copied"] == 6
        assert result["source_assets_copied"] == 6
        assert result["folders_copied"] == 3
        assert result["total_copied"] == 15
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

    @pytest.mark.anyio
    async def test_copy_items_rollback_on_failure(self, folder_repo, mock_db):
        folder_repo.copy_media_items = AsyncMock(return_value=2)
        folder_repo.copy_source_assets = AsyncMock(return_value=1)
        folder_repo.copy_folders = AsyncMock(
            side_effect=RuntimeError("Database constraint error")
        )

        with pytest.raises(RuntimeError, match="Database constraint error"):
            await folder_repo.copy_items(
                workspace_id=1,
                media_item_ids=[1, 2],
                source_asset_ids=[10],
                folder_ids=[5],
                destination_folder_id=8,
            )

        mock_db.commit.assert_not_called()
        mock_db.rollback.assert_called_once()

    @pytest.mark.anyio
    async def test_copy_items_atomic_execution_commits_once(
        self, folder_repo, mock_db
    ):
        mock_media = MagicMock(
            id=10,
            titles=["test"],
            descriptions=[],
            original_file_name="test.png",
            mime_type="image/png",
            thumbnail_uris=[],
            gcs_uris=[],
            original_gcs_uris=[],
            user_id=1,
            user_email="a@b.com",
            aspect_ratio="1:1",
            generation_time=1.0,
            error_message=None,
            style=None,
            lighting=None,
            color_and_tone=None,
            composition=None,
            negative_prompt=None,
            add_watermark=False,
            status="completed",
            source_assets=None,
            source_media_items=None,
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
        mock_media_res.scalars.return_value.all.return_value = [mock_media]
        mock_media_tags_res = MagicMock()
        mock_media_tags_res.fetchall.return_value = []

        mock_asset = MagicMock(
            id=20,
            gcs_uri="gs://b/a.png",
            original_filename="a.png",
            titles=["asset"],
            descriptions=[],
            mime_type="image/png",
            aspect_ratio="1:1",
            file_hash="h",
            scope="private",
            asset_type="generic_image",
            thumbnail_gcs_uri=None,
            original_gcs_uri=None,
            external_url=None,
            user_id=1,
        )
        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = [mock_asset]
        mock_asset_tags_res = MagicMock()
        mock_asset_tags_res.fetchall.return_value = []

        # Folder queries: select folders to copy -> none found for simplicity
        mock_folders_res = MagicMock()
        mock_folders_res.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_media_res,
            mock_media_tags_res,
            mock_asset_res,
            mock_asset_tags_res,
            mock_folders_res,
        ]

        result = await folder_repo.copy_items(
            workspace_id=1,
            media_item_ids=[10],
            source_asset_ids=[20],
            folder_ids=[999],
            destination_folder_id=5,
            user_id=1,
            user_email="a@b.com",
        )

        assert result["media_items_copied"] == 1
        assert result["source_assets_copied"] == 1
        assert result["folders_copied"] == 0
        assert result["total_copied"] == 2
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

    @pytest.mark.anyio
    async def test_merge_folders_not_found(self, folder_repo, mock_db):
        mock_res = MagicMock()
        mock_res.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = mock_res

        result = await folder_repo.merge_folders(
            source_folder_id=1,
            target_folder_id=2,
            target_workspace_id=1,
            is_copy=False,
        )
        assert result["folders_moved"] == 0
        assert result["media_moved"] == 0
        assert result["assets_moved"] == 0

    @pytest.mark.anyio
    async def test_merge_folders_move(self, folder_repo, mock_db):
        source = Folder(
            id=1, workspace_id=1, name="Source", parent_id=None, color="#fff"
        )
        target = Folder(
            id=2, workspace_id=2, name="Target", parent_id=None, color="#fff"
        )

        folder_repo.get_folder_by_id = AsyncMock(
            side_effect=lambda fid: (
                source if fid == 1 else target if fid == 2 else None
            )
        )
        folder_repo.get_descendant_ids = AsyncMock(return_value=[3])

        mock_media = MagicMock(id=10)
        mock_media_res = MagicMock()
        mock_media_res.scalars.return_value.all.return_value = [mock_media]

        mock_asset = MagicMock(id=20)
        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = [mock_asset]

        mock_child = Folder(
            id=3, workspace_id=1, name="Child", parent_id=1, color="#fff"
        )
        mock_children_res = MagicMock()
        mock_children_res.scalars.return_value.all.return_value = [mock_child]

        mock_target_children_res = MagicMock()
        mock_target_children_res.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_media_res,
            MagicMock(),  # delete media tags
            MagicMock(),  # update media
            mock_asset_res,
            MagicMock(),  # delete asset tags
            MagicMock(),  # update asset
            mock_children_res,
            mock_target_children_res,
            MagicMock(),  # delete child media tags
            MagicMock(),  # delete child asset tags
            MagicMock(),  # update child folders
            MagicMock(),  # update child media items
            MagicMock(),  # update child assets
        ]

        result = await folder_repo.merge_folders(
            source_folder_id=1,
            target_folder_id=2,
            target_workspace_id=2,
            user_id=5,
            is_copy=False,
            clear_tags=True,
        )

        assert result["folders_moved"] == 2  # source folder + child
        assert result["media_moved"] == 1
        assert result["assets_moved"] == 1
        assert source.deleted_at is not None
        assert source.deleted_by == 5
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_merge_folders_no_commit(self, folder_repo, mock_db):
        source = Folder(
            id=1, workspace_id=1, name="Source", parent_id=None, color="#fff"
        )
        target = Folder(
            id=2, workspace_id=2, name="Target", parent_id=None, color="#fff"
        )

        folder_repo.get_folder_by_id = AsyncMock(
            side_effect=lambda fid: (
                source if fid == 1 else target if fid == 2 else None
            )
        )
        mock_media_res = MagicMock()
        mock_media_res.scalars.return_value.all.return_value = []

        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = []

        mock_children_res = MagicMock()
        mock_children_res.scalars.return_value.all.return_value = []

        mock_target_children_res = MagicMock()
        mock_target_children_res.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_media_res,
            mock_asset_res,
            mock_children_res,
            mock_target_children_res,
        ]

        result = await folder_repo.merge_folders(
            source_folder_id=1,
            target_folder_id=2,
            target_workspace_id=2,
            user_id=5,
            is_copy=False,
            clear_tags=False,
            commit=False,
        )

        assert result["folders_moved"] == 1
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_merge_folders_copy(self, folder_repo, mock_db):
        source = Folder(
            id=1, workspace_id=1, name="Source", parent_id=None, color="#fff"
        )
        target = Folder(
            id=2, workspace_id=1, name="Target", parent_id=None, color="#fff"
        )

        folder_repo.get_folder_by_id = AsyncMock(
            side_effect=lambda fid: (
                source if fid == 1 else target if fid == 2 else None
            )
        )
        folder_repo._copy_subtree_under = AsyncMock(
            return_value={
                "folders_copied": 1,
                "media_copied": 0,
                "assets_copied": 0,
            }
        )

        mock_media = MagicMock(
            id=10,
            titles=["test"],
            descriptions=[],
            original_file_name="test.png",
            mime_type="image/png",
            thumbnail_uris=[],
            gcs_uris=[],
            original_gcs_uris=[],
            user_id=1,
            user_email="a@b.com",
            aspect_ratio="1:1",
            generation_time=1.0,
            error_message=None,
            style=None,
            lighting=None,
            color_and_tone=None,
            composition=None,
            negative_prompt=None,
            add_watermark=False,
            status="completed",
            source_assets=None,
            source_media_items=None,
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
        mock_media_res.scalars.return_value.all.return_value = [mock_media]

        mock_media_tags_res = MagicMock()
        mock_media_tags_res.fetchall.return_value = []

        mock_asset = MagicMock(
            id=20,
            gcs_uri="gs://b/a.png",
            original_filename="a.png",
            titles=["asset"],
            descriptions=[],
            mime_type="image/png",
            aspect_ratio="1:1",
            file_hash="h",
            scope="private",
            asset_type="generic_image",
            thumbnail_gcs_uri=None,
            original_gcs_uri=None,
            external_url=None,
            user_id=1,
        )
        mock_asset_res = MagicMock()
        mock_asset_res.scalars.return_value.all.return_value = [mock_asset]

        mock_asset_tags_res = MagicMock()
        mock_asset_tags_res.fetchall.return_value = []

        mock_child = Folder(
            id=3, workspace_id=1, name="Child", parent_id=1, color="#fff"
        )
        mock_children_res = MagicMock()
        mock_children_res.scalars.return_value.all.return_value = [mock_child]

        mock_target_children_res = MagicMock()
        mock_target_children_res.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_media_res,
            mock_media_tags_res,
            mock_asset_res,
            mock_asset_tags_res,
            mock_children_res,
            mock_target_children_res,
        ]

        result = await folder_repo.merge_folders(
            source_folder_id=1,
            target_folder_id=2,
            target_workspace_id=1,
            user_id=5,
            is_copy=True,
            clear_tags=False,
        )

        assert result["folders_copied"] == 2  # target folder + child copied
        assert result["media_copied"] == 1
        assert result["assets_copied"] == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_move_folders_merge_strategy(self, folder_repo, mock_db):
        f1 = Folder(
            id=1, workspace_id=1, name="Colliding", parent_id=None, color="#fff"
        )
        f2 = Folder(
            id=2, workspace_id=1, name="Colliding", parent_id=5, color="#fff"
        )

        mock_folders_res = MagicMock()
        mock_folders_res.scalars.return_value.all.return_value = [f1]
        mock_db.execute.side_effect = [mock_folders_res]

        folder_repo.get_existing_folders_map = AsyncMock(
            return_value={"colliding": f2}
        )
        folder_repo.merge_folders = AsyncMock(
            return_value={
                "folders_moved": 1,
                "media_moved": 2,
                "assets_moved": 0,
            }
        )

        moved = await folder_repo.move_folders(
            folder_ids=[1],
            workspace_id=1,
            destination_folder_id=5,
            conflict_strategy=ConflictStrategyEnum.MERGE,
        )
        assert moved == 1
        folder_repo.merge_folders.assert_awaited_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_copy_folders_merge_strategy(self, folder_repo, mock_db):
        f1 = Folder(
            id=1, workspace_id=1, name="Colliding", parent_id=None, color="#fff"
        )
        f2 = Folder(
            id=2, workspace_id=1, name="Colliding", parent_id=5, color="#fff"
        )

        mock_folders_res = MagicMock()
        mock_folders_res.scalars.return_value.all.return_value = [f1]
        mock_db.execute.side_effect = [mock_folders_res]

        folder_repo.get_existing_folder_names = AsyncMock(return_value=set())
        folder_repo.get_folder_by_name = AsyncMock(return_value=f2)
        folder_repo.merge_folders = AsyncMock(
            return_value={
                "folders_copied": 1,
                "media_copied": 3,
                "assets_copied": 1,
            }
        )

        res = await folder_repo.copy_folders(
            folder_ids=[1],
            workspace_id=1,
            destination_folder_id=5,
            conflict_strategy=ConflictStrategyEnum.MERGE,
        )
        assert res["folders_copied"] == 1
        assert res["media_copied"] == 3
        assert res["assets_copied"] == 1
        folder_repo.merge_folders.assert_awaited_once()
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_move_folder_to_workspace_merge_strategy(
        self, folder_repo, mock_db
    ):
        root = Folder(
            id=1, workspace_id=1, name="Root", parent_id=None, color="#fff"
        )
        target = Folder(
            id=2, workspace_id=2, name="Root", parent_id=None, color="#fff"
        )

        folder_repo.get_folder_by_id = AsyncMock(return_value=root)
        folder_repo.get_descendant_ids = AsyncMock(return_value=[1])
        folder_repo.get_folder_by_name = AsyncMock(return_value=target)
        folder_repo.merge_folders = AsyncMock(
            return_value={
                "folders_moved": 1,
                "media_moved": 2,
                "assets_moved": 1,
            }
        )

        res = await folder_repo.move_folder_to_workspace(
            folder_id=1,
            target_workspace_id=2,
            conflict_strategy=ConflictStrategyEnum.MERGE,
        )
        assert res["folders_moved"] == 1
        folder_repo.merge_folders.assert_awaited_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_copy_folder_to_workspace_merge_strategy(
        self, folder_repo, mock_db
    ):
        root = Folder(
            id=1, workspace_id=1, name="Root", parent_id=None, color="#fff"
        )
        target = Folder(
            id=2, workspace_id=2, name="Root", parent_id=None, color="#fff"
        )

        folder_repo.get_folder_by_id = AsyncMock(return_value=root)
        folder_repo.get_folder_by_name = AsyncMock(return_value=target)
        folder_repo.merge_folders = AsyncMock(
            return_value={
                "folders_copied": 1,
                "media_copied": 2,
                "assets_copied": 1,
            }
        )

        res = await folder_repo.copy_folder_to_workspace(
            folder_id=1,
            target_workspace_id=2,
            user_id=1,
            conflict_strategy=ConflictStrategyEnum.MERGE,
        )
        assert res["folders_copied"] == 1
        folder_repo.merge_folders.assert_awaited_once()
        mock_db.commit.assert_called_once()
