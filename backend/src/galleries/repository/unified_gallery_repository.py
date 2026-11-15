# Copyright 2025 Google LLC
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
"""Repository for unified gallery pagination and workflow loop queries."""

from collections.abc import Iterable
import datetime
from enum import Enum
from typing import Any

from fastapi import Depends
from sqlalchemy import and_, any_, exists, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.media_item_model import JobStatusEnum, MediaItem
from src.common.schema.unified_gallery_view import UnifiedGalleryView
from src.database import get_db
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.unified_gallery_response import (
    UnifiedGalleryItemResponse,
)
from src.source_assets.schema.source_asset_model import SourceAsset
from src.tags.schema.tags_model import (
    Tag,
    media_item_tags,
    source_asset_tags,
)
from src.users.user_model import User

# ``item_type`` values of the unified gallery view.
LOOP_MEDIA_ITEM = "media_item"
LOOP_SOURCE_ASSET = "source_asset"


class UnifiedGalleryRepository(
    BaseRepository[UnifiedGalleryView, UnifiedGalleryItemResponse],
):
    """Repository for accessing the unified_gallery_view."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=UnifiedGalleryView,
            schema=UnifiedGalleryItemResponse,
            db=db,
        )

    def _apply_common_filters(
        self,
        stmt: Any,
        table: type[MediaItem] | type[SourceAsset],
        search_dto: GallerySearchDto,
        user_id: int | None,
    ) -> Any:
        """Applies shared gallery filters to a base-table key query."""
        if not search_dto.include_deleted:
            stmt = stmt.where(table.deleted_at.is_(None))

        if search_dto.workspace_id is not None:
            stmt = stmt.where(table.workspace_id == search_dto.workspace_id)

        if user_id is not None:
            stmt = stmt.where(table.user_id == user_id)

        if search_dto.user_email:
            users_tbl = User.__table__
            stmt = stmt.join(users_tbl, table.user_id == users_tbl.c.id).where(
                users_tbl.c.email == search_dto.user_email
            )

        if search_dto.mime_type:
            mime_val = (
                search_dto.mime_type.value
                if isinstance(search_dto.mime_type, Enum)
                else search_dto.mime_type
            )
            if "*" in mime_val:
                stmt = stmt.where(
                    table.mime_type.like(mime_val.replace("*", "%"))
                )
            else:
                stmt = stmt.where(table.mime_type == mime_val)

        if search_dto.start_date:
            stmt = stmt.where(table.created_at >= search_dto.start_date)

        if search_dto.end_date:
            stmt = stmt.where(
                table.created_at
                < search_dto.end_date + datetime.timedelta(days=1)
            )

        if search_dto.is_root:
            stmt = stmt.where(table.folder_id.is_(None))
        elif search_dto.folder_id is not None:
            stmt = stmt.where(table.folder_id == search_dto.folder_id)

        return stmt

    def _build_filtered_keys_subquery(
        self,
        search_dto: GallerySearchDto,
        user_id: int | None = None,
        *,
        top_n: int | None = None,
    ) -> Any | None:
        """Builds a base-table subquery yielding (id, item_type, created_at).

        Filtering and sorting directly against the indexed base tables avoids
        scanning all rows through ``unified_gallery_view`` (and constructing
        per-row JSONB + tag aggregation) just to count or discard non-page rows.
        When ``top_n`` is supplied for page-key selection across multiple
        branches, each branch is pre-limited by ``(created_at DESC, id DESC)``
        so Postgres can merge-append top keys without sorting the full table.
        """
        item_type = search_dto.item_type
        include_media = True
        include_source = True
        if item_type == LOOP_MEDIA_ITEM:
            include_source = False
        elif item_type == LOOP_SOURCE_ASSET:
            include_media = False
        elif item_type:
            include_media = False
            include_source = False

        if search_dto.status and search_dto.status != JobStatusEnum.COMPLETED:
            include_source = False
        if search_dto.model:
            include_source = False

        branches: list[Any] = []
        tags = search_dto.tags or []
        search_text = search_dto.query
        search_pattern = f"%{search_text}%" if search_text else None

        if include_media:
            media_stmt = select(
                MediaItem.id.label("id"),
                literal(LOOP_MEDIA_ITEM).label("item_type"),
                MediaItem.created_at.label("created_at"),
            )
            media_stmt = self._apply_common_filters(
                media_stmt, MediaItem, search_dto, user_id
            )
            if search_dto.status:
                media_stmt = media_stmt.where(
                    MediaItem.status == search_dto.status.value
                )
            if search_dto.model:
                media_stmt = media_stmt.where(
                    MediaItem.model == search_dto.model.value
                )
            for tag_name in tags:
                media_stmt = media_stmt.where(
                    exists(
                        select(1)
                        .select_from(
                            media_item_tags.join(
                                Tag, media_item_tags.c.tag_id == Tag.id
                            )
                        )
                        .where(
                            media_item_tags.c.media_item_id == MediaItem.id,
                            Tag.name == tag_name,
                        )
                    )
                )
            if search_pattern:
                media_stmt = media_stmt.where(
                    func.coalesce(MediaItem.prompt, "").ilike(search_pattern)
                    | func.coalesce(MediaItem.comment, "").ilike(search_pattern)
                    | func.coalesce(MediaItem.model, "").ilike(search_pattern)
                )
            if top_n is not None and include_source:
                media_stmt = media_stmt.order_by(
                    MediaItem.created_at.desc(),
                    MediaItem.id.desc(),
                ).limit(top_n)
            branches.append(media_stmt)

        if include_source:
            source_stmt = select(
                SourceAsset.id.label("id"),
                literal(LOOP_SOURCE_ASSET).label("item_type"),
                SourceAsset.created_at.label("created_at"),
            )
            source_stmt = self._apply_common_filters(
                source_stmt, SourceAsset, search_dto, user_id
            )
            if not search_dto.include_external:
                source_stmt = source_stmt.where(
                    SourceAsset.external_url.is_(None)
                    | (SourceAsset.external_url == "")
                )
            for tag_name in tags:
                source_stmt = source_stmt.where(
                    exists(
                        select(1)
                        .select_from(
                            source_asset_tags.join(
                                Tag, source_asset_tags.c.tag_id == Tag.id
                            )
                        )
                        .where(
                            source_asset_tags.c.source_asset_id
                            == SourceAsset.id,
                            Tag.name == tag_name,
                        )
                    )
                )
            if search_pattern:
                source_stmt = source_stmt.where(
                    func.coalesce(SourceAsset.original_filename, "").ilike(
                        search_pattern
                    )
                )
            if top_n is not None and include_media:
                source_stmt = source_stmt.order_by(
                    SourceAsset.created_at.desc(),
                    SourceAsset.id.desc(),
                ).limit(top_n)
            branches.append(source_stmt)

        if not branches:
            return None
        if len(branches) == 1:
            return branches[0].subquery("filtered_keys")
        return union_all(*branches).subquery("filtered_keys")

    async def query(
        self,
        search_dto: GallerySearchDto,
        user_id: int | None = None,
    ) -> PaginationResponseDto[UnifiedGalleryItemResponse]:
        """Runs a two-stage paginated query on gallery base tables and view.

        Contract note: relies on the columns, eligibility, and metadata shape of
        ``unified_gallery_view`` defined in
        ``d4e5f6a7b8c9_create_folders_and_hierarchy.py``. ``user_id`` is
        resolved from ``search_dto.user_email`` in the service layer when set.
        """
        page = (search_dto.offset // search_dto.limit) + 1
        page_size = search_dto.limit

        count_keys_subq = self._build_filtered_keys_subquery(
            search_dto, user_id=user_id
        )
        if count_keys_subq is None:
            return PaginationResponseDto[UnifiedGalleryItemResponse](
                count=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                data=[],
            )

        # Stage 1: Count matching keys on base tables without view JSONB work.
        count_query = select(func.count()).select_from(count_keys_subq)
        if search_dto.include_deleted:
            count_query = count_query.execution_options(include_deleted=True)
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar_one()

        total_pages = (total_count + page_size - 1) // page_size
        if total_count == 0 or search_dto.offset >= total_count:
            return PaginationResponseDto[UnifiedGalleryItemResponse](
                count=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                data=[],
            )

        # Stage 2: Page keys on base tables, then push branch IDs into
        # unified_gallery_view so Postgres resolves only page rows via PKs.
        page_keys_subq = self._build_filtered_keys_subquery(
            search_dto,
            user_id=user_id,
            top_n=search_dto.offset + search_dto.limit,
        )
        page_keys = (
            select(
                page_keys_subq.c.id,
                page_keys_subq.c.item_type,
                page_keys_subq.c.created_at,
            )
            .order_by(
                page_keys_subq.c.created_at.desc(),
                page_keys_subq.c.id.desc(),
                page_keys_subq.c.item_type.desc(),
            )
            .offset(search_dto.offset)
            .limit(search_dto.limit)
            .cte("page_keys")
        )
        # Filter each UNION ALL branch of unified_gallery_view by a constant
        # item_type + scalar ARRAY(...) so the planner pushes Index Scans down.
        query = (
            select(self.model)
            .where(
                or_(
                    *(
                        and_(
                            self.model.item_type == branch_type,
                            self.model.id
                            == any_(
                                func.array(
                                    select(page_keys.c.id)
                                    .where(page_keys.c.item_type == branch_type)
                                    .scalar_subquery()
                                )
                            ),
                        )
                        for branch_type in (
                            LOOP_MEDIA_ITEM,
                            LOOP_SOURCE_ASSET,
                        )
                    )
                )
            )
            .order_by(
                self.model.created_at.desc(),
                self.model.id.desc(),
                self.model.item_type.desc(),
            )
        )
        if search_dto.include_deleted:
            query = query.execution_options(include_deleted=True)

        result = await self.db.execute(query)
        rows = result.scalars().all()

        data = [self.schema.model_validate(item) for item in rows]

        return PaginationResponseDto[UnifiedGalleryItemResponse](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=data,
        )

    def _loop_item_conditions(
        self, *, workspace_id: int, mime_type_prefix: str
    ) -> tuple[Any, ...]:
        """Conditions of a row a workflow ``Loop`` step may iterate over.

        Non-deleted rows of the workspace whose ``mime_type`` starts with
        ``"<mime_type_prefix>/"``: completed generated ``media_item`` rows
        and uploaded ``source_asset`` rows. External resources
        (``external_url`` set) are skipped, as in the default gallery view.
        """
        external_url = self.model.metadata_["external_url"].astext
        return (
            self.model.workspace_id == workspace_id,
            self.model.deleted_at.is_(None),
            self.model.metadata_["mime_type"].astext.like(
                f"{mime_type_prefix}/%"
            ),
            external_url.is_(None) | (external_url == ""),
            or_(
                and_(
                    self.model.item_type == LOOP_MEDIA_ITEM,
                    self.model.status == JobStatusEnum.COMPLETED.value,
                ),
                self.model.item_type == LOOP_SOURCE_ASSET,
            ),
        )

    async def list_folder_loop_items(
        self,
        *,
        workspace_id: int,
        folder_id: int,
        mime_type_prefix: str,
        limit: int,
    ) -> tuple[list[tuple[str, int]], int]:
        """Media of a folder iterated by a workflow ``Loop`` step.

        Considers non-deleted rows of the given workspace and folder whose
        ``mime_type`` starts with ``"<mime_type_prefix>/"``: completed
        generated ``media_item`` rows and uploaded ``source_asset`` rows.
        External resources (``external_url`` set) are skipped, as in the
        default gallery view.

        Args:
            workspace_id: Workspace the folder belongs to.
            folder_id: Folder to list.
            mime_type_prefix: ``"image"``, ``"video"`` or ``"audio"``.
            limit: Maximum number of rows returned.

        Returns:
            ``(rows, total)``: up to ``limit`` ``(item_type, id)`` pairs
            (``item_type`` is ``"media_item"`` or ``"source_asset"``),
            oldest first (``created_at, item_type, id``), and the total
            number of matches.
        """
        conditions = (
            *self._loop_item_conditions(
                workspace_id=workspace_id, mime_type_prefix=mime_type_prefix
            ),
            self.model.folder_id == folder_id,
        )
        count_result = await self.db.execute(
            select(func.count()).select_from(self.model).where(*conditions)
        )
        total = count_result.scalar_one()
        rows_result = await self.db.execute(
            select(self.model.item_type, self.model.id)
            .where(*conditions)
            .order_by(
                self.model.created_at.asc(),
                self.model.item_type.asc(),
                self.model.id.asc(),
            )
            .limit(limit)
        )
        rows = [(item_type, item_id) for item_type, item_id in rows_result]
        return rows, total

    async def filter_linked_loop_items(
        self,
        *,
        workspace_id: int,
        media_item_ids: Iterable[int],
        source_asset_ids: Iterable[int],
        mime_type_prefix: str,
    ) -> set[tuple[str, int]]:
        """Linked media a workflow ``Loop`` step may iterate over.

        Applies the same eligibility rules as
        :meth:`list_folder_loop_items` (workspace, not deleted, mime prefix,
        completed media items, no external URL) to the given ids, in one
        query and without any folder filter.

        Args:
            workspace_id: Workspace of the run.
            media_item_ids: Candidate generated media item ids.
            source_asset_ids: Candidate uploaded source asset ids.
            mime_type_prefix: ``"image"``, ``"video"`` or ``"audio"``.

        Returns:
            The eligible ``(item_type, id)`` pairs (``item_type`` is
            ``"media_item"`` or ``"source_asset"``). Empty, without any
            query, when no id is given.
        """
        id_filters = [
            and_(self.model.item_type == item_type, self.model.id.in_(ids))
            for item_type, ids in (
                (LOOP_MEDIA_ITEM, sorted(set(media_item_ids))),
                (LOOP_SOURCE_ASSET, sorted(set(source_asset_ids))),
            )
            if ids
        ]
        if not id_filters:
            return set()
        result = await self.db.execute(
            select(self.model.item_type, self.model.id).where(
                *self._loop_item_conditions(
                    workspace_id=workspace_id,
                    mime_type_prefix=mime_type_prefix,
                ),
                or_(*id_filters),
            )
        )
        return {(item_type, item_id) for item_type, item_id in result}
