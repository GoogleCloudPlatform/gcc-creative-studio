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
"""Tests for PromotionService target discovery and promotion flows."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_dto import GenerationModelEnum, MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.galleries.dto.bulk_copy_dto import BulkCopyItemDto
from src.galleries.dto.promote_dto import (
    PromoteItemsDto,
    PromoteTargetsRequestDto,
)
from src.galleries.promotion_service import MAX_FOLDER_DEPTH, PromotionService
from src.galleries.repository.promotion_mapper import (
    can_update_promoted,
)
from src.galleries.repository.promotion_repository import PromotionRepository
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
)
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)


@pytest.fixture(name="user")
def fixture_user():
    return UserModel(id=5, email="me@example.com", name="Me", roles=["user"])


def _build_service():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    exec_res = MagicMock()
    exec_res.fetchall.return_value = []
    db.execute.return_value = exec_res
    workspace_auth = AsyncMock()
    workspace_service = AsyncMock()
    folder_repo = AsyncMock()
    folder_repo.get_existing_folder_names = AsyncMock(return_value=set())
    folder_repo.get_folder_depth = AsyncMock(return_value=0)
    folder_repo.get_subtree_depth = AsyncMock(return_value=1)
    svc = PromotionService(
        db=db,
        workspace_auth=workspace_auth,
        workspace_service=workspace_service,
        folder_repo=folder_repo,
    )
    return svc, db, workspace_auth, workspace_service, folder_repo


@pytest.mark.anyio
async def test_get_promote_targets_filters_workspaces_and_computes_counts(user):
    svc, _db, ws_auth, ws_svc, _fr = _build_service()

    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=5,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    public_ws = WorkspaceModel(
        id=1,
        name="Public",
        owner_id=1,
        scope=WorkspaceScopeEnum.PUBLIC,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    viewer_ws = WorkspaceModel(
        id=2,
        name="ReadOnly Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.VIEWER,
    )
    editor_ws = WorkspaceModel(
        id=3,
        name="Campaign Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    ws_auth.authorize = AsyncMock(return_value=personal_ws)
    ws_svc.list_workspaces_for_user = AsyncMock(
        return_value=[personal_ws, public_ws, viewer_ws, editor_ws]
    )

    svc.promo_repo.collect_promotable_sources = AsyncMock(
        return_value=([(105, 100)], [], 0)
    )
    pm_rows = [
        SimpleNamespace(
            id=900,
            workspace_id=1,
            folder_id=None,
            user_id=99,
            promoted_from_root_id=100,
            promoted_from_media_item_id=101,
        ),
        SimpleNamespace(
            id=901,
            workspace_id=3,
            folder_id=44,
            user_id=5,
            promoted_from_root_id=100,
            promoted_from_media_item_id=102,
        ),
    ]
    svc.promo_repo.fetch_existing_media_promotions = AsyncMock(
        return_value=(pm_rows, {102: 2})
    )
    svc.promo_repo.fetch_existing_asset_promotions = AsyncMock(return_value=[])

    targets = await svc.get_promote_targets(
        PromoteTargetsRequestDto(
            source_workspace_id=10,
            items=[BulkCopyItemDto(id=105, type="media_item")],
        ),
        user,
    )
    assert [t.workspace_id for t in targets] == [1, 3]
    assert targets[0].existing_count == 0
    assert targets[0].new_count == 1
    assert targets[0].existing_promotion is None
    assert targets[1].existing_count == 1
    assert targets[1].new_count == 0
    assert targets[1].existing_promotion is not None
    assert targets[1].existing_promotion.target_item_id == 901
    assert targets[1].existing_promotion.promoted_revision_number == 2


@pytest.mark.anyio
async def test_get_promote_targets_folder_counts_all_as_net_new(user):
    svc, db, ws_auth, ws_svc, folder_repo = _build_service()
    svc.promo_repo = PromotionRepository(db, folder_repo)
    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=5,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    team_ws = WorkspaceModel(
        id=3,
        name="Campaign Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    ws_auth.authorize = AsyncMock(return_value=personal_ws)
    ws_svc.list_workspaces_for_user = AsyncMock(return_value=[team_ws])
    folder_repo.get_descendant_ids_batch = AsyncMock(return_value=[20, 21])

    m_res = MagicMock()
    m_res.scalar_one.return_value = 1
    a_res = MagicMock()
    a_res.scalar_one.return_value = 1
    db.execute.side_effect = [m_res, a_res]

    targets = await svc.get_promote_targets(
        PromoteTargetsRequestDto(
            source_workspace_id=10,
            items=[BulkCopyItemDto(id=20, type="folder")],
        ),
        user,
    )
    assert len(targets) == 1
    assert targets[0].existing_count == 0
    assert targets[0].new_count == 2
    assert targets[0].existing_promotion is None


@pytest.mark.anyio
async def test_promote_items_validation_errors(user):
    svc, _db, ws_auth, _ws_svc, folder_repo = _build_service()
    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=5,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )

    ws_auth.authorize = AsyncMock(
        return_value=WorkspaceModel(
            id=2,
            name="Shared Team",
            owner_id=1,
            scope=WorkspaceScopeEnum.PRIVATE,
            current_user_role=WorkspaceRoleEnum.VIEWER,
        )
    )
    with pytest.raises(HTTPException) as exc_non_personal:
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=1, type="media_item")],
                source_workspace_id=2,
                target_workspace_id=3,
            ),
            user,
        )
    assert exc_non_personal.value.status_code == 400
    with pytest.raises(HTTPException) as exc_targets_non_personal:
        await svc.get_promote_targets(
            PromoteTargetsRequestDto(
                source_workspace_id=2,
                items=[BulkCopyItemDto(id=1, type="media_item")],
            ),
            user,
        )
    assert exc_targets_non_personal.value.status_code == 400
    ws_auth.authorize = AsyncMock(return_value=personal_ws)

    with pytest.raises(HTTPException) as exc1:
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=1, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=10,
            ),
            user,
        )
    assert exc1.value.status_code == 400

    ws_auth.authorize_write = AsyncMock(
        return_value=WorkspaceModel(
            id=11, name="Other", owner_id=9, scope=WorkspaceScopeEnum.PERSONAL
        )
    )
    with pytest.raises(HTTPException) as exc2:
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=1, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=11,
            ),
            user,
        )
    assert exc2.value.status_code == 400

    ws_auth.authorize_write = AsyncMock(
        side_effect=HTTPException(status_code=403, detail="Read only")
    )
    with pytest.raises(HTTPException) as exc_viewer:
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=1, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=2,
            ),
            user,
        )
    assert exc_viewer.value.status_code == 403

    ws_auth.authorize_write = AsyncMock(
        return_value=WorkspaceModel(
            id=3, name="Team", owner_id=5, scope=WorkspaceScopeEnum.PRIVATE
        )
    )
    folder_repo.get_folder_by_id = AsyncMock(
        return_value=SimpleNamespace(id=50, workspace_id=99)
    )
    with pytest.raises(HTTPException) as exc3:
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=1, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=3,
                target_folder_id=50,
            ),
            user,
        )
    assert exc3.value.status_code == 422

    # Folder promotion exceeding MAX_FOLDER_DEPTH (20) must reject with 400
    folder_repo.get_folder_by_id = AsyncMock(
        side_effect=[
            SimpleNamespace(id=60, workspace_id=3, name="Deep Target"),
            SimpleNamespace(id=20, workspace_id=10, name="Nested Source"),
        ]
    )
    folder_repo.get_folder_depth = AsyncMock(return_value=MAX_FOLDER_DEPTH - 1)
    folder_repo.get_subtree_depth = AsyncMock(return_value=2)
    with pytest.raises(HTTPException) as exc_depth:
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=20, type="folder")],
                source_workspace_id=10,
                target_workspace_id=3,
                target_folder_id=60,
            ),
            user,
        )
    assert exc_depth.value.status_code == 400
    assert str(MAX_FOLDER_DEPTH) in exc_depth.value.detail


@pytest.mark.anyio
async def test_promote_media_update_and_create_modes(user):
    svc, db, ws_auth, _ws_svc, folder_repo = _build_service()

    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=5,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    target_ws = WorkspaceModel(
        id=3,
        name="Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    ws_auth.authorize = AsyncMock(return_value=personal_ws)
    ws_auth.authorize_write = AsyncMock(return_value=target_ws)

    src_media = MediaItem(
        id=105,
        workspace_id=10,
        user_id=5,
        user_email="me@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_FAST.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        gcs_uris=["gs://b/v2.png"],
        revision_root_id=100,
        revision_parent_id=100,
        revision_number=2,
        source_assets=[{"asset_id": 12, "role": "input"}],
        source_media_items=[
            {"media_item_id": 100, "media_index": 0, "role": "input"}
        ],
    )
    existing_target = MediaItem(
        id=901,
        workspace_id=3,
        folder_id=77,
        user_id=5,
        user_email="me@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_FAST.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        gcs_uris=["gs://b/v1.png"],
        promoted_from_root_id=100,
        promoted_from_media_item_id=100,
    )

    with (
        patch.object(
            svc.promo_repo,
            "get_source_media",
            new=AsyncMock(return_value=src_media),
        ),
        patch.object(
            svc.promo_repo,
            "list_updatable_media",
            new=AsyncMock(return_value=[existing_target]),
        ),
        patch(
            "src.galleries.repository.promotion_repository.lock_media_stack_root",
            new=AsyncMock(),
        ) as mock_lock,
    ):
        res = await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=105, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=3,
                mode="update_or_create",
            ),
            user,
        )

    mock_lock.assert_awaited_once_with(db, 100)
    assert existing_target.source_assets == []
    assert existing_target.source_media_items == []
    assert res.updated_count == 1
    assert res.created_count == 0
    assert existing_target.folder_id == 77
    assert existing_target.revision_root_id is None
    assert existing_target.revision_parent_id is None
    assert existing_target.revision_number == 1
    assert existing_target.promoted_from_media_item_id == 105
    assert existing_target.promoted_from_root_id == 100
    assert existing_target.gcs_uris == ["gs://b/v2.png"]

    with (
        patch.object(
            svc.promo_repo,
            "get_source_media",
            new=AsyncMock(return_value=src_media),
        ),
        patch.object(
            svc.promo_repo,
            "list_updatable_media",
            new=AsyncMock(return_value=[existing_target]),
        ),
        patch(
            "src.galleries.repository.promotion_repository.lock_media_stack_root",
            new=AsyncMock(),
        ),
    ):
        await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=105, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=3,
                target_folder_id=None,
                clear_target_folder=True,
                mode="update_or_create",
            ),
            user,
        )
    assert existing_target.folder_id is None

    def _assign_id(obj):
        obj.id = 950

    db.add = MagicMock(side_effect=_assign_id)
    folder_repo.get_folder_by_id = AsyncMock(
        return_value=SimpleNamespace(id=88, workspace_id=3)
    )
    with (
        patch.object(
            svc.promo_repo,
            "get_source_media",
            new=AsyncMock(return_value=src_media),
        ),
        patch(
            "src.galleries.repository.promotion_repository.lock_media_stack_root",
            new=AsyncMock(),
        ),
    ):
        res_new = await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=105, type="media_item")],
                source_workspace_id=10,
                target_workspace_id=3,
                target_folder_id=88,
                mode="create_new",
            ),
            user,
        )
    assert res_new.created_count == 1
    assert res_new.promoted_items[0].action == "created"
    assert res_new.promoted_items[0].target_id == 950
    assert res_new.promoted_items[0].target_folder_id == 88
    created_obj = db.add.call_args.args[0]
    assert created_obj.revision_root_id is None
    assert created_obj.revision_number == 1


@pytest.mark.anyio
async def test_promote_asset_and_folder_subtree(user):
    svc, db, ws_auth, _ws_svc, folder_repo = _build_service()
    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=5,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    target_ws = WorkspaceModel(
        id=3,
        name="Team",
        owner_id=5,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    ws_auth.authorize = AsyncMock(return_value=personal_ws)
    ws_auth.authorize_write = AsyncMock(return_value=target_ws)

    src_asset = SourceAsset(
        id=40,
        workspace_id=10,
        user_id=5,
        gcs_uri="gs://b/logo.png",
        original_filename="logo.png",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        aspect_ratio="1:1",
        file_hash="abc",
        scope=AssetScopeEnum.SYSTEM.value,
        asset_type=AssetTypeEnum.GENERIC_IMAGE.value,
        folder_id=20,
    )
    src_media_latest = MediaItem(
        id=105,
        workspace_id=10,
        folder_id=20,
        user_id=5,
        user_email="me@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_FAST.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        gcs_uris=["gs://b/v2.png"],
        revision_root_id=100,
        revision_number=2,
    )

    next_id = 500

    def _assign_id(obj):
        nonlocal next_id
        next_id += 1
        obj.id = next_id

    db.add = MagicMock(side_effect=_assign_id)
    folder_repo.get_folder_by_id = AsyncMock(
        return_value=SimpleNamespace(id=20, workspace_id=10, name="Moodboard")
    )

    with (
        patch.object(
            svc.promo_repo,
            "clone_folder_structure",
            new=AsyncMock(
                return_value=({20: 701}, [src_media_latest], [src_asset])
            ),
        ),
        patch(
            "src.galleries.repository.promotion_repository.lock_media_stack_root",
            new=AsyncMock(),
        ),
    ):
        res = await svc.promote_items(
            PromoteItemsDto(
                items=[BulkCopyItemDto(id=20, type="folder")],
                source_workspace_id=10,
                target_workspace_id=3,
            ),
            user,
        )

    assert res.promoted_count == 2
    assert res.created_count == 2
    assert [i.source_type for i in res.promoted_items] == [
        "media_item",
        "source_asset",
    ]
    assert all(i.target_folder_id == 701 for i in res.promoted_items)
    asset_created = db.add.call_args_list[1].args[0]
    assert asset_created.scope == AssetScopeEnum.PRIVATE.value
    assert asset_created.promoted_from_source_asset_id == 40
    lock_stmts = [
        call.args[0]
        for call in db.execute.call_args_list
        if "source_assets" in str(call.args[0]).lower()
        and "FOR UPDATE" in str(call.args[0])
    ]
    assert len(lock_stmts) == 1
    assert lock_stmts[0].get_execution_options().get("include_deleted") is True


def test_can_update_promoted_respects_workspace_manager_parity(user):
    private_ws = WorkspaceModel(
        id=3,
        name="Team",
        owner_id=1,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.EDITOR,
    )
    assert can_update_promoted(private_ws, user, 5) is True
    assert can_update_promoted(private_ws, user, 99) is False

    ws_admin_user = UserModel(
        id=5, email="me@example.com", name="Me", roles=[UserRoleEnum.USER]
    )
    private_admin_ws = private_ws.model_copy(
        update={"current_user_role": WorkspaceRoleEnum.ADMIN}
    )
    assert can_update_promoted(private_admin_ws, ws_admin_user, 99) is True

    public_ws = WorkspaceModel(
        id=1, name="Public", owner_id=1, scope=WorkspaceScopeEnum.PUBLIC
    )
    sys_admin = UserModel(
        id=8, email="adm@example.com", name="Adm", roles=[UserRoleEnum.ADMIN]
    )
    assert can_update_promoted(public_ws, user, 99) is False
    assert can_update_promoted(public_ws, sys_admin, 99) is True


@pytest.mark.anyio
async def test_clone_folder_structure_filters_by_source_workspace_id(user):
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    cte_res = MagicMock()
    cte_res.fetchall.return_value = [
        SimpleNamespace(
            id=20, name="Drafts", color="#fff", parent_id=None, depth=0
        )
    ]
    media_res = MagicMock()
    media_res.scalars.return_value.all.return_value = []
    asset_res = MagicMock()
    asset_res.scalars.return_value.all.return_value = []
    db.execute.side_effect = [cte_res, media_res, asset_res]

    def _assign_id(obj):
        obj.id = 801

    db.add.side_effect = _assign_id
    folder_repo = AsyncMock()
    folder_repo.get_existing_folder_names = AsyncMock(return_value=set())
    repo = PromotionRepository(db, folder_repo)

    id_map, _m, _a = await repo.clone_folder_structure(
        20,
        "Drafts",
        source_workspace_id=10,
        target_workspace_id=3,
        target_parent_folder_id=None,
        current_user=user,
    )
    assert id_map == {20: 801}


@pytest.mark.anyio
async def test_promote_fails_closed_on_missing_status_and_dedupes_nested_batches(
    user,
):
    svc, db, ws_auth, _ws_svc, folder_repo = _build_service()
    personal_ws = WorkspaceModel(
        id=10,
        name="My Workspace",
        owner_id=5,
        scope=WorkspaceScopeEnum.PERSONAL,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    target_ws = WorkspaceModel(
        id=3,
        name="Team",
        owner_id=5,
        scope=WorkspaceScopeEnum.PRIVATE,
        current_user_role=WorkspaceRoleEnum.OWNER,
    )
    ws_auth.authorize = AsyncMock(return_value=personal_ws)
    ws_auth.authorize_write = AsyncMock(return_value=target_ws)

    no_status_media = MediaItem(
        id=106,
        workspace_id=10,
        user_id=5,
        user_email="me@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_FAST.value,
        aspect_ratio="1:1",
    )
    with patch.object(
        svc.promo_repo,
        "get_source_media",
        new=AsyncMock(return_value=no_status_media),
    ):
        with pytest.raises(HTTPException) as exc_status:
            await svc.promote_items(
                PromoteItemsDto(
                    items=[BulkCopyItemDto(id=106, type="media_item")],
                    source_workspace_id=10,
                    target_workspace_id=3,
                ),
                user,
            )
    assert exc_status.value.status_code == 400

    folder_repo.get_descendant_ids = AsyncMock(
        side_effect=lambda fid: [20, 21] if fid == 20 else [21]
    )
    folder_repo.get_folder_by_id = AsyncMock(
        return_value=SimpleNamespace(id=20, workspace_id=10, name="Parent")
    )
    next_id = 800

    def _assign(obj):
        nonlocal next_id
        next_id += 1
        obj.id = next_id

    db.add = MagicMock(side_effect=_assign)
    src_m = MediaItem(
        id=105,
        workspace_id=10,
        folder_id=21,
        user_id=5,
        user_email="me@example.com",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_FAST.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
    )
    with (
        patch.object(
            svc.promo_repo,
            "clone_folder_structure",
            new=AsyncMock(return_value=({20: 700, 21: 701}, [src_m], [])),
        ) as clone_mock,
        patch(
            "src.galleries.repository.promotion_repository.lock_media_stack_root",
            new=AsyncMock(),
        ),
    ):
        dedup_res = await svc.promote_items(
            PromoteItemsDto(
                items=[
                    BulkCopyItemDto(id=21, type="folder"),
                    BulkCopyItemDto(id=20, type="folder"),
                    BulkCopyItemDto(id=20, type="folder"),
                ],
                source_workspace_id=10,
                target_workspace_id=3,
            ),
            user,
        )
    clone_mock.assert_awaited_once()
    assert dedup_res.promoted_count == 1
