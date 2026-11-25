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
"""Revision stack lineage resolution, folder inheritance, and copy helpers."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.common.schema.media_item_model import (
    JobStatusEnum,
    MediaItem,
    SourceMediaItemLink,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    SourceAsset,
)
from src.users.user_model import UserModel

COPIED_MEDIA_EXCLUDE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "deleted_by",
        "workspace_id",
        "folder_id",
        "user_id",
        "user_email",
        "revision_root_id",
        "revision_parent_id",
        "revision_number",
        "promoted_from_media_item_id",
        "promoted_from_root_id",
    }
)

COPIED_ASSET_EXCLUDE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "deleted_by",
        "workspace_id",
        "folder_id",
        "user_id",
        "promoted_from_source_asset_id",
    }
)


@dataclass(frozen=True, slots=True)
class RevisionLineage:
    """Lineage metadata assigned to a newly created MediaItem placeholder."""

    revision_root_id: int | None
    revision_parent_id: int | None
    revision_number: int
    inherited_folder_id: int | None


def stack_root_expr(
    media_cls: type[MediaItem] = MediaItem,
) -> ColumnElement[int]:
    """SQL expression for a MediaItem stack root."""
    return func.coalesce(media_cls.revision_root_id, media_cls.id)


def latest_completed_take_predicate(
    media_cls: type[MediaItem] = MediaItem,
    alias_name: str = "mi_newer",
) -> ColumnElement[bool]:
    """SQL NOT EXISTS predicate matching the latest completed take per stack."""
    newer_media = aliased(media_cls, name=alias_name)
    return ~exists(
        select(1).where(
            newer_media.workspace_id == media_cls.workspace_id,
            stack_root_expr(newer_media) == stack_root_expr(media_cls),
            newer_media.deleted_at.is_(None),
            newer_media.status == JobStatusEnum.COMPLETED.value,
            or_(
                newer_media.revision_number > media_cls.revision_number,
                and_(
                    newer_media.revision_number == media_cls.revision_number,
                    newer_media.id > media_cls.id,
                ),
            ),
        )
    )


async def lock_media_stack_root(db: AsyncSession, root_id: int) -> None:
    """Locks stack root row (even soft-deleted) to serialize concurrent writes."""
    await db.execute(
        select(MediaItem.id)
        .where(MediaItem.id == root_id)
        .with_for_update()
        .execution_options(include_deleted=True)
    )


def _extract_primary_media_id(
    explicit_parent_id: int | None,
    source_media_items: Sequence[SourceMediaItemLink] | None,
) -> int | None:
    if explicit_parent_id is not None:
        return explicit_parent_id
    if not source_media_items:
        return None
    return source_media_items[0].media_item_id


async def _resolve_promoted_personal_origin(
    db: AsyncSession,
    parent: MediaItem,
    output_workspace_id: int,
) -> tuple[int, int | None] | None:
    """Folds edits on one's own promoted copy back into its personal stack."""
    origin_root_id = parent.promoted_from_root_id
    if origin_root_id is None:
        return None
    root_res = await db.execute(
        select(
            MediaItem.id,
            MediaItem.workspace_id,
            MediaItem.user_id,
            MediaItem.deleted_at,
        )
        .where(MediaItem.id == origin_root_id)
        .execution_options(include_deleted=True)
    )
    root_row = root_res.first()
    if (
        root_row is None
        or root_row.workspace_id != output_workspace_id
        or root_row.user_id != parent.user_id
    ):
        return None
    origin_parent_id = parent.promoted_from_media_item_id
    if origin_parent_id is not None:
        src_res = await db.execute(
            select(MediaItem.id)
            .where(
                MediaItem.id == origin_parent_id,
                MediaItem.workspace_id == output_workspace_id,
                MediaItem.deleted_at.is_(None),
            )
            .limit(1)
        )
        if src_res.scalar_one_or_none() is None:
            origin_parent_id = None
    if origin_parent_id is None and root_row.deleted_at is None:
        origin_parent_id = origin_root_id
    if origin_parent_id is None:
        active_res = await db.execute(
            select(MediaItem.id)
            .where(
                MediaItem.workspace_id == output_workspace_id,
                MediaItem.deleted_at.is_(None),
                stack_root_expr(MediaItem) == origin_root_id,
            )
            .limit(1)
        )
        if active_res.scalar_one_or_none() is None:
            return None
    return origin_root_id, origin_parent_id


