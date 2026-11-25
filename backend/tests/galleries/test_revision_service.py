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
"""Unit tests for revision lineage resolution and RevisionService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
import pytest

from src.common.base_dto import GenerationModelEnum
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    MimeTypeEnum,
    SourceMediaItemLink,
)
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.galleries.revision_lineage import (
    RevisionLineage,
    effective_revision_folder,
    lock_media_stack_root,
    resolve_revision_lineage,
    sanitize_copied_media_kwargs,
)
from src.galleries.revision_service import RevisionService
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)


def _user(uid: int = 1, role: UserRoleEnum = UserRoleEnum.USER) -> UserModel:
    return UserModel(
        id=uid, email=f"u{uid}@test.com", name=f"User {uid}", roles=[role]
    )


def _media(
    item_id: int,
    workspace_id: int = 10,
    user_id: int = 1,
    revision_root_id: int | None = None,
    revision_parent_id: int | None = None,
    revision_number: int = 1,
    folder_id: int | None = None,
) -> MediaItemModel:
    return MediaItemModel(
        id=item_id,
        workspace_id=workspace_id,
        folder_id=folder_id,
        revision_root_id=revision_root_id,
        revision_parent_id=revision_parent_id,
        revision_number=revision_number,
        user_id=user_id,
        user_email=f"u{user_id}@test.com",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        model=GenerationModelEnum.IMAGEN_3_001,
        aspect_ratio="1:1",
        gcs_uris=["gs://b/img.png"],
        thumbnail_uris=["gs://b/thumb.png"],
        status=JobStatusEnum.COMPLETED,
        created_at=datetime.now(timezone.utc),
    )


def _hydrated_response(item: MediaItemModel) -> MediaItemResponse:
    return MediaItemResponse(
        **item.model_dump(),
        presigned_urls=["https://signed/img.png"],
        presigned_thumbnail_urls=["https://signed/thumb.png"],
    )


class TestRevisionLineageHelpers:
    def test_effective_revision_folder_prefers_explicit_override_and_inherits_stack(
        self,
    ):
        iter_lineage = RevisionLineage(
            revision_root_id=100,
            revision_parent_id=101,
            revision_number=3,
            inherited_folder_id=42,
        )
        assert effective_revision_folder(99, 99, iter_lineage) == 99
        assert effective_revision_folder(None, 55, iter_lineage) == 42

        fresh_lineage = RevisionLineage(None, None, 1, None)
        assert effective_revision_folder(None, 55, fresh_lineage) == 55

    @pytest.mark.anyio
    async def test_lock_media_stack_root_executes_for_update_query(self):
        mock_db = AsyncMock()
        await lock_media_stack_root(mock_db, 42)
        mock_db.execute.assert_awaited_once()
        stmt = mock_db.execute.await_args.args[0]
        assert stmt._for_update_arg is not None
        assert stmt.get_execution_options().get("include_deleted") is True

    @pytest.mark.anyio
    async def test_resolve_revision_lineage_same_workspace_locks_and_increments(
        self,
    ):
        mock_db = AsyncMock()
        parent = _media(
            12,
            workspace_id=10,
            revision_root_id=10,
            revision_number=2,
            folder_id=5,
        )
        parent_res = MagicMock()
        parent_res.scalar_one_or_none.return_value = parent
        lock_res = MagicMock()
        max_res = MagicMock()
        max_res.scalar_one.return_value = 3
        folder_res = MagicMock()
        folder_res.scalar_one_or_none.return_value = 8

        mock_db.execute.side_effect = [
            parent_res,
            lock_res,
            max_res,
            folder_res,
        ]

        lineage = await resolve_revision_lineage(
            mock_db, _user(1), output_workspace_id=10, explicit_parent_id=12
        )

        assert lineage == RevisionLineage(
            revision_root_id=10,
            revision_parent_id=12,
            revision_number=4,
            inherited_folder_id=8,
        )
        assert mock_db.execute.await_count == 4

    @pytest.mark.anyio
    async def test_resolve_revision_lineage_colleague_remix_starts_new_stack(
        self,
    ):
        mock_db = AsyncMock()
        colleague_item = _media(50, workspace_id=88, user_id=2)
        parent_res = MagicMock()
        parent_res.scalar_one_or_none.return_value = colleague_item
        mock_db.execute.return_value = parent_res

        lineage = await resolve_revision_lineage(
            mock_db,
            _user(1),
            output_workspace_id=10,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=50,
                    media_index=0,
                    role=AssetRoleEnum.INPUT,
                )
            ],
        )

        assert lineage == RevisionLineage(None, None, 1, None)

    @pytest.mark.anyio
    async def test_resolve_revision_lineage_missing_parent_returns_fresh(self):
        mock_db = AsyncMock()
        missing = MagicMock()
        missing.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = missing

        assert await resolve_revision_lineage(
            mock_db, _user(1), output_workspace_id=10, explicit_parent_id=999
        ) == RevisionLineage(None, None, 1, None)
        assert await resolve_revision_lineage(
            mock_db, _user(1), output_workspace_id=10
        ) == RevisionLineage(None, None, 1, None)

    @pytest.mark.anyio
    async def test_sanitize_copied_media_kwargs_drops_foreign_references(self):
        mock_db = AsyncMock()
        asset_res = MagicMock()
        asset_res.fetchall.return_value = [(2,)]
        media_res = MagicMock()
        media_res.fetchall.return_value = [(10,)]
        mock_db.execute.side_effect = [asset_res, media_res]

        kwargs = {
            "source_assets": [{"asset_id": 1}, {"asset_id": 2}],
            "source_media_items": [
                {"media_item_id": 10},
                {"media_item_id": 99},
            ],
        }
        await sanitize_copied_media_kwargs(
            mock_db, kwargs, target_workspace_id=50
        )

        assert kwargs["source_assets"] == [{"asset_id": 2}]
        assert kwargs["source_media_items"] == [{"media_item_id": 10}]

    @pytest.mark.anyio
    async def test_resolve_revision_lineage_cross_folder_starts_fresh_stack(
        self,
    ):
        parent = _media(
            10,
            workspace_id=1,
            revision_root_id=None,
            revision_number=1,
            folder_id=40,
        )
        parent_res = MagicMock()
        parent_res.scalar_one_or_none.return_value = parent
        lock_res = MagicMock()
        max_res = MagicMock()
        max_res.scalar_one.return_value = 1
        folder_res = MagicMock()
        folder_res.scalar_one_or_none.return_value = 40

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            parent_res,
            lock_res,
            max_res,
            folder_res,
        ]

        lineage = await resolve_revision_lineage(
            mock_db,
            _user(1),
            output_workspace_id=1,
            explicit_parent_id=10,
            requested_folder_id=50,
            resolved_folder_id=50,
        )
        assert lineage == RevisionLineage(None, None, 1, None)

        mock_db.execute.side_effect = [
            parent_res,
            lock_res,
            max_res,
            folder_res,
        ]
        same_folder_lineage = await resolve_revision_lineage(
            mock_db,
            _user(1),
            output_workspace_id=1,
            explicit_parent_id=10,
            requested_folder_id=40,
            resolved_folder_id=40,
        )
        assert same_folder_lineage == RevisionLineage(10, 10, 2, 40)


class TestRevisionService:
    @pytest.mark.anyio
    async def test_get_revisions_missing_item_raises_404(self):
        media_repo = AsyncMock()
        media_repo.get_by_id.return_value = None
        service = RevisionService(
            db=AsyncMock(),
            media_repo=media_repo,
            workspace_auth=AsyncMock(),
            gallery_service=AsyncMock(),
        )
        with pytest.raises(HTTPException) as exc:
            await service.get_revisions(404, _user(1))
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_get_revisions_shared_workspace_returns_single_take(
        self,
    ):
        item = _media(
            30, workspace_id=88, revision_root_id=10, revision_number=1
        )
        media_repo = AsyncMock()
        media_repo.get_by_id.return_value = item
        ws_auth = AsyncMock()
        ws_auth.authorize.return_value = WorkspaceModel(
            id=88,
            name="Shared Team",
            owner_id=2,
            scope=WorkspaceScopeEnum.PRIVATE,
            current_user_role=WorkspaceRoleEnum.VIEWER,
        )
        gallery_service = AsyncMock()
        gallery_service.hydrate_media_items.return_value = [
            _hydrated_response(item)
        ]
        mock_db = AsyncMock()
        service = RevisionService(
            db=mock_db,
            media_repo=media_repo,
            workspace_auth=ws_auth,
            gallery_service=gallery_service,
        )

        res = await service.get_revisions(30, _user(1))

        assert res.root_id == 30
        assert res.revision_count == 1
        assert len(res.takes) == 1
        mock_db.execute.assert_not_awaited()

    @pytest.mark.anyio
    async def test_get_revisions_personal_workspace_returns_ordered_takes(
        self,
    ):
        v1 = _media(
            10, workspace_id=1, revision_root_id=None, revision_number=1
        )
        v2 = _media(11, workspace_id=1, revision_root_id=10, revision_number=2)

        media_repo = AsyncMock()
        media_repo.get_by_id.return_value = v1
        ws_auth = AsyncMock()
        ws_auth.authorize.return_value = WorkspaceModel(
            id=1,
            name="My Workspace",
            owner_id=1,
            scope=WorkspaceScopeEnum.PERSONAL,
            current_user_role=WorkspaceRoleEnum.OWNER,
        )
        gallery_service = AsyncMock()
        gallery_service.hydrate_media_items.return_value = [
            _hydrated_response(v1),
            _hydrated_response(v2),
        ]

        takes_res = MagicMock()
        takes_res.scalars.return_value.all.return_value = [v1, v2]
        mock_db = AsyncMock()
        mock_db.execute.return_value = takes_res

        service = RevisionService(
            db=mock_db,
            media_repo=media_repo,
            workspace_auth=ws_auth,
            gallery_service=gallery_service,
        )

        res = await service.get_revisions(10, _user(1))

        assert res.root_id == 10
        assert res.revision_count == 2
        assert [t.id for t in res.takes] == [10, 11]
        gallery_service.hydrate_media_items.assert_awaited_once()
