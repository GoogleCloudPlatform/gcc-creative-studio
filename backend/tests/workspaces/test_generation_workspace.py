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
"""Tests for private-first generation workspace and input-reference guards."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.source_assets.schema.source_asset_model import AssetScopeEnum
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.generation_workspace import (
    ensure_can_reference_inputs,
    ensure_folder_in_workspace,
    resolve_generation_context,
)
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)


def _user(user_id: int = 7) -> UserModel:
    return UserModel(
        id=user_id,
        email=f"u{user_id}@example.com",
        name=f"User {user_id}",
        roles=[UserRoleEnum.USER],
    )


def _workspace(
    ws_id: int, scope: WorkspaceScopeEnum, owner_id: int
) -> WorkspaceModel:
    return WorkspaceModel(
        id=ws_id,
        name=f"WS-{ws_id}",
        owner_id=owner_id,
        scope=scope,
        current_user_role=(
            WorkspaceRoleEnum.OWNER
            if scope == WorkspaceScopeEnum.PERSONAL
            else WorkspaceRoleEnum.EDITOR
        ),
    )


@pytest.mark.anyio
async def test_ensure_folder_in_workspace_validates_membership():
    db = AsyncMock(spec=AsyncSession)
    assert await ensure_folder_in_workspace(db, 10, None) is None

    with patch(
        "src.workspaces.generation_workspace.FolderRepository"
    ) as repo_cls:
        repo = repo_cls.return_value
        repo.get_folder_by_id = AsyncMock(
            return_value=SimpleNamespace(id=5, workspace_id=10)
        )
        assert await ensure_folder_in_workspace(db, 10, 5) == 5

        repo.get_folder_by_id = AsyncMock(
            return_value=SimpleNamespace(id=5, workspace_id=99)
        )
        with pytest.raises(HTTPException) as exc_foreign:
            await ensure_folder_in_workspace(db, 10, 5)
        assert exc_foreign.value.status_code == 422

        repo.get_folder_by_id = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_missing:
            await ensure_folder_in_workspace(db, 10, 5)
        assert exc_missing.value.status_code == 422


@pytest.mark.anyio
async def test_resolve_generation_context_personal_and_shared_routing():
    db = AsyncMock(spec=AsyncSession)
    user = _user(7)
    personal_ws = _workspace(42, WorkspaceScopeEnum.PERSONAL, owner_id=7)
    shared_ws = _workspace(10, WorkspaceScopeEnum.PRIVATE, owner_id=99)

    with (
        patch(
            "src.workspaces.generation_workspace.WorkspaceRepository"
        ) as repo_cls,
        patch("src.workspaces.generation_workspace.WorkspaceAuth") as auth_cls,
        patch(
            "src.workspaces.generation_workspace.FolderRepository"
        ) as folder_cls,
        patch(
            "src.workspaces.generation_workspace.resolve_output_folder_id",
            new=AsyncMock(return_value=55),
        ) as mock_resolve_folder,
    ):
        repo = repo_cls.return_value
        repo.ensure_personal_workspace = AsyncMock(return_value=personal_ws)
        auth = auth_cls.return_value
        auth.authorize = AsyncMock(return_value=personal_ws)

        ctx_personal = await resolve_generation_context(
            db, 42, user, requested_folder_id=55
        )
        assert ctx_personal.output_workspace_id == 42
        assert ctx_personal.brand_workspace_id == 42
        assert ctx_personal.resolved_folder_id == 55
        mock_resolve_folder.assert_awaited_once_with(db, 42, user, 55)

        # Generating while viewing a shared workspace routes outputs to personal workspace,
        # ignores a shared-workspace folder_id, and preserves brand_workspace_id.
        auth.authorize = AsyncMock(return_value=shared_ws)
        folder_cls.return_value.get_folder_by_id = AsyncMock(
            return_value=SimpleNamespace(id=88, workspace_id=10)
        )
        agent_resolver = AsyncMock(return_value=77)
        ctx_shared = await resolve_generation_context(
            db,
            10,
            user,
            requested_folder_id=88,
            context_workspace_id=10,
            agent_folder_resolver=agent_resolver,
        )
        assert ctx_shared.output_workspace_id == 42
        assert ctx_shared.brand_workspace_id == 10
        assert ctx_shared.resolved_folder_id == 77
        agent_resolver.assert_awaited_once_with(db, 42, user)


@pytest.mark.anyio
async def test_resolve_generation_context_rejects_foreign_personal_folder():
    db = AsyncMock(spec=AsyncSession)
    user = _user(7)
    personal_ws = _workspace(42, WorkspaceScopeEnum.PERSONAL, owner_id=7)
    shared_ws = _workspace(10, WorkspaceScopeEnum.PRIVATE, owner_id=99)
    foreign_personal = _workspace(99, WorkspaceScopeEnum.PERSONAL, owner_id=88)

    with (
        patch(
            "src.workspaces.generation_workspace.WorkspaceRepository"
        ) as repo_cls,
        patch("src.workspaces.generation_workspace.WorkspaceAuth") as auth_cls,
        patch(
            "src.workspaces.generation_workspace.FolderRepository"
        ) as folder_cls,
    ):
        repo = repo_cls.return_value
        repo.ensure_personal_workspace = AsyncMock(return_value=personal_ws)
        repo.get_by_id = AsyncMock(return_value=foreign_personal)
        auth_cls.return_value.authorize = AsyncMock(return_value=shared_ws)
        folder_cls.return_value.get_folder_by_id = AsyncMock(
            return_value=SimpleNamespace(id=300, workspace_id=99)
        )

        with pytest.raises(HTTPException) as exc:
            await resolve_generation_context(
                db, 10, user, requested_folder_id=300
            )
        assert exc.value.status_code == 422

        # Unauthorized foreign PRIVATE folder also maps uniformly to 422 (non-enumeration).
        foreign_private = _workspace(
            77, WorkspaceScopeEnum.PRIVATE, owner_id=88
        )
        repo.get_by_id = AsyncMock(return_value=foreign_private)
        folder_cls.return_value.get_folder_by_id = AsyncMock(
            return_value=SimpleNamespace(id=301, workspace_id=77)
        )
        auth_cls.return_value.authorize = AsyncMock(
            side_effect=[
                shared_ws,
                HTTPException(status_code=403, detail="Forbidden"),
            ]
        )
        with pytest.raises(HTTPException) as exc_priv:
            await resolve_generation_context(
                db, 10, user, requested_folder_id=301
            )
        assert exc_priv.value.status_code == 422


@pytest.mark.anyio
async def test_resolve_generation_context_authorizes_distinct_context_workspace():
    db = AsyncMock(spec=AsyncSession)
    user = _user(7)
    personal_ws = _workspace(42, WorkspaceScopeEnum.PERSONAL, owner_id=7)

    with (
        patch("src.workspaces.generation_workspace.WorkspaceRepository"),
        patch("src.workspaces.generation_workspace.WorkspaceAuth") as auth_cls,
    ):
        auth = auth_cls.return_value
        auth.authorize = AsyncMock(
            side_effect=[
                personal_ws,
                HTTPException(status_code=403, detail="Denied"),
            ]
        )
        with pytest.raises(HTTPException) as exc:
            await resolve_generation_context(
                db, 42, user, context_workspace_id=15, resolve_folder=False
            )
        assert exc.value.status_code == 403
        assert auth.authorize.await_count == 2


@pytest.mark.anyio
async def test_ensure_can_reference_inputs_enforces_workspace_and_system_rules():
    db = AsyncMock(spec=AsyncSession)
    user = _user(7)

    # Empty refs short-circuit without touching DB.
    await ensure_can_reference_inputs(db, user, [], [])
    db.execute.assert_not_awaited()

    media_res = MagicMock()
    media_res.all.return_value = [(10,), (10,)]
    asset_res = MagicMock()
    asset_res.all.return_value = [
        (99, AssetScopeEnum.SYSTEM.value),
        (12, AssetScopeEnum.PRIVATE.value),
    ]
    db.execute = AsyncMock(side_effect=[media_res, asset_res])

    with patch("src.workspaces.generation_workspace.WorkspaceAuth") as auth_cls:
        auth = auth_cls.return_value
        auth.authorize = AsyncMock()
        await ensure_can_reference_inputs(
            db, user, media_item_ids=[1, 2], source_asset_ids=[5, 6]
        )
        # Workspace 10 authorized once; SYSTEM workspace 99 skipped; private asset workspace 12 authorized.
        assert auth.authorize.await_args_list == [
            ((10, user), {}),
            ((12, user), {}),
        ]

        # Foreign inaccessible workspace fails closed with 403.
        media_res_2 = MagicMock()
        media_res_2.all.return_value = [(77,)]
        db.execute = AsyncMock(return_value=media_res_2)
        auth.authorize = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Forbidden")
        )
        with pytest.raises(HTTPException) as exc:
            await ensure_can_reference_inputs(db, user, media_item_ids=[9])
        assert exc.value.status_code == 403
