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
"""Real-Postgres integration tests for revision stacks and loop pinning."""

import asyncio
from collections.abc import Iterator
import contextlib
import datetime
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_dto import GenerationModelEnum, MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.folders.repository.folder_repository import FolderRepository
from src.folders.schema.folder_model import Folder
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.gallery_service import GalleryService
from src.galleries.repository.unified_gallery_repository import (
    UnifiedGalleryRepository,
)
from src.galleries.revision_lineage import resolve_revision_lineage
from src.galleries.revision_service import RevisionService
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.tags.repository.tags_repository import TagsRepository
from src.tags.schema.tags_model import Tag, media_item_tags
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
from tests.postgres_harness import (
    drop_throwaway_db,
    in_worker_thread,
    make_nullpool_session_factory,
    recreate_throwaway_db,
    run_alembic_upgrade,
)

THROWAWAY_DB = "creative_studio_revision_stacks_test"
DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


@pytest.fixture(name="pg_db", scope="module")
def fixture_pg_db() -> Iterator[None]:
    """Creates and migrates an ephemeral Postgres DB for revision tests."""
    in_worker_thread(asyncio.run, recreate_throwaway_db(THROWAWAY_DB))
    try:
        run_alembic_upgrade(THROWAWAY_DB, "head")
        yield
    finally:
        with contextlib.suppress(DB_ERRORS):
            in_worker_thread(asyncio.run, drop_throwaway_db(THROWAWAY_DB))


def _user_model(user_row: User) -> UserModel:
    return UserModel(
        id=user_row.id,
        email=user_row.email,
        name=user_row.name,
        picture=user_row.picture,
        roles=[UserRoleEnum.USER],
    )


