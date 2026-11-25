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
"""Pure mapping and ownership helpers for cross-workspace promotion."""

import copy
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from sqlalchemy import inspect as sa_inspect

from src.common.schema.media_item_model import MediaItem
from src.galleries.dto.promote_dto import PromoteTargetWorkspaceDto
from src.galleries.dto.unified_gallery_response import PromotionSummaryDto
from src.source_assets.schema.source_asset_model import SourceAsset
from src.users.user_model import UserModel
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import is_workspace_manager


class OwnedPromotionRow(Protocol):
    """Structural type for lightweight promotion match rows."""

    id: int
    workspace_id: int
    folder_id: int | None
    user_id: int | None


RowT = TypeVar("RowT", bound=OwnedPromotionRow)


def copy_column_values(
    row: MediaItem | SourceAsset, columns: list[str]
) -> dict[str, Any]:
    """Deep-copies mutable JSON/array ORM column values for cloning."""
    state = sa_inspect(row)
    copied: dict[str, Any] = {}
    for col in columns:
        val = state.attrs[col].value
        copied[col] = (
            copy.deepcopy(val) if isinstance(val, (list, dict)) else val
        )
    return copied


def can_update_promoted(
    ws: WorkspaceModel, user: UserModel, uid: int | None
) -> bool:
    """Returns True if user owns the promoted row or manages target workspace."""
    return is_workspace_manager(user, ws) or (
        uid is not None and uid == user.id
    )


def pick_updatable_match(
    rows: list[RowT], ws: WorkspaceModel, user: UserModel
) -> RowT | None:
    """Picks caller's own promoted match first, or first row if manager."""
    fallback: RowT | None = None
    for row in rows:
        if not can_update_promoted(ws, user, row.user_id):
            continue
        if row.user_id == user.id:
            return row
        if fallback is None:
            fallback = row
    return fallback


def index_updatable_matches(
    rows: list[RowT],
    ws_by_id: dict[int, WorkspaceModel],
    user: UserModel,
    key_fn: Callable[[RowT], int],
) -> dict[tuple[int, int], RowT]:
    """Groups candidate matches by ``(workspace_id, source_key)`` and filters."""
    grouped: dict[tuple[int, int], list[RowT]] = {}
    for row in rows:
        grouped.setdefault((row.workspace_id, key_fn(row)), []).append(row)
    indexed: dict[tuple[int, int], RowT] = {}
    for key, group in grouped.items():
        ws = ws_by_id.get(key[0])
        hit = pick_updatable_match(group, ws, user) if ws is not None else None
        if hit is not None:
            indexed[key] = hit
    return indexed


def to_promo_summary(
    ws: WorkspaceModel,
    m_hits: list[Any],
    a_hits: list[Any],
    rev_by_src: dict[int, int],
) -> PromotionSummaryDto | None:
    """Builds a single-item existing promotion summary for target previews."""
    assert ws.id is not None
    if m_hits:
        row = m_hits[0]
        src_mid = row.promoted_from_media_item_id
        return PromotionSummaryDto(
            target_workspace_id=ws.id,
            target_workspace_name=ws.name,
            target_item_id=row.id,
            target_folder_id=row.folder_id,
            promoted_revision_number=(
                rev_by_src.get(src_mid) if src_mid is not None else None
            ),
            promoted_from_media_item_id=src_mid,
        )
    if a_hits:
        row = a_hits[0]
        return PromotionSummaryDto(
            target_workspace_id=ws.id,
            target_workspace_name=ws.name,
            target_item_id=row.id,
            target_folder_id=row.folder_id,
        )
    return None


def to_target_dto(
    ws: WorkspaceModel,
    roots: list[int],
    a_ids: list[int],
    m_idx: dict[tuple[int, int], Any],
    a_idx: dict[tuple[int, int], Any],
    rev: dict[int, int],
    single: bool,
    total: int,
) -> PromoteTargetWorkspaceDto:
    """Converts a writable workspace into a target preview DTO with counts."""
    assert ws.id is not None
    mh = [m_idx[(ws.id, r)] for r in roots if (ws.id, r) in m_idx]
    ah = [a_idx[(ws.id, a)] for a in a_ids if (ws.id, a) in a_idx]
    existing = len(mh) + len(ah)
    role_raw = ws.current_user_role
    if isinstance(role_raw, WorkspaceRoleEnum):
        role: str | None = role_raw.value
    elif role_raw is not None:
        role = str(role_raw)
    else:
        role = None
    scope = (
        ws.scope.value
        if isinstance(ws.scope, WorkspaceScopeEnum)
        else str(ws.scope)
    )
    promo = to_promo_summary(ws, mh, ah, rev) if single else None
    return PromoteTargetWorkspaceDto(
        workspace_id=ws.id,
        workspace_name=ws.name,
        scope=scope,
        current_user_role=role,
        existing_count=existing,
        new_count=max(0, total - existing),
        existing_promotion=promo,
    )
