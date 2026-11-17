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
"""Real-Postgres integration tests for cross-workspace promotion and stats."""

import asyncio
from collections.abc import Iterator
import contextlib
import datetime
from unittest.mock import AsyncMock, MagicMock

import asyncpg
from fastapi import HTTPException
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.repository.admin_repository import AdminRepository
from src.common.base_dto import GenerationModelEnum, MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.folders.repository.folder_repository import FolderRepository
from src.folders.schema.folder_model import Folder
from src.galleries.dto.bulk_copy_dto import BulkCopyItemDto
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.promote_dto import (
    PromoteItemsDto,
    PromoteTargetsRequestDto,
)
from src.galleries.gallery_service import GalleryService
from src.galleries.promotion_service import MAX_FOLDER_DEPTH, PromotionService
from src.galleries.repository.unified_gallery_repository import (
    UnifiedGalleryRepository,
)
from src.galleries.revision_lineage import (
    RevisionLineage,
    resolve_revision_lineage,
)
from src.galleries.revision_service import RevisionService
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
)
from src.tags.repository.tags_repository import TagsRepository
from src.users.repository.user_repository import UserRepository
from src.users.user_model import User, UserModel, UserRoleEnum
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import WorkspaceAuth
from src.workspaces.workspace_service import WorkspaceService
from tests.postgres_harness import (
    drop_throwaway_db,
    in_worker_thread,
    make_nullpool_session_factory,
    recreate_throwaway_db,
    run_alembic_upgrade,
)

THROWAWAY_DB = "creative_studio_promotion_test"
DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


@pytest.fixture(name="pg_db", scope="module")
def fixture_pg_db() -> Iterator[None]:
    """Creates and migrates an ephemeral Postgres DB for promotion tests."""
    in_worker_thread(asyncio.run, recreate_throwaway_db(THROWAWAY_DB))
    try:
        run_alembic_upgrade(THROWAWAY_DB, "head")
        yield
    finally:
        with contextlib.suppress(DB_ERRORS):
            in_worker_thread(asyncio.run, drop_throwaway_db(THROWAWAY_DB))


def _user_model(row: User) -> UserModel:
    return UserModel(
        id=row.id,
        email=row.email,
        name=row.name,
        roles=[UserRoleEnum.USER],
    )


def _build_services(
    session: AsyncSession,
) -> tuple[PromotionService, RevisionService]:
    iam_signer = MagicMock()
    iam_signer.generate_presigned_url_async = AsyncMock(
        side_effect=lambda uri: f"https://signed/{uri}"
    )
    ws_repo = WorkspaceRepository(session)
    ws_auth = WorkspaceAuth(workspace_repo=ws_repo)
    user_repo = UserRepository(session)
    folder_repo = FolderRepository(session)
    ws_svc = WorkspaceService(
        workspace_repo=ws_repo,
        user_repo=user_repo,
        email_service=MagicMock(),
    )
    media_repo = MediaRepository(session)
    gallery_svc = GalleryService(
        media_repo=media_repo,
        source_asset_repo=SourceAssetRepository(session),
        unified_gallery_repo=UnifiedGalleryRepository(session),
        user_repo=user_repo,
        workspace_repo=ws_repo,
        iam_signer_credentials=iam_signer,
        workspace_auth=ws_auth,
        imagen_service=MagicMock(),
        gcs_service=MagicMock(),
        tags_repo=TagsRepository(session),
        folder_repo=folder_repo,
        db=session,
    )
    promo_svc = PromotionService(
        db=session,
        workspace_auth=ws_auth,
        workspace_service=ws_svc,
        folder_repo=folder_repo,
    )
    rev_svc = RevisionService(
        db=session,
        media_repo=media_repo,
        workspace_auth=ws_auth,
        gallery_service=gallery_svc,
    )
    return promo_svc, rev_svc