async def resolve_revision_lineage(
    db: AsyncSession,
    user: UserModel,
    output_workspace_id: int,
    explicit_parent_id: int | None = None,
    source_media_items: Sequence[SourceMediaItemLink] | None = None,
    requested_folder_id: int | None = None,
    resolved_folder_id: int | None = None,
) -> RevisionLineage:
    """Computes revision stack lineage and inherited folder for an iteration.

    Iterations referencing an item outside ``output_workspace_id`` start a fresh
    stack (``revision_number=1``) unless iterating on the caller's own promoted
    copy, which folds back into its personal stack under a ``FOR UPDATE`` lock.
    """
    del user
    candidate_id = _extract_primary_media_id(
        explicit_parent_id, source_media_items
    )
    if candidate_id is None:
        return RevisionLineage(None, None, 1, None)

    parent_res = await db.execute(
        select(MediaItem).where(
            MediaItem.id == candidate_id, MediaItem.deleted_at.is_(None)
        )
    )
    parent = parent_res.scalar_one_or_none()
    if parent is None:
        return RevisionLineage(None, None, 1, None)

    if parent.workspace_id == output_workspace_id:
        root_id = parent.revision_root_id or parent.id
        parent_id: int | None = parent.id
    else:
        folded = await _resolve_promoted_personal_origin(
            db, parent, output_workspace_id
        )
        if folded is None:
            return RevisionLineage(None, None, 1, None)
        root_id, parent_id = folded

    await lock_media_stack_root(db, root_id)
    root_expr = stack_root_expr(MediaItem)
    max_res = await db.execute(
        select(func.coalesce(func.max(MediaItem.revision_number), 1))
        .where(
            MediaItem.workspace_id == output_workspace_id,
            root_expr == root_id,
        )
        .execution_options(include_deleted=True)
    )
    next_rev = int(max_res.scalar_one() or 1) + 1

    folder_res = await db.execute(
        select(MediaItem.folder_id)
        .where(
            MediaItem.workspace_id == output_workspace_id,
            root_expr == root_id,
            MediaItem.deleted_at.is_(None),
        )
        .order_by(MediaItem.revision_number.desc(), MediaItem.id.desc())
        .limit(1)
    )
    inherited_folder_id = folder_res.scalar_one_or_none()
    if (
        requested_folder_id is not None
        and resolved_folder_id != inherited_folder_id
    ):
        return RevisionLineage(None, None, 1, None)
    return RevisionLineage(
        revision_root_id=root_id,
        revision_parent_id=parent_id,
        revision_number=next_rev,
        inherited_folder_id=inherited_folder_id,
    )


def effective_revision_folder(
    requested_folder_id: int | None,
    resolved_folder_id: int | None,
    lineage: RevisionLineage,
) -> int | None:
    """Keeps existing stack folder when iterating without explicit override."""
    if requested_folder_id is None and lineage.revision_root_id is not None:
        return lineage.inherited_folder_id
    return resolved_folder_id


async def sanitize_copied_media_kwargs(
    db: AsyncSession,
    kwargs: dict[str, Any],
    target_workspace_id: int,
) -> None:
    """Strips source references outside ``target_workspace_id`` (or ``SYSTEM``)."""
    raw_assets: list[dict[str, Any]] | None = kwargs.get("source_assets")
    if raw_assets:
        asset_ids = [
            int(aid)
            for entry in raw_assets
            if (aid := entry.get("asset_id")) is not None
        ]
        allowed_assets: set[int] = set()
        if asset_ids:
            res = await db.execute(
                select(SourceAsset.id).where(
                    SourceAsset.id.in_(asset_ids),
                    SourceAsset.deleted_at.is_(None),
                    or_(
                        SourceAsset.workspace_id == target_workspace_id,
                        SourceAsset.scope == AssetScopeEnum.SYSTEM.value,
                    ),
                )
            )
            allowed_assets = {row[0] for row in res.fetchall()}
        kwargs["source_assets"] = [
            entry
            for entry in raw_assets
            if entry.get("asset_id") in allowed_assets
        ]

    raw_media: list[dict[str, Any]] | None = kwargs.get("source_media_items")
    if raw_media:
        media_ids = [
            int(mid)
            for entry in raw_media
            if (mid := entry.get("media_item_id")) is not None
        ]
        allowed_media: set[int] = set()
        if media_ids:
            res = await db.execute(
                select(MediaItem.id).where(
                    MediaItem.id.in_(media_ids),
                    MediaItem.deleted_at.is_(None),
                    MediaItem.workspace_id == target_workspace_id,
                )
            )
            allowed_media = {row[0] for row in res.fetchall()}
        kwargs["source_media_items"] = [
            entry
            for entry in raw_media
            if entry.get("media_item_id") in allowed_media
        ]
