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
"""Tests verifying strongly typed ORM factories and Postgres persistence."""

from __future__ import annotations

import pytest

from src.common.base_dto import AspectRatioEnum, MimeTypeEnum
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.folders.schema.folder_model import Folder
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    SourceAsset,
)
from src.tags.schema.tags_model import Tag
from src.users.user_model import User, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceRoleEnum,
)
from tests.factories import (
    make_folder,
    make_media_item,
    make_source_asset,
    make_tag,
    make_user,
    make_workspace,
    make_workspace_member,
)
from tests.postgres_harness import (
    drop_throwaway_db,
    make_nullpool_session_factory,
    recreate_throwaway_db,
    run_alembic_upgrade,
)

FACTORY_TEST_DB = "creative_studio_factories_smoke_test"


def test_factories_return_typed_orm_instances() -> None:
    """Every factory produces its real ORM type with non-None defaults."""
    user = make_user(roles=[UserRoleEnum.ADMIN])
    ws = make_workspace(owner_id=1)
    member = make_workspace_member(role=WorkspaceRoleEnum.EDITOR)
    folder = make_folder()
    asset = make_source_asset(mime_type=MimeTypeEnum.IMAGE_JPEG)
    media = make_media_item(aspect_ratio=AspectRatioEnum.RATIO_16_9)
    tag = make_tag(color="#112233")

    assert isinstance(user, User) and user.roles == ["admin"]
    assert make_user(roles=[]).roles == []
    assert isinstance(ws, Workspace) and ws.scope == "private"
    assert isinstance(member, WorkspaceMemberAssociation)
    assert isinstance(folder, Folder) and folder.name
    assert isinstance(asset, SourceAsset)
    assert asset.scope == AssetScopeEnum.PRIVATE
    assert isinstance(media, MediaItem)
    assert media.status == JobStatusEnum.COMPLETED
    assert isinstance(tag, Tag) and tag.color == "#112233"


@pytest.mark.anyio
async def test_factories_persist_cleanly_in_postgres() -> None:
    """Factories insert cleanly against real Alembic Postgres constraints."""
    await recreate_throwaway_db(FACTORY_TEST_DB)
    try:
        run_alembic_upgrade(FACTORY_TEST_DB, "head")
        engine, session_factory = make_nullpool_session_factory(FACTORY_TEST_DB)
        try:
            async with session_factory() as session:
                user = make_user()
                session.add(user)
                await session.flush()

                ws = make_workspace(owner_id=user.id)
                session.add(ws)
                await session.flush()

                member = make_workspace_member(
                    workspace_id=ws.id,
                    user_id=user.id,
                    role=WorkspaceRoleEnum.OWNER,
                )
                folder = make_folder(
                    workspace_id=ws.id, user_id=user.id, user_email=user.email
                )
                session.add_all([member, folder])
                await session.flush()

                asset = make_source_asset(
                    workspace_id=ws.id, user_id=user.id, folder_id=folder.id
                )
                media = make_media_item(
                    workspace_id=ws.id,
                    user_id=user.id,
                    user_email=user.email,
                    folder_id=folder.id,
                )
                tag = make_tag(workspace_id=ws.id, user_id=user.id)
                session.add_all([asset, media, tag])
                await session.commit()

                assert asset.id > 0 and media.id > 0 and tag.id > 0
        finally:
            await engine.dispose()
    finally:
        await drop_throwaway_db(FACTORY_TEST_DB)
