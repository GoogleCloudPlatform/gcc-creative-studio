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
"""Resolves private-first output workspaces and validates input references."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.schema.media_item_model import MediaItem
from src.folders.output_folder import (
    OUTPUT_FOLDER_NOT_FOUND_DETAIL,
    resolve_output_folder_id,
)
from src.folders.repository.folder_repository import FolderRepository
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    SourceAsset,
)
from src.users.user_model import UserModel
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import WorkspaceScopeEnum
from src.workspaces.workspace_auth_guard import WorkspaceAuth

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GenerationContext:
    """Resolved output destination and Brand Guideline context for a job."""

    output_workspace_id: int
    brand_workspace_id: int
    resolved_folder_id: int | None


async def ensure_folder_in_workspace(
    db: AsyncSession, workspace_id: int, folder_id: int | None
) -> int | None:
    """Validates that ``folder_id`` (if set) exists in ``workspace_id``."""
    if folder_id is None:
        return None
    folder = await FolderRepository(db).get_folder_by_id(folder_id)
    if folder is None or folder.workspace_id != workspace_id:
        raise HTTPException(422, detail=OUTPUT_FOLDER_NOT_FOUND_DETAIL)
    return folder_id


async def _resolve_requested_folder_for_personal(
    db: AsyncSession,
    ws_repo: WorkspaceRepository,
    ws_auth: WorkspaceAuth,
    user: UserModel,
    req_ws_id: int,
    out_ws_id: int,
    req_folder_id: int | None,
) -> int | None:
    if req_folder_id is None:
        return None
    folder = await FolderRepository(db).get_folder_by_id(req_folder_id)
    if folder is None:
        raise HTTPException(422, detail=OUTPUT_FOLDER_NOT_FOUND_DETAIL)
    if folder.workspace_id == out_ws_id:
        return req_folder_id
    if folder.workspace_id != req_ws_id:
        folder_ws = await ws_repo.get_by_id(folder.workspace_id)
        if folder_ws is None or folder_ws.scope == WorkspaceScopeEnum.PERSONAL:
            raise HTTPException(422, detail=OUTPUT_FOLDER_NOT_FOUND_DETAIL)
        try:
            await ws_auth.authorize(folder.workspace_id, user)
        except HTTPException as exc:
            raise HTTPException(
                422, detail=OUTPUT_FOLDER_NOT_FOUND_DETAIL
            ) from exc
    logger.info(
        "Ignoring shared folder_id=%s for personal output ws=%s",
        req_folder_id,
        out_ws_id,
    )
    return None


async def resolve_generation_context(
    db: AsyncSession,
    requested_workspace_id: int,
    user: UserModel,
    requested_folder_id: int | None = None,
    context_workspace_id: int | None = None,
    *,
    agent_folder_resolver: (
        Callable[[AsyncSession, int, UserModel], Awaitable[int | None]] | None
    ) = None,
    resolve_folder: bool = True,
) -> GenerationContext:
    """Routes AI outputs to the caller's personal workspace while preserving Brand Guidelines context."""
    brand_ws_id = context_workspace_id or requested_workspace_id
    ws_repo = WorkspaceRepository(db)
    ws_auth = WorkspaceAuth(ws_repo)
    workspace = await ws_auth.authorize(requested_workspace_id, user)

    if workspace.scope == WorkspaceScopeEnum.PERSONAL:
        output_ws_id, effective_folder_id = (
            requested_workspace_id,
            requested_folder_id,
        )
    else:
        personal_ws = await ws_repo.ensure_personal_workspace(
            user, commit_on_create=False
        )
        if personal_ws.id is None:
            raise HTTPException(500, detail="Personal workspace missing.")
        output_ws_id = personal_ws.id
        effective_folder_id = await _resolve_requested_folder_for_personal(
            db,
            ws_repo,
            ws_auth,
            user,
            requested_workspace_id,
            output_ws_id,
            requested_folder_id,
        )

    if context_workspace_id and context_workspace_id != requested_workspace_id:
        await ws_auth.authorize(context_workspace_id, user)

    if not resolve_folder:
        resolved_folder_id = None
    elif agent_folder_resolver is not None and effective_folder_id is None:
        resolved_folder_id = await agent_folder_resolver(db, output_ws_id, user)
    else:
        resolved_folder_id = await resolve_output_folder_id(
            db, output_ws_id, user, effective_folder_id
        )

    return GenerationContext(output_ws_id, brand_ws_id, resolved_folder_id)


async def ensure_can_reference_inputs(
    db: AsyncSession,
    user: UserModel,
    media_item_ids: Iterable[int] = (),
    source_asset_ids: Iterable[int] = (),
) -> None:
    """Verifies read access for referenced MediaItems and non-SYSTEM SourceAssets."""
    media_ids = sorted({m for m in media_item_ids if m and m > 0})
    asset_ids = sorted({a for a in source_asset_ids if a and a > 0})
    if not media_ids and not asset_ids:
        return

    ws_auth, authorized = WorkspaceAuth(WorkspaceRepository(db)), set()

    async def _auth(ws_id: int | None) -> None:
        if ws_id is not None and ws_id not in authorized:
            await ws_auth.authorize(ws_id, user)
            authorized.add(ws_id)

    if media_ids:
        q = select(MediaItem.workspace_id).where(
            MediaItem.id.in_(media_ids), MediaItem.deleted_at.is_(None)
        )
        for (ws_id,) in (await db.execute(q)).all():
            await _auth(ws_id)
    if asset_ids:
        q = select(SourceAsset.workspace_id, SourceAsset.scope).where(
            SourceAsset.id.in_(asset_ids), SourceAsset.deleted_at.is_(None)
        )
        for ws_id, scope in (await db.execute(q)).all():
            if scope != AssetScopeEnum.SYSTEM:
                await _auth(ws_id)