def _media_row(
    *,
    workspace_id: int,
    user: User,
    folder_id: int | None = None,
    revision_root_id: int | None = None,
    revision_parent_id: int | None = None,
    revision_number: int = 1,
    status: JobStatusEnum = JobStatusEnum.COMPLETED,
    mime_type: MimeTypeEnum = MimeTypeEnum.IMAGE_PNG,
    prompt: str = "test prompt",
    created_at: datetime.datetime | None = None,
) -> MediaItem:
    return MediaItem(
        workspace_id=workspace_id,
        folder_id=folder_id,
        revision_root_id=revision_root_id,
        revision_parent_id=revision_parent_id,
        revision_number=revision_number,
        user_email=user.email,
        user_id=user.id,
        mime_type=mime_type.value,
        model=GenerationModelEnum.IMAGEN_3_001.value,
        aspect_ratio="1:1",
        status=status.value,
        prompt=prompt,
        original_prompt=prompt,
        gcs_uris=(
            ["gs://bucket/media.png"]
            if status == JobStatusEnum.COMPLETED
            else []
        ),
        thumbnail_uris=(
            ["gs://bucket/thumb.png"]
            if status == JobStatusEnum.COMPLETED
            else []
        ),
        created_at=created_at
        or datetime.datetime(2026, 3, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )


def _build_revision_service(session: AsyncSession) -> RevisionService:
    iam_signer = MagicMock()
    iam_signer.generate_presigned_url_async = AsyncMock(
        side_effect=lambda uri: f"https://signed/{uri}"
    )
    ws_repo = WorkspaceRepository(session)
    ws_auth = WorkspaceAuth(workspace_repo=ws_repo)
    media_repo = MediaRepository(session)
    gallery_service = GalleryService(
        media_repo=media_repo,
        source_asset_repo=SourceAssetRepository(session),
        unified_gallery_repo=UnifiedGalleryRepository(session),
        user_repo=UserRepository(session),
        workspace_repo=ws_repo,
        iam_signer_credentials=iam_signer,
        workspace_auth=ws_auth,
        imagen_service=MagicMock(),
        gcs_service=MagicMock(),
        tags_repo=TagsRepository(session),
        folder_repo=FolderRepository(session),
        db=session,
    )
    return RevisionService(
        db=session,
        media_repo=media_repo,
        workspace_auth=ws_auth,
        gallery_service=gallery_service,
    )


@pytest.mark.anyio
async def test_postgres_concurrent_revision_numbering_and_colleague_remix(
    pg_db,
):
    _ = pg_db
    engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
    try:
        async with session_factory() as s:
            alice = User(
                email="alice@rev.test",
                name="Alice",
                picture="https://pic/alice",
                roles=[UserRoleEnum.USER.value],
            )
            bob = User(
                email="bob@rev.test",
                name="Bob",
                picture="https://pic/bob",
                roles=[UserRoleEnum.USER.value],
            )
            s.add_all([alice, bob])
            await s.flush()

            alice_ws = Workspace(
                name="Alice Personal",
                owner_id=alice.id,
                scope=WorkspaceScopeEnum.PERSONAL.value,
            )
            bob_ws = Workspace(
                name="Bob Personal",
                owner_id=bob.id,
                scope=WorkspaceScopeEnum.PERSONAL.value,
            )
            team_ws = Workspace(
                name="Team Shared",
                owner_id=alice.id,
                scope=WorkspaceScopeEnum.PRIVATE.value,
            )
            s.add_all([alice_ws, bob_ws, team_ws])
            await s.flush()

            root_folder = Folder(
                workspace_id=alice_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="Campaign",
            )
            s.add(root_folder)
            await s.flush()

            v1 = _media_row(
                workspace_id=alice_ws.id,
                user=alice,
                folder_id=root_folder.id,
                revision_number=1,
            )
            colleague_shared = _media_row(
                workspace_id=team_ws.id,
                user=alice,
                revision_number=1,
            )
            s.add_all([v1, colleague_shared])
            await s.commit()

        # Two concurrent iterations under Alice's personal stack lock to v2 & v3
        alice_dto = _user_model(alice)
        locked_v2 = asyncio.Event()

        async def _worker_tx(delay: float, wait_for_tx1: bool) -> int:
            async with session_factory() as ws_sess:
                if wait_for_tx1:
                    await locked_v2.wait()
                lineage = await resolve_revision_lineage(
                    ws_sess,
                    alice_dto,
                    output_workspace_id=alice_ws.id,
                    explicit_parent_id=v1.id,
                )
                if not wait_for_tx1:
                    locked_v2.set()
                    await asyncio.sleep(delay)
                assert lineage.revision_root_id == v1.id
                assert lineage.inherited_folder_id == root_folder.id
                take = _media_row(
                    workspace_id=alice_ws.id,
                    user=alice,
                    folder_id=lineage.inherited_folder_id,
                    revision_root_id=lineage.revision_root_id,
                    revision_parent_id=lineage.revision_parent_id,
                    revision_number=lineage.revision_number,
                )
                ws_sess.add(take)
                await ws_sess.commit()
                return lineage.revision_number

        rev_a, rev_b = await asyncio.gather(
            _worker_tx(0.15, False),
            _worker_tx(0.0, True),
        )
        assert sorted([rev_a, rev_b]) == [2, 3]

        async with session_factory() as s:
            # Bob iterating Alice's shared item starts a brand-new stack
            bob_dto = _user_model(bob)
            bob_lineage = await resolve_revision_lineage(
                s,
                bob_dto,
                output_workspace_id=bob_ws.id,
                explicit_parent_id=colleague_shared.id,
            )
            assert bob_lineage.revision_root_id is None
            assert bob_lineage.revision_parent_id is None
            assert bob_lineage.revision_number == 1
            assert bob_lineage.inherited_folder_id is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_collapse_delete_rollback_folder_move_and_pinning(
    pg_db,
):
    _ = pg_db
    engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
    now = datetime.datetime(2026, 3, 2, 12, 0, tzinfo=datetime.timezone.utc)
    try:
        async with session_factory() as s:
            alice = User(
                email="alice2@rev.test",
                name="Alice Two",
                picture="https://pic/a2",
                roles=[UserRoleEnum.USER.value],
            )
            outsider = User(
                email="outsider@rev.test",
                name="Outsider",
                roles=[UserRoleEnum.USER.value],
            )
            s.add_all([alice, outsider])
            await s.flush()

            personal_ws = Workspace(
                name="Alice Personal 2",
                owner_id=alice.id,
                scope=WorkspaceScopeEnum.PERSONAL.value,
            )
            shared_open = Workspace(
                name="Design Accessible",
                owner_id=outsider.id,
                scope=WorkspaceScopeEnum.PRIVATE.value,
            )
            s.add_all([personal_ws, shared_open])
            await s.flush()

            s.add(
                WorkspaceMemberAssociation(
                    workspace_id=shared_open.id,
                    user_id=alice.id,
                    role=WorkspaceRoleEnum.EDITOR.value,
                )
            )
            folder_a = Folder(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="Folder A",
            )
            folder_b = Folder(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="Folder B",
            )
            tag = Tag(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                name="approved",
                color="#00aa55",
            )
            s.add_all([folder_a, folder_b, tag])
            await s.flush()

            v1 = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=folder_a.id,
                revision_number=1,
                created_at=now,
            )
            s.add(v1)
            await s.flush()

            v2 = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=folder_a.id,
                revision_root_id=v1.id,
                revision_parent_id=v1.id,
                revision_number=2,
                created_at=now + datetime.timedelta(minutes=1),
            )
            v3_processing = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=folder_a.id,
                revision_root_id=v1.id,
                revision_parent_id=v2.id,
                revision_number=3,
                status=JobStatusEnum.PROCESSING,
                created_at=now + datetime.timedelta(minutes=2),
            )
            shared_item_1 = _media_row(
                workspace_id=shared_open.id,
                user=alice,
                revision_number=1,
            )
            shared_item_2 = _media_row(
                workspace_id=shared_open.id,
                user=outsider,
                revision_number=1,
            )
            s.add_all([v2, v3_processing, shared_item_1, shared_item_2])
            await s.flush()

            await s.execute(
                media_item_tags.insert().values(
                    media_item_id=v1.id, tag_id=tag.id
                )
            )
            await s.commit()

        alice_dto = _user_model(alice)
        async with session_factory() as s:
            repo = UnifiedGalleryRepository(s)
            folder_repo = FolderRepository(s)

            # 1. Gallery collapses v1/v2 to v2 (revisionCount=2 completed)
            # while keeping v3_processing visible alongside the completed cover.
            res = await repo.query(
                GallerySearchDto(workspace_id=personal_ws.id, limit=20),
                requesting_user_id=alice.id,
            )
            assert [
                (r.id, r.metadata.get("revisionCount"), r.is_latest_revision)
                for r in res.data
            ] == [
                (v3_processing.id, 2, True),
                (v2.id, 2, True),
            ]
            # Filtering explicitly on status=COMPLETED collapses to latest completed take (v2)
            completed_only = await repo.query(
                GallerySearchDto(
                    workspace_id=personal_ws.id,
                    status=JobStatusEnum.COMPLETED,
                    limit=20,
                ),
                requesting_user_id=alice.id,
            )
            assert [
                (r.id, r.metadata.get("revisionCount"), r.is_latest_revision)
                for r in completed_only.data
            ] == [(v2.id, 2, True)]

            # Shared workspace keeps all items uncollapsed
            shared_res = await repo.query(
                GallerySearchDto(workspace_id=shared_open.id, limit=20),
                requesting_user_id=alice.id,
            )
            assert {r.id for r in shared_res.data} == {
                shared_item_1.id,
                shared_item_2.id,
            }

            # 2. Folder loop picks latest completed take (v2),
            # while explicit linked workflow pins keep resolving v1 AND v2
            loop_rows, loop_total = await repo.list_folder_loop_items(
                workspace_id=personal_ws.id,
                folder_id=folder_a.id,
                mime_type_prefix="image",
                limit=50,
            )
            assert loop_total == 1
            assert loop_rows == [("media_item", v2.id)]

            linked = await repo.filter_linked_loop_items(
                workspace_id=personal_ws.id,
                media_item_ids=[v1.id, v2.id, v3_processing.id],
                source_asset_ids=[],
                mime_type_prefix="image",
            )
            assert linked == {("media_item", v1.id), ("media_item", v2.id)}

            ws_map = await repo.lookup_linked_loop_item_workspaces(
                media_item_ids=[v1.id],
                source_asset_ids=[],
                mime_type_prefix="image",
            )
            assert ws_map == {("media_item", v1.id): personal_ws.id}

            # 3. Folder count and list_by_parent deduplicate stacks cleanly
            cnt_a, _ = await folder_repo.get_folder_counts(folder_a.id)
            assert cnt_a == 1
            parent_folders = await folder_repo.list_by_parent(personal_ws.id)
            by_id = {f.id: f for f in parent_folders}
            assert by_id[folder_a.id].item_count == 1

            # 4. RevisionService returns ordered takes for PERSONAL workspace only
            rev_service = _build_revision_service(s)
            history = await rev_service.get_revisions(v2.id, alice_dto)
            assert history.root_id == v1.id
            assert history.revision_count == 3
            assert [t.id for t in history.takes] == [
                v1.id,
                v2.id,
                v3_processing.id,
            ]
            assert [t.name for t in history.takes[0].tags] == ["approved"]
            assert history.takes[0].user_picture == "https://pic/a2"

            shared_history = await rev_service.get_revisions(
                shared_item_1.id, alice_dto
            )
            assert [t.id for t in shared_history.takes] == [shared_item_1.id]

            # 5. Moving one item in personal workspace moves the entire stack together
            moved = await folder_repo.move_media_items(
                [v2.id],
                workspace_id=personal_ws.id,
                destination_folder_id=folder_b.id,
            )
            assert moved == 3
            folders_res = await s.execute(
                select(MediaItem.id, MediaItem.folder_id).where(
                    MediaItem.id.in_([v1.id, v2.id, v3_processing.id])
                )
            )
            assert all(fid == folder_b.id for _, fid in folders_res.all())

            # 6. Completing v3 collapses to v3; deleting v3 & v2 rolls cover back to v1;
            # soft-deleting root v1 keeps v2 grouped under root v1.id -> next is v4.
            v3_db = await s.get(MediaItem, v3_processing.id)
            v3_db.status = JobStatusEnum.COMPLETED.value
            v3_db.gcs_uris = ["gs://bucket/v3.png"]
            await s.commit()

            completed_res = await repo.query(
                GallerySearchDto(workspace_id=personal_ws.id, limit=20),
                requesting_user_id=alice.id,
            )
            assert [
                (r.id, r.metadata.get("revisionCount"), r.is_latest_revision)
                for r in completed_res.data
            ] == [(v3_processing.id, 3, True)]

            v3_db.deleted_at = now + datetime.timedelta(minutes=4)
            v2_db = await s.get(MediaItem, v2.id)
            v2_db.deleted_at = now + datetime.timedelta(minutes=5)
            await s.commit()

            rolled = await repo.query(
                GallerySearchDto(workspace_id=personal_ws.id, limit=20),
                requesting_user_id=alice.id,
            )
            assert [
                (r.id, r.metadata.get("revisionCount"), r.is_latest_revision)
                for r in rolled.data
            ] == [(v1.id, 1, True)]

            v1_db = await s.get(MediaItem, v1.id)
            v1_db.deleted_at = now + datetime.timedelta(minutes=6)
            v2_db.deleted_at = None
            await s.commit()

            next_after_root_del = await resolve_revision_lineage(
                s,
                alice_dto,
                output_workspace_id=personal_ws.id,
                explicit_parent_id=v2.id,
            )
            assert next_after_root_del.revision_root_id == v1.id
            assert next_after_root_del.revision_number == 4

            # 7. Same-workspace folder copy & merge_folders(is_copy=True)
            # collapse completed stacks to latest take and skip incomplete rows.
            src_folder = Folder(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="StackCopySource",
            )
            dst_folder = Folder(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="StackCopyMergeDst",
            )
            s.add_all([src_folder, dst_folder])
            await s.flush()

            c_v1 = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=src_folder.id,
                prompt="copy-v1",
                created_at=now + datetime.timedelta(minutes=10),
            )
            s.add(c_v1)
            await s.flush()
            c_v2 = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=src_folder.id,
                prompt="copy-v2-latest",
                revision_root_id=c_v1.id,
                revision_parent_id=c_v1.id,
                revision_number=2,
                created_at=now + datetime.timedelta(minutes=11),
            )
            c_v3_proc = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=src_folder.id,
                prompt="copy-v3-processing",
                revision_root_id=c_v1.id,
                revision_parent_id=c_v2.id,
                revision_number=3,
                status=JobStatusEnum.PROCESSING,
                created_at=now + datetime.timedelta(minutes=12),
            )
            s.add_all([c_v2, c_v3_proc])
            await s.flush()
            await s.execute(
                media_item_tags.insert().values(
                    media_item_id=c_v2.id, tag_id=tag.id
                )
            )
            await s.commit()

            copy_res = await folder_repo.copy_folder_to_workspace(
                folder_id=src_folder.id,
                target_workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
            )
            assert copy_res["media_copied"] == 1
            copied_folder = next(
                f
                for f in await folder_repo.list_by_parent(personal_ws.id)
                if f.id
                not in (folder_a.id, folder_b.id, src_folder.id, dst_folder.id)
            )
            assert copied_folder.item_count == 1
            copied_rows = (
                (
                    await s.execute(
                        select(MediaItem).where(
                            MediaItem.folder_id == copied_folder.id,
                            MediaItem.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(copied_rows) == 1
            assert copied_rows[0].prompt == "copy-v2-latest"
            assert copied_rows[0].revision_root_id is None
            assert copied_rows[0].revision_parent_id is None
            assert copied_rows[0].revision_number == 1
            copied_tag_rows = (
                (
                    await s.execute(
                        select(media_item_tags.c.tag_id).where(
                            media_item_tags.c.media_item_id == copied_rows[0].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert copied_tag_rows == [tag.id]

            merge_res = await folder_repo.merge_folders(
                source_folder_id=src_folder.id,
                target_folder_id=dst_folder.id,
                target_workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                is_copy=True,
            )
            assert merge_res["media_copied"] == 1
            merged_rows = (
                (
                    await s.execute(
                        select(MediaItem).where(
                            MediaItem.folder_id == dst_folder.id,
                            MediaItem.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [(r.prompt, r.revision_number) for r in merged_rows] == [
                ("copy-v2-latest", 1)
            ]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_cross_folder_iteration_and_shared_move_colocation(
    pg_db,
):
    _ = pg_db
    from src.galleries.revision_lineage import (
        RevisionLineage,
        effective_revision_folder,
    )

    engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
    now = datetime.datetime(2026, 3, 3, 12, 0, tzinfo=datetime.timezone.utc)
    try:
        async with session_factory() as s:
            alice = User(
                email="alice_cf@rev.test",
                name="Alice CF",
                picture="https://pic/cf",
                roles=[UserRoleEnum.USER.value],
            )
            s.add(alice)
            await s.flush()

            personal_ws = Workspace(
                name="Alice CF Personal",
                owner_id=alice.id,
                scope=WorkspaceScopeEnum.PERSONAL.value,
            )
            shared_ws = Workspace(
                name="Team CF Shared",
                owner_id=alice.id,
                scope=WorkspaceScopeEnum.PRIVATE.value,
            )
            s.add_all([personal_ws, shared_ws])
            await s.flush()

            folder_a = Folder(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="CF Folder A",
            )
            folder_b = Folder(
                workspace_id=personal_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="CF Folder B",
            )
            s_folder_a = Folder(
                workspace_id=shared_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="Shared Folder A",
            )
            s_folder_b = Folder(
                workspace_id=shared_ws.id,
                user_id=alice.id,
                user_email=alice.email,
                name="Shared Folder B",
            )
            s.add_all([folder_a, folder_b, s_folder_a, s_folder_b])
            await s.flush()

            v1 = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=folder_a.id,
                prompt="cf-v1",
                created_at=now,
            )
            s.add(v1)
            await s.flush()

            # Processing take in Folder A must not inflate completed count
            v1_proc = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=folder_a.id,
                prompt="cf-v1-proc",
                revision_root_id=v1.id,
                revision_parent_id=v1.id,
                revision_number=2,
                status=JobStatusEnum.PROCESSING,
                created_at=now + datetime.timedelta(minutes=1),
            )
            s.add(v1_proc)

            # Shared workspace stack co-locates on move_media_items
            sh_v1 = _media_row(
                workspace_id=shared_ws.id,
                user=alice,
                folder_id=s_folder_a.id,
                prompt="shared-v1",
                created_at=now,
            )
            s.add(sh_v1)
            await s.flush()
            sh_v2 = _media_row(
                workspace_id=shared_ws.id,
                user=alice,
                folder_id=s_folder_a.id,
                prompt="shared-v2",
                revision_root_id=sh_v1.id,
                revision_parent_id=sh_v1.id,
                revision_number=2,
                created_at=now + datetime.timedelta(minutes=1),
            )
            s.add(sh_v2)
            await s.commit()

            alice_dto = _user_model(alice)
            cross_lineage = await resolve_revision_lineage(
                s,
                alice_dto,
                output_workspace_id=personal_ws.id,
                explicit_parent_id=v1.id,
                requested_folder_id=folder_b.id,
                resolved_folder_id=folder_b.id,
            )
            assert cross_lineage == RevisionLineage(None, None, 1, None)
            target_folder_id = effective_revision_folder(
                folder_b.id, folder_b.id, cross_lineage
            )
            assert target_folder_id == folder_b.id

            v2_fresh = _media_row(
                workspace_id=personal_ws.id,
                user=alice,
                folder_id=target_folder_id,
                prompt="cf-v2-fresh",
                revision_root_id=cross_lineage.revision_root_id,
                revision_parent_id=cross_lineage.revision_parent_id,
                revision_number=cross_lineage.revision_number,
                created_at=now + datetime.timedelta(minutes=2),
            )
            s.add(v2_fresh)
            await s.commit()

            repo = UnifiedGalleryRepository(s)
            folder_repo = FolderRepository(s)

            res_a = await repo.query(
                GallerySearchDto(
                    workspace_id=personal_ws.id,
                    folder_id=folder_a.id,
                    status=JobStatusEnum.COMPLETED,
                    limit=20,
                ),
                requesting_user_id=alice.id,
            )
            assert [r.id for r in res_a.data] == [v1.id]

            res_b = await repo.query(
                GallerySearchDto(
                    workspace_id=personal_ws.id, folder_id=folder_b.id, limit=20
                ),
                requesting_user_id=alice.id,
            )
            assert [r.id for r in res_b.data] == [v2_fresh.id]

            loop_a, total_a = await repo.list_folder_loop_items(
                workspace_id=personal_ws.id,
                folder_id=folder_a.id,
                mime_type_prefix="image",
                limit=50,
            )
            assert (loop_a, total_a) == ([("media_item", v1.id)], 1)

            loop_b, total_b = await repo.list_folder_loop_items(
                workspace_id=personal_ws.id,
                folder_id=folder_b.id,
                mime_type_prefix="image",
                limit=50,
            )
            assert (loop_b, total_b) == ([("media_item", v2_fresh.id)], 1)

            assert await folder_repo.get_folder_counts(folder_a.id) == (1, 0)
            assert await folder_repo.get_folder_counts(folder_b.id) == (1, 0)

            moved_shared = await folder_repo.move_media_items(
                [sh_v2.id],
                workspace_id=shared_ws.id,
                destination_folder_id=s_folder_b.id,
            )
            assert moved_shared == 2
            sh_res = await s.execute(
                select(MediaItem.folder_id).where(
                    MediaItem.id.in_([sh_v1.id, sh_v2.id])
                )
            )
            assert all(fid == s_folder_b.id for (fid,) in sh_res.all())
    finally:
        await engine.dispose()
