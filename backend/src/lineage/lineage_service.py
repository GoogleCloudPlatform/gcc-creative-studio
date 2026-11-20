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
"""Service orchestrating lineage persistence, auth, and URL enrichment."""

import asyncio
from collections.abc import Sequence
import inspect
import logging
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.media_utils import extract_youtube_video_id
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.database import get_db
from src.lineage.dto.lineage_dto import ItemLineageResponseDto, LineageNodeDto
from src.lineage.lineage_builder import ExplicitPrimarySpec, build_lineage_edges
from src.lineage.repository.lineage_repository import (
    AncestorChainRow,
    LineageRepository,
)
from src.lineage.schema.item_lineage_model import (
    ItemLineage,
    LineageItemTypeEnum,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAsset,
)
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.workspace_auth_guard import WorkspaceAuth

logger = logging.getLogger(__name__)


def _first_non_empty(*values: Any) -> str | None:
    for val in values:
        if isinstance(val, str):
            stripped = val.strip()
            if stripped:
                return stripped
    return None


def _enum_str(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value or "")


def _is_usable_async_db(db: Any) -> bool:
    """Returns True when ``db`` is an ``AsyncSession`` or async test double."""
    if db is None:
        return False
    if isinstance(db, AsyncSession):
        return True
    execute_fn = getattr(db, "execute", None)
    commit_fn = getattr(db, "commit", None)
    return inspect.iscoroutinefunction(
        execute_fn
    ) and inspect.iscoroutinefunction(commit_fn)


async def record_lineage_safely(
    db: Any,
    *,
    workspace_id: int,
    child_type: LineageItemTypeEnum,
    child_id: int | None,
    child_mime_type: Any = None,
    user_prompt: str | None = None,
    source_assets: Sequence[Any] | None = None,
    source_media_items: Sequence[Any] | None = None,
    explicit_primary: ExplicitPrimarySpec | None = None,
    skip_if_exists: bool = False,
) -> None:
    """Best-effort lineage persistence that never fails a generation job."""
    if not child_id or child_id <= 0 or not workspace_id or workspace_id <= 0:
        return

    edges = build_lineage_edges(
        child_type=child_type,
        child_id=int(child_id),
        child_mime_type=_enum_str(child_mime_type) or None,
        user_prompt=user_prompt,
        source_assets=source_assets,
        source_media_items=source_media_items,
        explicit_primary=explicit_primary,
    )
    if not edges or not _is_usable_async_db(db):
        return

    try:
        repo = LineageRepository(db)
        if skip_if_exists and await repo.has_any_edges_for_child(
            workspace_id=int(workspace_id),
            child_type=child_type,
            child_id=int(child_id),
        ):
            return
        await repo.replace_child_edges(
            workspace_id=int(workspace_id),
            child_type=child_type,
            child_id=int(child_id),
            edges=edges,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Failed to record item lineage for %s %s in workspace %s: %s",
            child_type.value,
            child_id,
            workspace_id,
            exc,
        )
        rollback_fn = getattr(db, "rollback", None)
        if inspect.iscoroutinefunction(rollback_fn):
            try:
                await rollback_fn()
            except Exception:  # pylint: disable=broad-except
                pass