async def _seed_promotion_fixture(
    session: AsyncSession,
) -> dict[str, int | User]:
    creator_row = User(
        email="creator-promo@example.com",
        name="Creator Promo",
        roles=[UserRoleEnum.USER.value],
    )
    viewer_row = User(
        email="viewer-promo@example.com",
        name="Viewer Promo",
        roles=[UserRoleEnum.USER.value],
    )
    session.add_all([creator_row, viewer_row])
    await session.flush()

    personal_ws = Workspace(
        name="Creator Personal",
        owner_id=creator_row.id,
        scope=WorkspaceScopeEnum.PERSONAL.value,
    )
    viewer_personal_ws = Workspace(
        name="Viewer Personal",
        owner_id=viewer_row.id,
        scope=WorkspaceScopeEnum.PERSONAL.value,
    )
    team_ws = Workspace(
        name="Team Brand",
        owner_id=creator_row.id,
        scope=WorkspaceScopeEnum.PRIVATE.value,
    )
    viewer_only_ws = Workspace(
        name="Viewer Only Team",
        owner_id=viewer_row.id,
        scope=WorkspaceScopeEnum.PRIVATE.value,
    )
    session.add_all([personal_ws, viewer_personal_ws, team_ws, viewer_only_ws])
    await session.flush()

    session.add_all(
        [
            WorkspaceMemberAssociation(
                workspace_id=personal_ws.id,
                user_id=creator_row.id,
                role=WorkspaceRoleEnum.OWNER.value,
            ),
            WorkspaceMemberAssociation(
                workspace_id=viewer_personal_ws.id,
                user_id=viewer_row.id,
                role=WorkspaceRoleEnum.OWNER.value,
            ),
            WorkspaceMemberAssociation(
                workspace_id=team_ws.id,
                user_id=creator_row.id,
                role=WorkspaceRoleEnum.OWNER.value,
            ),
            WorkspaceMemberAssociation(
                workspace_id=team_ws.id,
                user_id=viewer_row.id,
                role=WorkspaceRoleEnum.VIEWER.value,
            ),
            WorkspaceMemberAssociation(
                workspace_id=viewer_only_ws.id,
                user_id=creator_row.id,
                role=WorkspaceRoleEnum.VIEWER.value,
            ),
        ]
    )
    dest_folder = Folder(
        workspace_id=team_ws.id,
        user_id=creator_row.id,
        user_email=creator_row.email,
        name="Approved Cuts",
    )
    src_folder = Folder(
        workspace_id=personal_ws.id,
        user_id=creator_row.id,
        user_email=creator_row.email,
        name="Exploration Set",
    )
    session.add_all([dest_folder, src_folder])
    await session.flush()

    priv_asset = SourceAsset(
        workspace_id=personal_ws.id,
        user_id=creator_row.id,
        gcs_uri="gs://bucket/ref.png",
        original_filename="ref.png",
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        aspect_ratio="1:1",
        file_hash="hash_promo_1",
        scope=AssetScopeEnum.PRIVATE.value,
        asset_type=AssetTypeEnum.GENERIC_IMAGE.value,
        folder_id=src_folder.id,
    )
    session.add(priv_asset)
    await session.flush()

    t0 = datetime.datetime(2026, 4, 1, 10, 0, tzinfo=datetime.timezone.utc)
    v1 = MediaItem(
        workspace_id=personal_ws.id,
        folder_id=src_folder.id,
        user_email=creator_row.email,
        user_id=creator_row.id,
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_001.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        prompt="take 1",
        gcs_uris=["gs://bucket/v1.png"],
        revision_number=1,
        created_at=t0,
    )
    session.add(v1)
    await session.flush()
    v2 = MediaItem(
        workspace_id=personal_ws.id,
        folder_id=src_folder.id,
        revision_root_id=v1.id,
        revision_parent_id=v1.id,
        revision_number=2,
        user_email=creator_row.email,
        user_id=creator_row.id,
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_001.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        prompt="take 2",
        gcs_uris=["gs://bucket/v2.png"],
        source_assets=[{"asset_id": priv_asset.id, "role": "input"}],
        created_at=t0 + datetime.timedelta(minutes=1),
    )
    v3 = MediaItem(
        workspace_id=personal_ws.id,
        folder_id=src_folder.id,
        revision_root_id=v1.id,
        revision_parent_id=v2.id,
        revision_number=3,
        user_email=creator_row.email,
        user_id=creator_row.id,
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_001.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        prompt="take 3",
        gcs_uris=["gs://bucket/v3.png"],
        created_at=t0 + datetime.timedelta(minutes=2),
    )
    v4 = MediaItem(
        workspace_id=personal_ws.id,
        folder_id=src_folder.id,
        revision_root_id=v1.id,
        revision_parent_id=v3.id,
        revision_number=4,
        user_email=creator_row.email,
        user_id=creator_row.id,
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_001.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        prompt="take 4",
        gcs_uris=["gs://bucket/v4.png"],
        created_at=t0 + datetime.timedelta(minutes=3),
    )
    viewer_item = MediaItem(
        workspace_id=viewer_personal_ws.id,
        user_email=viewer_row.email,
        user_id=viewer_row.id,
        mime_type=MimeTypeEnum.IMAGE_PNG.value,
        model=GenerationModelEnum.IMAGEN_3_001.value,
        aspect_ratio="1:1",
        status=JobStatusEnum.COMPLETED.value,
        prompt="viewer creation",
        gcs_uris=["gs://bucket/viewer.png"],
        revision_number=1,
        created_at=t0 + datetime.timedelta(minutes=4),
    )
    session.add_all([v2, v3, v4, viewer_item])
    await session.commit()
    return {
        "creator_row": creator_row,
        "viewer_row": viewer_row,
        "personal_ws_id": personal_ws.id,
        "viewer_personal_ws_id": viewer_personal_ws.id,
        "team_ws_id": team_ws.id,
        "viewer_only_ws_id": viewer_only_ws.id,
        "dest_folder_id": dest_folder.id,
        "src_folder_id": src_folder.id,
        "priv_asset_id": priv_asset.id,
        "v1_id": v1.id,
        "v2_id": v2.id,
        "v4_id": v4.id,
        "viewer_item_id": viewer_item.id,
    }


