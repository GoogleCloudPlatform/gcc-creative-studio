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
"""Real PostgreSQL unscoped personal-workspace privacy tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
import contextlib
from typing import Any, TypeVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.repository.admin_repository import AdminRepository
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.repository.unified_gallery_repository import (
    UnifiedGalleryRepository,
)
from src.source_assets.dto.source_asset_search_dto import SourceAssetSearchDto
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.tags.repository.tags_repository import TagsRepository
from src.users.user_model import UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)
from tests.factories import (
    make_media_item,
    make_source_asset,
    make_tag,
    make_user,
    make_workspace,
    make_workspace_member,
)
from tests.postgres_harness import (
    drop_throwaway_db,
    in_worker_thread,
    make_nullpool_session_factory,
    recreate_throwaway_db,
    run_alembic_upgrade,
)

THROWAWAY_DB = "creative_studio_ws_privacy_test"
T = TypeVar("T")


async def _seed_privacy_fixture() -> dict[str, int]:
    engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
    try:
        async with session_factory() as session:
            admin = make_user(
                email="global-admin@example.com",
                roles=[UserRoleEnum.ADMIN, UserRoleEnum.USER],
                name="Global Admin",
            )
            alice = make_user(
                email="alice-private@example.com",
                roles=[UserRoleEnum.USER],
                name="Alice",
            )
            session.add_all([admin, alice])
            await session.flush()

            shared_ws = make_workspace(
                owner_id=admin.id,
                name="Shared Public WS",
                scope=WorkspaceScopeEnum.PUBLIC,
            )
            admin_personal = make_workspace(
                owner_id=admin.id,
                name="Admin Personal WS",
                scope=WorkspaceScopeEnum.PERSONAL,
            )
            alice_personal = make_workspace(
                owner_id=alice.id,
                name="Alice Personal WS",
                scope=WorkspaceScopeEnum.PERSONAL,
            )
            session.add_all([shared_ws, admin_personal, alice_personal])
            await session.flush()

            session.add_all(
                [
                    make_workspace_member(
                        workspace_id=shared_ws.id,
                        user_id=admin.id,
                        role=WorkspaceRoleEnum.OWNER,
                    ),
                    make_workspace_member(
                        workspace_id=admin_personal.id,
                        user_id=admin.id,
                        role=WorkspaceRoleEnum.OWNER,
                    ),
                    make_workspace_member(
                        workspace_id=alice_personal.id,
                        user_id=alice.id,
                        role=WorkspaceRoleEnum.OWNER,
                    ),
                ]
            )

            shared_media = make_media_item(
                workspace_id=shared_ws.id,
                user_id=admin.id,
                user_email=admin.email,
                prompt="shared prompt",
            )
            admin_media = make_media_item(
                workspace_id=admin_personal.id,
                user_id=admin.id,
                user_email=admin.email,
                prompt="admin personal prompt",
            )
            alice_media = make_media_item(
                workspace_id=alice_personal.id,
                user_id=alice.id,
                user_email=alice.email,
                prompt="alice personal secret prompt",
            )
            shared_asset = make_source_asset(
                workspace_id=shared_ws.id,
                user_id=admin.id,
                original_filename="shared.png",
            )
            admin_asset = make_source_asset(
                workspace_id=admin_personal.id,
                user_id=admin.id,
                original_filename="admin-secret.png",
            )
            alice_asset = make_source_asset(
                workspace_id=alice_personal.id,
                user_id=alice.id,
                original_filename="alice-secret.png",
            )
            shared_tag = make_tag(
                workspace_id=shared_ws.id,
                user_id=admin.id,
                name="shared-tag",
            )
            admin_tag = make_tag(
                workspace_id=admin_personal.id,
                user_id=admin.id,
                name="admin-personal-tag",
            )
            alice_tag = make_tag(
                workspace_id=alice_personal.id,
                user_id=alice.id,
                name="alice-personal-tag",
            )
            session.add_all(
                [
                    shared_media,
                    admin_media,
                    alice_media,
                    shared_asset,
                    admin_asset,
                    alice_asset,
                    shared_tag,
                    admin_tag,
                    alice_tag,
                ]
            )
            await session.commit()
            return {
                "admin_id": admin.id,
                "alice_id": alice.id,
                "shared_ws_id": shared_ws.id,
                "admin_personal_id": admin_personal.id,
                "alice_personal_id": alice_personal.id,
                "shared_media_id": shared_media.id,
                "admin_media_id": admin_media.id,
                "alice_media_id": alice_media.id,
                "shared_asset_id": shared_asset.id,
                "admin_asset_id": admin_asset.id,
                "alice_asset_id": alice_asset.id,
                "shared_tag_id": shared_tag.id,
                "admin_tag_id": admin_tag.id,
                "alice_tag_id": alice_tag.id,
            }
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def privacy_dataset() -> Iterator[dict[str, int]]:
    in_worker_thread(lambda: asyncio.run(recreate_throwaway_db(THROWAWAY_DB)))
    try:
        run_alembic_upgrade(THROWAWAY_DB, "head")
        yield in_worker_thread(lambda: asyncio.run(_seed_privacy_fixture()))
    finally:
        with contextlib.suppress(Exception):
            in_worker_thread(
                lambda: asyncio.run(drop_throwaway_db(THROWAWAY_DB))
            )


def _run_with_session(
    fn: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    async def _runner() -> T:
        engine, session_factory = make_nullpool_session_factory(THROWAWAY_DB)
        try:
            async with session_factory() as session:
                return await fn(session)
        finally:
            await engine.dispose()

    return in_worker_thread(lambda: asyncio.run(_runner()))


def test_unscoped_admin_excludes_foreign_personal_gallery_items(
    privacy_dataset: dict[str, int],
) -> None:
    ds = privacy_dataset

    async def _check(
        session: AsyncSession,
    ) -> tuple[set[tuple[str, int]], set[tuple[str, int]]]:
        repo = UnifiedGalleryRepository(db=session)
        search = GallerySearchDto(workspace_id=None, limit=50, offset=0)
        as_admin = await repo.query(search, requesting_user_id=ds["admin_id"])
        unscoped = await repo.query(search, requesting_user_id=None)
        admin_keys = {(i.item_type, i.id) for i in as_admin.data}
        unscoped_keys = {(i.item_type, i.id) for i in unscoped.data}
        return admin_keys, unscoped_keys

    admin_keys, unscoped_keys = _run_with_session(_check)

    assert ("media_item", ds["alice_media_id"]) not in admin_keys
    assert ("source_asset", ds["alice_asset_id"]) not in admin_keys
    assert ("media_item", ds["shared_media_id"]) in admin_keys
    assert ("source_asset", ds["shared_asset_id"]) in admin_keys
    assert ("media_item", ds["admin_media_id"]) in admin_keys
    assert ("source_asset", ds["admin_asset_id"]) in admin_keys

    assert ("media_item", ds["alice_media_id"]) not in unscoped_keys
    assert ("source_asset", ds["alice_asset_id"]) not in unscoped_keys
    assert ("media_item", ds["admin_media_id"]) not in unscoped_keys
    assert ("source_asset", ds["admin_asset_id"]) not in unscoped_keys
    assert ("media_item", ds["shared_media_id"]) in unscoped_keys


def test_unscoped_admin_excludes_foreign_personal_source_assets(
    privacy_dataset: dict[str, int],
) -> None:
    ds = privacy_dataset

    async def _check(session: AsyncSession) -> tuple[set[int], set[int]]:
        repo = SourceAssetRepository(db=session)
        search = SourceAssetSearchDto(workspace_id=None, limit=50, offset=0)
        as_admin = await repo.query(search, requesting_user_id=ds["admin_id"])
        unscoped = await repo.query(search, requesting_user_id=None)
        return (
            {a.id for a in as_admin.data},
            {a.id for a in unscoped.data},
        )

    admin_ids, unscoped_ids = _run_with_session(_check)

    assert ds["alice_asset_id"] not in admin_ids
    assert ds["shared_asset_id"] in admin_ids
    assert ds["admin_asset_id"] in admin_ids

    assert ds["alice_asset_id"] not in unscoped_ids
    assert ds["admin_asset_id"] not in unscoped_ids
    assert ds["shared_asset_id"] in unscoped_ids


def test_unscoped_admin_excludes_foreign_personal_tags(
    privacy_dataset: dict[str, int],
) -> None:
    ds = privacy_dataset

    async def _check(session: AsyncSession) -> tuple[set[int], set[int]]:
        repo = TagsRepository(db=session)
        as_admin = await repo.list_global_tags(
            requesting_user_id=ds["admin_id"], limit=50
        )
        unscoped = await repo.list_global_tags(
            requesting_user_id=None, limit=50
        )
        return (
            {t.id for t in as_admin.data},
            {t.id for t in unscoped.data},
        )

    admin_ids, unscoped_ids = _run_with_session(_check)

    assert ds["alice_tag_id"] not in admin_ids
    assert ds["shared_tag_id"] in admin_ids
    assert ds["admin_tag_id"] in admin_ids

    assert ds["alice_tag_id"] not in unscoped_ids
    assert ds["admin_tag_id"] not in unscoped_ids
    assert ds["shared_tag_id"] in unscoped_ids


def test_admin_overview_and_workspace_stats_exclude_personal_workspaces(
    privacy_dataset: dict[str, int],
) -> None:
    ds = privacy_dataset

    async def _check(session: AsyncSession) -> tuple[Any, list[Any]]:
        repo = AdminRepository(db=session)
        overview = await repo.get_overview_stats()
        ws_stats = await repo.get_workspace_stats()
        return overview, ws_stats

    overview, ws_stats = _run_with_session(_check)

    assert overview.total_workspaces == 1
    ws_ids = {s.workspace_id for s in ws_stats}
    assert ds["shared_ws_id"] in ws_ids
    assert ds["alice_personal_id"] not in ws_ids
    assert ds["admin_personal_id"] not in ws_ids