class LineageService:
    """Queries and enriches ancestor chains and derived items."""

    def __init__(
        self,
        lineage_repo: LineageRepository = Depends(),
        workspace_repo: WorkspaceRepository = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
        db: AsyncSession = Depends(get_db),
    ):
        self.lineage_repo = lineage_repo
        self.workspace_repo = workspace_repo
        self.workspace_auth = workspace_auth
        self.iam_signer_credentials = iam_signer_credentials
        self.db = db

    async def _load_media_items_by_ids(
        self, ids: set[int]
    ) -> dict[int, MediaItem]:
        if not ids:
            return {}
        stmt = select(MediaItem).where(MediaItem.id.in_(sorted(ids)))
        result = await self.db.execute(stmt)
        return {row.id: row for row in result.scalars().all()}

    async def _load_source_assets_by_ids(
        self, ids: set[int]
    ) -> dict[int, SourceAsset]:
        if not ids:
            return {}
        stmt = select(SourceAsset).where(SourceAsset.id.in_(sorted(ids)))
        result = await self.db.execute(stmt)
        return {row.id: row for row in result.scalars().all()}

    async def _authorize_and_resolve_target(
        self,
        item_type: LineageItemTypeEnum,
        item_id: int,
        current_user: UserModel,
    ) -> tuple[int, MediaItem | SourceAsset]:
        """Authorizes target access and returns ``(workspace_id, row)``."""
        is_admin = UserRoleEnum.ADMIN in (current_user.roles or [])

        if item_type == LineageItemTypeEnum.MEDIA_ITEM:
            media_map = await self._load_media_items_by_ids({item_id})
            target = media_map.get(item_id)
            if target is None or (
                target.deleted_at is not None and not is_admin
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Media item not found.",
                )
            workspace = await self.workspace_repo.get_by_id(target.workspace_id)
            if not workspace:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent workspace for this item not found.",
                )
            await self.workspace_auth.authorize(
                workspace_id=target.workspace_id,
                user=current_user,
            )
            return target.workspace_id, target

        asset_map = await self._load_source_assets_by_ids({item_id})
        target_asset = asset_map.get(item_id)
        if target_asset is None or (
            target_asset.deleted_at is not None and not is_admin
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source asset not found.",
            )
        if _enum_str(target_asset.scope) != AssetScopeEnum.SYSTEM.value:
            workspace = await self.workspace_repo.get_by_id(
                target_asset.workspace_id
            )
            if not workspace:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent workspace for this asset not found.",
                )
            await self.workspace_auth.authorize(
                workspace_id=target_asset.workspace_id,
                user=current_user,
            )
        return target_asset.workspace_id, target_asset

    @staticmethod
    def _extract_node_uris_and_meta(
        *,
        row: MediaItem | SourceAsset | None,
        media_index: int,
        workspace_id: int,
        is_admin: bool,
        is_root: bool,
        edge_role: str | None,
        edge_summary: str | None,
    ) -> tuple[dict[str, Any], str | None, str | None]:
        """Extracts node metadata plus ``(raw_thumb_gcs, raw_preview_gcs)``."""
        if row is None:
            return (
                {
                    "deleted": True,
                    "prompt": edge_summary
                    or ("Original source unavailable" if is_root else None),
                    "role": edge_role,
                },
                None,
                None,
            )

        if isinstance(row, MediaItem):
            in_workspace = row.workspace_id == workspace_id
            is_deleted = row.deleted_at is not None or not in_workspace
            if is_deleted and not (is_admin and in_workspace):
                return (
                    {
                        "mime_type": (
                            _enum_str(row.mime_type) if in_workspace else None
                        ),
                        "model": _enum_str(row.model) if in_workspace else None,
                        "deleted": True,
                        "prompt": edge_summary
                        or (
                            _first_non_empty(row.original_prompt, row.prompt)
                            if in_workspace and is_root
                            else (
                                "Original source removed" if is_root else None
                            )
                        ),
                        "role": edge_role,
                        "created_at": row.created_at if in_workspace else None,
                    },
                    None,
                    None,
                )

            uris = list(row.gcs_uris or [])
            thumbs = list(row.thumbnail_uris or [])
            safe_idx = media_index if 0 <= media_index < len(uris) else 0
            preview_gcs = uris[safe_idx] if uris else None
            mime_val = _enum_str(row.mime_type)
            thumb_gcs: str | None = None
            if thumbs and 0 <= safe_idx < len(thumbs) and thumbs[safe_idx]:
                thumb_gcs = thumbs[safe_idx]
            elif mime_val.startswith("image/") and preview_gcs:
                thumb_gcs = preview_gcs

            titles = list(row.titles or [])
            title = (
                titles[safe_idx]
                if 0 <= safe_idx < len(titles) and titles[safe_idx]
                else (titles[0] if titles else None)
            )
            own_prompt = _first_non_empty(row.original_prompt, row.prompt)
            step_prompt = (
                own_prompt
                if is_root
                else _first_non_empty(edge_summary, own_prompt)
            )
            return (
                {
                    "mime_type": mime_val or None,
                    "model": _enum_str(row.model) or None,
                    "title": _first_non_empty(title, row.comment),
                    "prompt": step_prompt,
                    "role": edge_role,
                    "status": _enum_str(row.status) or None,
                    "deleted": bool(row.deleted_at is not None),
                    "created_at": row.created_at,
                },
                thumb_gcs,
                preview_gcs,
            )

        # SourceAsset branch
        in_workspace = (
            row.workspace_id == workspace_id
            or _enum_str(row.scope) == AssetScopeEnum.SYSTEM.value
        )
        is_deleted = row.deleted_at is not None or not in_workspace
        if is_deleted and not (is_admin and in_workspace):
            return (
                {
                    "mime_type": (
                        _enum_str(row.mime_type) if in_workspace else None
                    ),
                    "deleted": True,
                    "prompt": edge_summary
                    or ("Uploaded source removed" if is_root else None),
                    "role": edge_role,
                    "created_at": row.created_at if in_workspace else None,
                },
                None,
                None,
            )

        titles = list(row.titles or [])
        asset_title = _first_non_empty(
            titles[0] if titles else None,
            row.original_filename,
            f"Asset #{row.id}",
        )
        root_label = (
            f"Uploaded: {asset_title}" if asset_title else "Uploaded asset"
        )
        step_prompt = (
            root_label
            if is_root
            else _first_non_empty(edge_summary, root_label)
        )

        is_youtube = _enum_str(
            row.asset_type
        ) == AssetTypeEnum.YOUTUBE_VIDEO.value or (
            isinstance(row.external_url, str)
            and bool(extract_youtube_video_id(row.external_url))
        )
        if is_youtube and row.external_url:
            yt_id = extract_youtube_video_id(row.external_url)
            yt_thumb = (
                f"https://img.youtube.com/vi/{yt_id}/mqdefault.jpg"
                if yt_id
                else None
            )
            return (
                {
                    "mime_type": _enum_str(row.mime_type) or "video/mp4",
                    "title": asset_title,
                    "prompt": step_prompt,
                    "role": edge_role,
                    "status": JobStatusEnum.COMPLETED.value,
                    "thumbnail_url": yt_thumb,
                    "preview_url": row.external_url,
                    "deleted": bool(row.deleted_at is not None),
                    "created_at": row.created_at,
                },
                None,
                None,
            )

        mime_val = _enum_str(row.mime_type)
        preview_gcs = row.gcs_uri
        thumb_gcs = (
            row.thumbnail_gcs_uri
            if row.thumbnail_gcs_uri
            else (preview_gcs if mime_val.startswith("image/") else None)
        )
        return (
            {
                "mime_type": mime_val or None,
                "title": asset_title,
                "prompt": step_prompt,
                "role": edge_role,
                "status": JobStatusEnum.COMPLETED.value,
                "deleted": bool(row.deleted_at is not None),
                "created_at": row.created_at,
            },
            thumb_gcs,
            preview_gcs,
        )

    async def _batch_sign_gcs_uris(self, uris: set[str]) -> dict[str, str]:
        clean_uris = sorted(u for u in uris if u and u.startswith("gs://"))
        if not clean_uris:
            return {}
        signed = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self.iam_signer_credentials.generate_presigned_url,
                    uri,
                )
                for uri in clean_uris
            )
        )
        return dict(zip(clean_uris, signed))

    async def get_item_lineage(
        self,
        *,
        item_type: LineageItemTypeEnum,
        item_id: int,
        current_user: UserModel,
        max_depth: int = 25,
    ) -> ItemLineageResponseDto:
        """Returns the primary ancestor spine and active direct derivatives."""
        is_admin = UserRoleEnum.ADMIN in (current_user.roles or [])
        workspace_id, target_row = await self._authorize_and_resolve_target(
            item_type=item_type,
            item_id=item_id,
            current_user=current_user,
        )

        ancestor_edges: list[AncestorChainRow] = (
            await self.lineage_repo.get_primary_ancestor_chain(
                workspace_id=workspace_id,
                item_type=item_type,
                item_id=item_id,
                max_depth=max_depth,
            )
        )
        derivative_edges: list[ItemLineage] = (
            await self.lineage_repo.get_direct_derivative_edges(
                workspace_id=workspace_id,
                parent_type=item_type,
                parent_id=item_id,
            )
        )

        media_ids_to_load: set[int] = set()
        asset_ids_to_load: set[int] = set()

        for a_edge in ancestor_edges:
            for n_type, n_id in (
                (a_edge.parent_type, a_edge.parent_id),
                (a_edge.child_type, a_edge.child_id),
            ):
                if n_type == LineageItemTypeEnum.MEDIA_ITEM.value:
                    media_ids_to_load.add(n_id)
                elif n_type == LineageItemTypeEnum.SOURCE_ASSET.value:
                    asset_ids_to_load.add(n_id)

        for d_edge in derivative_edges:
            if d_edge.child_type == LineageItemTypeEnum.MEDIA_ITEM.value:
                media_ids_to_load.add(d_edge.child_id)
            elif d_edge.child_type == LineageItemTypeEnum.SOURCE_ASSET.value:
                asset_ids_to_load.add(d_edge.child_id)

        media_map, asset_map = await asyncio.gather(
            self._load_media_items_by_ids(media_ids_to_load),
            self._load_source_assets_by_ids(asset_ids_to_load),
        )
        if isinstance(target_row, MediaItem):
            media_map[target_row.id] = target_row
        else:
            asset_map[target_row.id] = target_row

        def lookup_row(
            node_type: LineageItemTypeEnum, node_id: int
        ) -> MediaItem | SourceAsset | None:
            return (
                media_map.get(node_id)
                if node_type == LineageItemTypeEnum.MEDIA_ITEM
                else asset_map.get(node_id)
            )

        uris_to_sign: set[str] = set()
        pending_spine: list[tuple[dict[str, Any], str | None, str | None]] = []

        if ancestor_edges:
            first_edge = ancestor_edges[0]
            root_type = LineageItemTypeEnum(first_edge.parent_type)
            root_meta, root_thumb, root_prev = self._extract_node_uris_and_meta(
                row=lookup_row(root_type, first_edge.parent_id),
                media_index=first_edge.parent_index,
                workspace_id=workspace_id,
                is_admin=is_admin,
                is_root=True,
                edge_role=None,
                edge_summary=None,
            )
            root_meta.update(
                {
                    "item_type": root_type,
                    "id": first_edge.parent_id,
                    "media_index": first_edge.parent_index,
                }
            )
            pending_spine.append((root_meta, root_thumb, root_prev))
            if root_thumb:
                uris_to_sign.add(root_thumb)
            if root_prev:
                uris_to_sign.add(root_prev)

            for idx, edge in enumerate(ancestor_edges):
                step_type = LineageItemTypeEnum(edge.child_type)
                next_edge = (
                    ancestor_edges[idx + 1]
                    if idx + 1 < len(ancestor_edges)
                    else None
                )
                step_media_index = (
                    next_edge.parent_index
                    if next_edge is not None
                    else int(edge.child_index or 0)
                )
                step_meta, step_thumb, step_prev = (
                    self._extract_node_uris_and_meta(
                        row=lookup_row(step_type, edge.child_id),
                        media_index=step_media_index,
                        workspace_id=workspace_id,
                        is_admin=is_admin,
                        is_root=False,
                        edge_role=edge.role,
                        edge_summary=edge.action_summary,
                    )
                )
                step_meta.update(
                    {
                        "item_type": step_type,
                        "id": edge.child_id,
                        "media_index": step_media_index,
                    }
                )
                pending_spine.append((step_meta, step_thumb, step_prev))
                if step_thumb:
                    uris_to_sign.add(step_thumb)
                if step_prev:
                    uris_to_sign.add(step_prev)

        # Deduplicate direct derivatives, preferring primary edges when present
        chosen_derivative_edges: dict[tuple[str, int], ItemLineage] = {}
        for d_edge in derivative_edges:
            key = (d_edge.child_type, d_edge.child_id)
            existing = chosen_derivative_edges.get(key)
            if existing is None or (
                d_edge.is_primary_parent and not existing.is_primary_parent
            ):
                chosen_derivative_edges[key] = d_edge

        pending_derivatives: list[
            tuple[dict[str, Any], str | None, str | None]
        ] = []
        for d_edge in chosen_derivative_edges.values():
            d_type = LineageItemTypeEnum(d_edge.child_type)
            d_row = lookup_row(d_type, d_edge.child_id)
            if d_row is None or d_row.deleted_at is not None:
                continue
            if d_row.workspace_id != workspace_id:
                continue
            if isinstance(d_row, MediaItem) and (
                _enum_str(d_row.status) != JobStatusEnum.COMPLETED.value
            ):
                continue

            d_idx = int(d_edge.child_index or 0)
            d_meta, d_thumb, d_prev = self._extract_node_uris_and_meta(
                row=d_row,
                media_index=d_idx,
                workspace_id=workspace_id,
                is_admin=is_admin,
                is_root=False,
                edge_role=d_edge.role,
                edge_summary=d_edge.action_summary,
            )
            d_meta.update(
                {
                    "item_type": d_type,
                    "id": d_edge.child_id,
                    "media_index": d_idx,
                }
            )
            pending_derivatives.append((d_meta, d_thumb, d_prev))
            if d_thumb:
                uris_to_sign.add(d_thumb)
            if d_prev:
                uris_to_sign.add(d_prev)

        signed_map = await self._batch_sign_gcs_uris(uris_to_sign)

        def finalize_node(
            meta: dict[str, Any],
            thumb_gcs: str | None,
            prev_gcs: str | None,
        ) -> LineageNodeDto:
            if thumb_gcs and not meta.get("thumbnail_url"):
                meta["thumbnail_url"] = signed_map.get(thumb_gcs)
            if prev_gcs and not meta.get("preview_url"):
                meta["preview_url"] = signed_map.get(prev_gcs)
            return LineageNodeDto(**meta)

        return ItemLineageResponseDto(
            spine=[finalize_node(m, t, p) for m, t, p in pending_spine],
            derivatives=[
                finalize_node(m, t, p) for m, t, p in pending_derivatives
            ],
        )