@pytest.mark.anyio
async def test_postgres_promotion_lineage_folder_depth_and_rollback(pg_db):
    _ = pg_db

    async def _run() -> None:
        engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
        try:
            async with session_factory() as session:
                ids = await _seed_promotion_fixture(session)
                creator_row = ids["creator_row"]
                viewer_row = ids["viewer_row"]
                assert isinstance(creator_row, User)
                assert isinstance(viewer_row, User)
                creator = _user_model(creator_row)
                viewer = _user_model(viewer_row)

                personal_ws_id = int(ids["personal_ws_id"])
                viewer_personal_ws_id = int(ids["viewer_personal_ws_id"])
                team_ws_id = int(ids["team_ws_id"])
                viewer_only_ws_id = int(ids["viewer_only_ws_id"])
                dest_folder_id = int(ids["dest_folder_id"])
                src_folder_id = int(ids["src_folder_id"])
                priv_asset_id = int(ids["priv_asset_id"])
                v1_id = int(ids["v1_id"])
                v2_id = int(ids["v2_id"])
                v4_id = int(ids["v4_id"])
                viewer_item_id = int(ids["viewer_item_id"])

                promo_svc, rev_svc = _build_services(session)

                # 0. Non-personal source_workspace_id rejected with 400
                with pytest.raises(HTTPException) as exc_src:
                    await promo_svc.promote_items(
                        PromoteItemsDto(
                            items=[
                                BulkCopyItemDto(id=v2_id, type="media_item")
                            ],
                            source_workspace_id=team_ws_id,
                            target_workspace_id=viewer_only_ws_id,
                        ),
                        viewer,
                    )
                assert exc_src.value.status_code == 400
                with pytest.raises(HTTPException) as exc_tgt:
                    await promo_svc.get_promote_targets(
                        PromoteTargetsRequestDto(
                            source_workspace_id=team_ws_id,
                            items=[
                                BulkCopyItemDto(id=v2_id, type="media_item")
                            ],
                        ),
                        creator,
                    )
                assert exc_tgt.value.status_code == 400
                await session.rollback()

                # 1. Viewer with own personal source fails authorize_write -> 403
                with pytest.raises(HTTPException) as exc_viewer:
                    await promo_svc.promote_items(
                        PromoteItemsDto(
                            items=[
                                BulkCopyItemDto(
                                    id=viewer_item_id, type="media_item"
                                )
                            ],
                            source_workspace_id=viewer_personal_ws_id,
                            target_workspace_id=team_ws_id,
                        ),
                        viewer,
                    )
                assert exc_viewer.value.status_code == 403
                await session.rollback()

                # 2. Promote v2 + private asset into team_ws/dest_folder
                first_res = await promo_svc.promote_items(
                    PromoteItemsDto(
                        items=[
                            BulkCopyItemDto(id=v2_id, type="media_item"),
                            BulkCopyItemDto(
                                id=priv_asset_id, type="source_asset"
                            ),
                        ],
                        source_workspace_id=personal_ws_id,
                        target_workspace_id=team_ws_id,
                        target_folder_id=dest_folder_id,
                    ),
                    creator,
                )
                assert first_res.promoted_count == 2
                assert first_res.created_count == 2
                shared_media_id = first_res.promoted_items[0].target_id
                shared_asset_id = first_res.promoted_items[1].target_id

                shared_media = (
                    await session.execute(
                        select(MediaItem).where(MediaItem.id == shared_media_id)
                    )
                ).scalar_one()
                assert shared_media.revision_root_id is None
                assert shared_media.revision_number == 1
                assert shared_media.folder_id == dest_folder_id
                assert shared_media.source_assets == []
                assert shared_media.promoted_from_media_item_id == v2_id
                assert shared_media.promoted_from_root_id == v1_id

                shared_asset = (
                    await session.execute(
                        select(SourceAsset).where(
                            SourceAsset.id == shared_asset_id
                        )
                    )
                ).scalar_one()
                assert shared_asset.scope == AssetScopeEnum.PRIVATE.value
                assert shared_asset.folder_id == dest_folder_id
                assert (
                    shared_asset.promoted_from_source_asset_id == priv_asset_id
                )

                # 3. Revisions strip on v4 shows accessible promotions
                history = await rev_svc.get_revisions(v4_id, creator)
                assert history.revision_count == 4
                assert len(history.promotions) == 1
                assert history.promotions[0].promoted_revision_number == 2
                assert history.promotions[0].target_item_id == shared_media_id

                # 4. Targets exclude VIEWER workspace & show v2 shared
                targets = await promo_svc.get_promote_targets(
                    PromoteTargetsRequestDto(
                        source_workspace_id=personal_ws_id,
                        items=[BulkCopyItemDto(id=v4_id, type="media_item")],
                    ),
                    creator,
                )
                assert [t.workspace_id for t in targets] == [team_ws_id]
                assert targets[0].existing_count == 1
                assert targets[0].existing_promotion is not None
                assert (
                    targets[0].existing_promotion.target_folder_id
                    == dest_folder_id
                )

                # 5. Update in place preserves dest_folder & advances origin
                upd_res = await promo_svc.promote_items(
                    PromoteItemsDto(
                        items=[BulkCopyItemDto(id=v4_id, type="media_item")],
                        source_workspace_id=personal_ws_id,
                        target_workspace_id=team_ws_id,
                        mode="update_or_create",
                    ),
                    creator,
                )
                assert upd_res.updated_count == 1
                assert upd_res.promoted_items[0].target_id == shared_media_id
                await session.refresh(shared_media)
                assert shared_media.folder_id == dest_folder_id
                assert shared_media.promoted_from_media_item_id == v4_id
                assert shared_media.gcs_uris == ["gs://bucket/v4.png"]

                # 6. Creator iterating on promoted copy folds back to personal
                folded = await resolve_revision_lineage(
                    session,
                    creator,
                    output_workspace_id=personal_ws_id,
                    explicit_parent_id=shared_media_id,
                )
                assert folded == RevisionLineage(
                    revision_root_id=v1_id,
                    revision_parent_id=v4_id,
                    revision_number=5,
                    inherited_folder_id=src_folder_id,
                )
                colleague_remix = await resolve_revision_lineage(
                    session,
                    viewer,
                    output_workspace_id=viewer_personal_ws_id,
                    explicit_parent_id=shared_media_id,
                )
                assert colleague_remix == RevisionLineage(None, None, 1, None)

                # 7. create_new publishes a separate shared item
                new_res = await promo_svc.promote_items(
                    PromoteItemsDto(
                        items=[BulkCopyItemDto(id=v4_id, type="media_item")],
                        source_workspace_id=personal_ws_id,
                        target_workspace_id=team_ws_id,
                        mode="create_new",
                    ),
                    creator,
                )
                assert new_res.created_count == 1
                second_shared_id = new_res.promoted_items[0].target_id
                assert second_shared_id != shared_media_id

                # 7b. Moving promoted copy to colleague's PERSONAL workspace
                # hides it from get_revisions even for global ADMIN users.
                moved_row = (
                    await session.execute(
                        select(MediaItem).where(
                            MediaItem.id == second_shared_id
                        )
                    )
                ).scalar_one()
                moved_row.workspace_id = viewer_personal_ws_id
                await session.commit()

                admin_creator = creator.model_copy(
                    update={"roles": [UserRoleEnum.USER, UserRoleEnum.ADMIN]}
                )
                admin_history = await rev_svc.get_revisions(
                    v4_id, admin_creator
                )
                assert [
                    p.target_workspace_id for p in admin_history.promotions
                ] == [team_ws_id]
                assert [p.target_item_id for p in admin_history.promotions] == [
                    shared_media_id
                ]

                # 8. Soft-deleting promoted copies preserves private v1..v4
                t_del = datetime.datetime(
                    2026, 4, 1, 12, 0, tzinfo=datetime.timezone.utc
                )
                for pid in (shared_media_id, second_shared_id):
                    row = (
                        await session.execute(
                            select(MediaItem).where(MediaItem.id == pid)
                        )
                    ).scalar_one()
                    row.deleted_at = t_del
                await session.commit()

                history_after = await rev_svc.get_revisions(v4_id, creator)
                assert history_after.revision_count == 4
                assert history_after.promotions == []

                # 9. Folder promote picks only latest completed take via SQL
                folder_targets = await promo_svc.get_promote_targets(
                    PromoteTargetsRequestDto(
                        source_workspace_id=personal_ws_id,
                        items=[
                            BulkCopyItemDto(id=src_folder_id, type="folder")
                        ],
                    ),
                    creator,
                )
                assert len(folder_targets) == 1
                assert folder_targets[0].existing_count == 0
                assert folder_targets[0].new_count == 2

                folder_res = await promo_svc.promote_items(
                    PromoteItemsDto(
                        items=[
                            BulkCopyItemDto(id=src_folder_id, type="folder")
                        ],
                        source_workspace_id=personal_ws_id,
                        target_workspace_id=team_ws_id,
                    ),
                    creator,
                )
                assert folder_res.created_count == 2
                assert folder_res.updated_count == 0

                # 10. MAX_FOLDER_DEPTH > 20 check rejects deep folder promote
                parent_id = dest_folder_id
                for idx in range(MAX_FOLDER_DEPTH):
                    node = Folder(
                        workspace_id=team_ws_id,
                        parent_id=parent_id,
                        user_id=creator_row.id,
                        user_email=creator_row.email,
                        name=f"Level {idx}",
                    )
                    session.add(node)
                    await session.flush()
                    parent_id = node.id
                await session.commit()

                with pytest.raises(HTTPException) as exc_depth:
                    await promo_svc.promote_items(
                        PromoteItemsDto(
                            items=[
                                BulkCopyItemDto(id=src_folder_id, type="folder")
                            ],
                            source_workspace_id=personal_ws_id,
                            target_workspace_id=team_ws_id,
                            target_folder_id=parent_id,
                        ),
                        creator,
                    )
                assert exc_depth.value.status_code == 400
                await session.rollback()

                # 11. AdminRepository excludes promoted clones from totals
                admin_repo = AdminRepository(session)
                overview = await admin_repo.get_overview_stats()
                assert overview.images_generated == 5
                assert overview.user_uploaded_media == 1

            # 12. Mid-batch failure rolls back cleanly
            async with session_factory() as rb_session:
                v_proc = MediaItem(
                    workspace_id=personal_ws_id,
                    user_email=creator.email,
                    user_id=creator.id,
                    mime_type=MimeTypeEnum.IMAGE_PNG.value,
                    model=GenerationModelEnum.IMAGEN_3_001.value,
                    aspect_ratio="1:1",
                    status=JobStatusEnum.PROCESSING.value,
                    prompt="processing take",
                    gcs_uris=[],
                    revision_number=1,
                )
                rb_session.add(v_proc)
                await rb_session.commit()
                v_proc_id = v_proc.id

                before_cnt = len(
                    (
                        await rb_session.execute(
                            select(MediaItem.id).where(
                                MediaItem.workspace_id == team_ws_id
                            )
                        )
                    ).all()
                )
                rb_promo, _ = _build_services(rb_session)
                with pytest.raises(HTTPException) as exc_mid:
                    await rb_promo.promote_items(
                        PromoteItemsDto(
                            items=[
                                BulkCopyItemDto(id=v4_id, type="media_item"),
                                BulkCopyItemDto(
                                    id=v_proc_id, type="media_item"
                                ),
                            ],
                            source_workspace_id=personal_ws_id,
                            target_workspace_id=team_ws_id,
                            mode="create_new",
                        ),
                        creator,
                    )
                assert exc_mid.value.status_code == 400
                await rb_session.rollback()

            async with session_factory() as verify_session:
                after_cnt = len(
                    (
                        await verify_session.execute(
                            select(MediaItem.id).where(
                                MediaItem.workspace_id == team_ws_id
                            )
                        )
                    ).all()
                )
                assert after_cnt == before_cnt
        finally:
            await engine.dispose()

    in_worker_thread(asyncio.run, _run())


@pytest.mark.anyio
async def test_postgres_get_paginated_gallery_filters_promotions_by_access(
    pg_db,
):
    """Unified gallery search hides unpermitted & personal promotion targets."""

    async def _run() -> None:
        engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
        try:
            async with session_factory() as session:
                creator_row = User(
                    email="creator-gallery-filter@example.com",
                    name="Creator Filter",
                    roles=[UserRoleEnum.USER.value],
                )
                outsider_row = User(
                    email="outsider-gallery-filter@example.com",
                    name="Outsider Filter",
                    roles=[UserRoleEnum.USER.value],
                )
                admin_row = User(
                    email="admin-gallery-filter@example.com",
                    name="Global Admin Filter",
                    roles=[UserRoleEnum.ADMIN.value],
                )
                session.add_all([creator_row, outsider_row, admin_row])
                await session.flush()

                creator = _user_model(creator_row)
                admin_user = UserModel(
                    id=admin_row.id,
                    email=admin_row.email,
                    name=admin_row.name,
                    roles=[UserRoleEnum.ADMIN],
                )

                creator_personal_ws = Workspace(
                    name="Creator Personal Filter",
                    owner_id=creator_row.id,
                    scope=WorkspaceScopeEnum.PERSONAL.value,
                )
                outsider_personal_ws = Workspace(
                    name="Outsider Personal Filter",
                    owner_id=outsider_row.id,
                    scope=WorkspaceScopeEnum.PERSONAL.value,
                )
                admin_personal_ws = Workspace(
                    name="Admin Personal Filter",
                    owner_id=admin_row.id,
                    scope=WorkspaceScopeEnum.PERSONAL.value,
                )
                secret_team_ws = Workspace(
                    name="Secret Team Filter",
                    owner_id=outsider_row.id,
                    scope=WorkspaceScopeEnum.PRIVATE.value,
                )
                public_ws = Workspace(
                    name="Public Gallery Filter",
                    owner_id=admin_row.id,
                    scope=WorkspaceScopeEnum.PUBLIC.value,
                )
                session.add_all(
                    [
                        creator_personal_ws,
                        outsider_personal_ws,
                        admin_personal_ws,
                        secret_team_ws,
                        public_ws,
                    ]
                )
                await session.flush()

                creator_src = MediaItem(
                    workspace_id=creator_personal_ws.id,
                    user_email=creator.email,
                    user_id=creator.id,
                    mime_type=MimeTypeEnum.IMAGE_PNG.value,
                    model=GenerationModelEnum.IMAGEN_3_001.value,
                    aspect_ratio="1:1",
                    status=JobStatusEnum.COMPLETED.value,
                    prompt="creator personal origin",
                    gcs_uris=["gs://bucket/creator-src.png"],
                    revision_number=1,
                )
                session.add(creator_src)
                await session.flush()

                for target_ws_id, prompt_txt in (
                    (public_ws.id, "public copy"),
                    (secret_team_ws.id, "secret team copy"),
                    (outsider_personal_ws.id, "rogue personal copy"),
                ):
                    session.add(
                        MediaItem(
                            workspace_id=target_ws_id,
                            user_email=creator.email,
                            user_id=creator.id,
                            mime_type=MimeTypeEnum.IMAGE_PNG.value,
                            model=GenerationModelEnum.IMAGEN_3_001.value,
                            aspect_ratio="1:1",
                            status=JobStatusEnum.COMPLETED.value,
                            prompt=prompt_txt,
                            gcs_uris=["gs://bucket/promo.png"],
                            revision_number=1,
                            promoted_from_media_item_id=creator_src.id,
                            promoted_from_root_id=creator_src.id,
                        )
                    )

                admin_src = MediaItem(
                    workspace_id=admin_personal_ws.id,
                    user_email=admin_user.email,
                    user_id=admin_user.id,
                    mime_type=MimeTypeEnum.IMAGE_PNG.value,
                    model=GenerationModelEnum.IMAGEN_3_001.value,
                    aspect_ratio="1:1",
                    status=JobStatusEnum.COMPLETED.value,
                    prompt="admin personal origin",
                    gcs_uris=["gs://bucket/admin-src.png"],
                    revision_number=1,
                )
                session.add(admin_src)
                await session.flush()

                for target_ws_id in (
                    secret_team_ws.id,
                    outsider_personal_ws.id,
                ):
                    session.add(
                        MediaItem(
                            workspace_id=target_ws_id,
                            user_email=admin_user.email,
                            user_id=admin_user.id,
                            mime_type=MimeTypeEnum.IMAGE_PNG.value,
                            model=GenerationModelEnum.IMAGEN_3_001.value,
                            aspect_ratio="1:1",
                            status=JobStatusEnum.COMPLETED.value,
                            prompt="admin promo",
                            gcs_uris=["gs://bucket/admin-promo.png"],
                            revision_number=1,
                            promoted_from_media_item_id=admin_src.id,
                            promoted_from_root_id=admin_src.id,
                        )
                    )
                await session.commit()

                _promo_svc, rev_svc = _build_services(session)
                res_creator = (
                    await rev_svc.gallery_service.get_paginated_gallery(
                        GallerySearchDto(
                            workspace_id=creator_personal_ws.id,
                            item_type="media_item",
                            limit=20,
                            offset=0,
                        ),
                        creator,
                    )
                )
                creator_item = next(
                    item
                    for item in res_creator.data
                    if item.id == creator_src.id
                )
                creator_target_ids = {
                    p["target_workspace_id"]
                    for p in creator_item.metadata["promotions"]
                }
                assert creator_target_ids == {public_ws.id}
                assert secret_team_ws.id not in creator_target_ids
                assert outsider_personal_ws.id not in creator_target_ids

                res_admin_all = (
                    await rev_svc.gallery_service.get_paginated_gallery(
                        GallerySearchDto(
                            item_type="media_item", limit=50, offset=0
                        ),
                        admin_user,
                    )
                )
                assert all(
                    item.id != creator_src.id for item in res_admin_all.data
                )

                res_admin_own = (
                    await rev_svc.gallery_service.get_paginated_gallery(
                        GallerySearchDto(
                            workspace_id=admin_personal_ws.id,
                            item_type="media_item",
                            limit=20,
                            offset=0,
                        ),
                        admin_user,
                    )
                )
                admin_own_item = next(
                    item
                    for item in res_admin_own.data
                    if item.id == admin_src.id
                )
                admin_target_ids = {
                    p["target_workspace_id"]
                    for p in admin_own_item.metadata["promotions"]
                }
                assert admin_target_ids == {secret_team_ws.id}
                assert outsider_personal_ws.id not in admin_target_ids
        finally:
            await engine.dispose()

    in_worker_thread(asyncio.run, _run())
