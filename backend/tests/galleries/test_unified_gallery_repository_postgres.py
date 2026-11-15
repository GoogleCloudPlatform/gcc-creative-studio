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
"""Real PostgreSQL row-equivalence tests for UnifiedGalleryRepository.

Runs against an ephemeral THROWAWAY database migrated via Alembic to ``head``
and compares ``UnifiedGalleryRepository.query()`` output (total count,
hydration fields, filter semantics, pagination, and sort order) against direct
queries on ``unified_gallery_view``.
"""

import asyncio
import contextlib
import datetime
from collections.abc import Callable, Iterator
from typing import Any

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_dto import (
    GenerationModelEnum,
    MimeTypeEnum,
    WildcardMimeTypeEnum,
)
from src.common.schema.media_item_model import JobStatusEnum
from src.common.schema.unified_gallery_view import UnifiedGalleryView
from src.config.config_service import config_service
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.repository.unified_gallery_repository import (
    UnifiedGalleryRepository,
)
from tests.postgres_harness import (
    connect_throwaway_db,
    drop_throwaway_db,
    in_worker_thread,
    make_nullpool_session_factory,
    recreate_throwaway_db,
    run_alembic_upgrade,
)

THROWAWAY_DB = "creative_studio_gallery_query_test"

DB_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


async def _seed_gallery_dataset() -> dict[str, Any]:
    conn = await connect_throwaway_db(THROWAWAY_DB)
    try:
        user_a = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('alice@example.com', ARRAY['user'], 'Alice', '') "
            "RETURNING id"
        )
        user_b = await conn.fetchval(
            "INSERT INTO users (email, roles, name, picture) "
            "VALUES ('bob@example.com', ARRAY['user'], 'Bob', '') "
            "RETURNING id"
        )
        main_ws = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Main Workspace', $1, 'public') RETURNING id",
            user_a,
        )
        other_ws = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Other Workspace', $1, 'private') RETURNING id",
            user_b,
        )
        folder_a = await conn.fetchval(
            "INSERT INTO folders (workspace_id, user_id, user_email, name) "
            "VALUES ($1, $2, 'alice@example.com', 'Folder A') RETURNING id",
            main_ws,
            user_a,
        )
        folder_b = await conn.fetchval(
            "INSERT INTO folders (workspace_id, user_id, user_email, name) "
            "VALUES ($1, $2, 'bob@example.com', 'Folder B') RETURNING id",
            main_ws,
            user_b,
        )
        tag_hero = await conn.fetchval(
            "INSERT INTO tags (workspace_id, name, color) "
            "VALUES ($1, 'hero', '#111111') RETURNING id",
            main_ws,
        )
        tag_summer = await conn.fetchval(
            "INSERT INTO tags (workspace_id, name, color) "
            "VALUES ($1, 'summer', '#222222') RETURNING id",
            main_ws,
        )
        tag_brand = await conn.fetchval(
            "INSERT INTO tags (workspace_id, name, color) "
            "VALUES ($1, 'brand', '#333333') RETURNING id",
            main_ws,
        )

        day1 = datetime.datetime(2026, 3, 1, 10, 0, tzinfo=datetime.UTC)
        day2 = datetime.datetime(2026, 3, 2, 10, 0, tzinfo=datetime.UTC)
        day2_late = datetime.datetime(2026, 3, 2, 22, 0, tzinfo=datetime.UTC)
        day3 = datetime.datetime(2026, 3, 3, 9, 0, tzinfo=datetime.UTC)
        deleted_ts = datetime.datetime(2026, 3, 4, 0, 0, tzinfo=datetime.UTC)

        # Insert explicit same-ID, same-timestamp pair (id=500) to test
        # deterministic cross-table tiebreaking (source_asset first).
        mi_tie = await conn.fetchval(
            "INSERT INTO media_items (id, workspace_id, user_id, user_email, "
            "folder_id, created_at, status, model, prompt, comment, mime_type, "
            "aspect_ratio, gcs_uris, thumbnail_uris) "
            "VALUES (500, $1, $2, 'alice@example.com', $3, $4, 'completed', "
            "'gemini-3-pro-image', 'Tie prompt', 'alpha', 'image/png', '1:1', "
            "ARRAY['gs://b/mi500.png'], ARRAY['gs://b/mi500_thumb.webp']) "
            "RETURNING id",
            main_ws,
            user_a,
            folder_a,
            day2,
        )
        sa_tie = await conn.fetchval(
            "INSERT INTO source_assets (id, workspace_id, user_id, folder_id, "
            "created_at, original_filename, mime_type, aspect_ratio, gcs_uri, "
            "thumbnail_gcs_uri, file_hash, scope, asset_type) "
            "VALUES (500, $1, $2, $3, $4, 'tie_asset.png', 'image/png', "
            "'1:1', 'gs://b/sa500.png', 'gs://b/sa500_thumb.webp', 'hash-500', "
            "'private', 'generic_image') RETURNING id",
            main_ws,
            user_a,
            folder_a,
            day2,
        )

        # Additional media_items covering statuses, models, mime types,
        # text search, date boundaries, soft deletes, and workspace isolation.
        mi_veo_root = await conn.fetchval(
            "INSERT INTO media_items (id, workspace_id, user_id, user_email, "
            "folder_id, created_at, status, model, prompt, comment, mime_type, "
            "aspect_ratio, gcs_uris, thumbnail_uris) "
            "VALUES (501, $1, $2, 'bob@example.com', NULL, $3, 'completed', "
            "'veo-3.0-fast-generate-001', 'Coastal drive', 'sunset review', "
            "'video/mp4', '16:9', ARRAY['gs://b/mi501.mp4'], "
            "ARRAY['gs://b/mi501_thumb.jpg']) RETURNING id",
            main_ws,
            user_b,
            day3,
        )
        mi_processing = await conn.fetchval(
            "INSERT INTO media_items (id, workspace_id, user_id, user_email, "
            "folder_id, created_at, status, model, prompt, comment, mime_type, "
            "aspect_ratio, gcs_uris, thumbnail_uris) "
            "VALUES (502, $1, $2, 'alice@example.com', $3, $4, 'processing', "
            "'gemini-3-pro-image', 'Sunset sketch', NULL, 'image/webp', "
            "'1:1', ARRAY['gs://b/mi502.webp'], ARRAY['gs://b/mi502.webp']) "
            "RETURNING id",
            main_ws,
            user_a,
            folder_b,
            day2_late,
        )
        mi_deleted = await conn.fetchval(
            "INSERT INTO media_items (id, workspace_id, user_id, user_email, "
            "folder_id, created_at, status, model, prompt, comment, mime_type, "
            "aspect_ratio, gcs_uris, thumbnail_uris, deleted_at) "
            "VALUES (503, $1, $2, 'alice@example.com', $3, $4, 'completed', "
            "'gemini-3-pro-image', 'Deleted sunset', NULL, 'image/png', '1:1', "
            "ARRAY['gs://b/mi503.png'], ARRAY['gs://b/mi503_thumb.webp'], $5) "
            "RETURNING id",
            main_ws,
            user_a,
            folder_a,
            day1,
            deleted_ts,
        )
        await conn.execute(
            "INSERT INTO media_items (id, workspace_id, user_id, user_email, "
            "folder_id, created_at, status, model, prompt, comment, mime_type, "
            "aspect_ratio, gcs_uris, thumbnail_uris) "
            "VALUES (504, $1, $2, 'bob@example.com', NULL, $3, 'completed', "
            "'gemini-3-pro-image', 'Other ws sunset', NULL, 'image/png', "
            "'1:1', ARRAY['gs://b/mi504.png'], ARRAY['gs://b/mi504.webp'])",
            other_ws,
            user_b,
            day3,
        )

        # Additional source_assets: root, JPEG, external YouTube, soft-deleted.
        sa_root = await conn.fetchval(
            "INSERT INTO source_assets (id, workspace_id, user_id, folder_id, "
            "created_at, original_filename, mime_type, aspect_ratio, gcs_uri, "
            "thumbnail_gcs_uri, file_hash, scope, asset_type) "
            "VALUES (501, $1, $2, NULL, $3, 'Sunset_Banner.jpg', 'image/jpeg', "
            "'16:9', 'gs://b/sa501.jpg', 'gs://b/sa501_thumb.webp', "
            "'hash-501', 'private', 'generic_image') RETURNING id",
            main_ws,
            user_b,
            day2_late,
        )
        sa_external = await conn.fetchval(
            "INSERT INTO source_assets (id, workspace_id, user_id, folder_id, "
            "created_at, original_filename, mime_type, aspect_ratio, gcs_uri, "
            "thumbnail_gcs_uri, file_hash, scope, asset_type, external_url) "
            "VALUES (502, $1, $2, $3, $4, 'yt_clip.mp4', 'video/mp4', '16:9', "
            "'gs://b/sa502.mp4', NULL, 'hash-502', 'private', 'generic_video', "
            "'https://youtube.com/watch?v=dQw4w9WgXcQ') RETURNING id",
            main_ws,
            user_a,
            folder_b,
            day1,
        )
        sa_deleted = await conn.fetchval(
            "INSERT INTO source_assets (id, workspace_id, user_id, folder_id, "
            "created_at, original_filename, mime_type, aspect_ratio, gcs_uri, "
            "thumbnail_gcs_uri, file_hash, scope, asset_type, deleted_at) "
            "VALUES (503, $1, $2, $3, $4, 'deleted_asset.png', 'image/png', "
            "'1:1', 'gs://b/sa503.png', 'gs://b/sa503_thumb.webp', 'hash-503', "
            "'private', 'generic_image', $5) RETURNING id",
            main_ws,
            user_a,
            folder_a,
            day1,
            deleted_ts,
        )

        # Tags:
        # mi_tie (500): hero + summer
        # mi_veo_root (501): hero only
        # sa_tie (500): hero + summer + brand
        # sa_root (501): summer only
        await conn.executemany(
            "INSERT INTO media_item_tags (media_item_id, tag_id) "
            "VALUES ($1, $2)",
            [
                (mi_tie, tag_hero),
                (mi_tie, tag_summer),
                (mi_veo_root, tag_hero),
            ],
        )
        await conn.executemany(
            "INSERT INTO source_asset_tags (source_asset_id, tag_id) "
            "VALUES ($1, $2)",
            [
                (sa_tie, tag_hero),
                (sa_tie, tag_summer),
                (sa_tie, tag_brand),
                (sa_root, tag_summer),
            ],
        )

        trunc_ws = await conn.fetchval(
            "INSERT INTO workspaces (name, owner_id, scope) "
            "VALUES ('Trunc Workspace', $1, 'public') RETURNING id",
            user_a,
        )
        base_ts = datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.UTC)
        # Seed 6 active media_items and 6 active source_assets so per-branch
        # pushdown limit(offset + limit) strictly truncates both branches.
        for idx in range(6):
            ts_media = base_ts + datetime.timedelta(minutes=idx * 2)
            ts_source = base_ts + datetime.timedelta(minutes=idx * 2 + 1)
            mi_id = 600 + idx
            sa_id = 600 + idx
            await conn.execute(
                "INSERT INTO media_items (id, workspace_id, user_id, "
                "user_email, folder_id, created_at, status, model, prompt, "
                "mime_type, aspect_ratio, gcs_uris, thumbnail_uris) "
                "VALUES ($1, $2, $3, 'alice@example.com', NULL, $4, "
                "'completed', 'gemini-3-pro-image', $5, 'image/png', '1:1', "
                "ARRAY[$6], ARRAY[$7])",
                mi_id,
                trunc_ws,
                user_a,
                ts_media,
                f"Trunc media {idx}",
                f"gs://b/trunc_m_{idx}.png",
                f"gs://b/trunc_m_{idx}_thumb.webp",
            )
            await conn.execute(
                "INSERT INTO source_assets (id, workspace_id, user_id, "
                "folder_id, created_at, original_filename, mime_type, "
                "aspect_ratio, gcs_uri, thumbnail_gcs_uri, file_hash, scope, "
                "asset_type) "
                "VALUES ($1, $2, $3, NULL, $4, $5, 'image/png', '1:1', "
                "$6, $7, $8, 'private', 'generic_image')",
                sa_id,
                trunc_ws,
                user_a,
                ts_source,
                f"trunc_{idx}.png",
                f"gs://b/trunc_s_{idx}.png",
                f"gs://b/trunc_s_{idx}_thumb.webp",
                f"hash-trunc-{idx}",
            )

        return {
            "main_ws": main_ws,
            "other_ws": other_ws,
            "trunc_ws": trunc_ws,
            "user_a": user_a,
            "user_b": user_b,
            "folder_a": folder_a,
            "folder_b": folder_b,
            "mi_tie": mi_tie,
            "sa_tie": sa_tie,
            "mi_veo_root": mi_veo_root,
            "mi_processing": mi_processing,
            "mi_deleted": mi_deleted,
            "sa_root": sa_root,
            "sa_external": sa_external,
            "sa_deleted": sa_deleted,
        }
    finally:
        await conn.close()


@pytest.fixture(name="seeded_gallery_db", scope="module")
def fixture_seeded_gallery_db() -> Iterator[dict[str, Any]]:
    """Migrates and seeds an ephemeral Postgres DB for repository tests."""
    if config_service.DB_NAME == THROWAWAY_DB:
        pytest.skip(
            "DB_NAME is the throwaway database; refusing to recreate it."
        )
    in_worker_thread(asyncio.run, recreate_throwaway_db(THROWAWAY_DB))
    try:
        run_alembic_upgrade(THROWAWAY_DB, "head")
        seeded = in_worker_thread(asyncio.run, _seed_gallery_dataset())
        yield seeded
    finally:
        with contextlib.suppress(DB_ERRORS):
            in_worker_thread(asyncio.run, drop_throwaway_db(THROWAWAY_DB))


async def _view_reference_query(
    session: AsyncSession,
    search_dto: GallerySearchDto,
    user_id: int | None = None,
) -> tuple[int, list[tuple[str, int]]]:
    """Reference SQL directly on ``unified_gallery_view`` for parity checks."""
    model = UnifiedGalleryView
    q = select(model)
    if not search_dto.include_deleted:
        q = q.where(model.deleted_at.is_(None))
    if not search_dto.include_external:
        ext = model.metadata_["external_url"].astext
        q = q.where(ext.is_(None) | (ext == ""))
    if search_dto.workspace_id is not None:
        q = q.where(model.workspace_id == search_dto.workspace_id)
    if user_id is not None:
        q = q.where(model.user_id == user_id)
    if search_dto.user_email:
        q = q.where(model.user_email == search_dto.user_email)
    if search_dto.status:
        q = q.where(model.status == search_dto.status.value)
    if search_dto.mime_type:
        mime_val = search_dto.mime_type.value
        if "*" in mime_val:
            q = q.where(
                model.metadata_["mime_type"].astext.like(
                    mime_val.replace("*", "%")
                )
            )
        else:
            q = q.where(model.metadata_["mime_type"].astext == mime_val)
    if search_dto.model:
        q = q.where(model.metadata_["model"].astext == search_dto.model.value)
    if search_dto.start_date:
        q = q.where(model.created_at >= search_dto.start_date)
    if search_dto.end_date:
        q = q.where(
            model.created_at < search_dto.end_date + datetime.timedelta(days=1)
        )
    if search_dto.is_root:
        q = q.where(model.folder_id.is_(None))
    elif search_dto.folder_id is not None:
        q = q.where(model.folder_id == search_dto.folder_id)
    if search_dto.item_type:
        q = q.where(model.item_type == search_dto.item_type)
    for tag_name in search_dto.tags or []:
        q = q.where(model.metadata_["tags"].contains([{"name": tag_name}]))
    if search_dto.query:
        pat = f"%{search_dto.query}%"
        q = q.where(
            func.coalesce(model.metadata_["prompt"].astext, "").ilike(pat)
            | func.coalesce(model.metadata_["file_name"].astext, "").ilike(pat)
            | func.coalesce(model.metadata_["model"].astext, "").ilike(pat)
            | func.coalesce(
                model.metadata_["original_filename"].astext, ""
            ).ilike(pat)
        )

    total = (
        await session.execute(select(func.count()).select_from(q.subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                q.order_by(
                    model.created_at.desc(),
                    model.id.desc(),
                    model.item_type.desc(),
                )
                .offset(search_dto.offset)
                .limit(search_dto.limit)
            )
        )
        .scalars()
        .all()
    )
    return total, [(r.item_type, r.id) for r in rows]


async def _run_with_repo(
    seeded_gallery_db: dict[str, Any],
    callback: Callable[[UnifiedGalleryRepository, AsyncSession], Any],
) -> Any:
    del seeded_gallery_db
    engine, session_maker = make_nullpool_session_factory(THROWAWAY_DB)
    try:
        async with session_maker() as session:
            return await callback(UnifiedGalleryRepository(db=session), session)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_default_pagination_and_deterministic_tiebreak(
    seeded_gallery_db: dict[str, Any],
) -> None:
    """Default view query matches view oracle across pages and exact ties."""
    main_ws = seeded_gallery_db["main_ws"]

    async def _verify(
        repo: UnifiedGalleryRepository, session: AsyncSession
    ) -> None:
        p1_dto = GallerySearchDto(
            workspace_id=main_ws,
            status=JobStatusEnum.COMPLETED,
            limit=2,
            offset=0,
        )
        p1 = await repo.query(p1_dto)
        ref1_count, ref1_keys = await _view_reference_query(session, p1_dto)
        assert p1.count == ref1_count == 4
        assert p1.total_pages == 2
        assert (
            [(i.item_type, i.id) for i in p1.data]
            == ref1_keys
            == [
                ("media_item", 501),
                ("source_asset", 501),
            ]
        )

        p2_dto = GallerySearchDto(
            workspace_id=main_ws,
            status=JobStatusEnum.COMPLETED,
            limit=2,
            offset=2,
        )
        p2 = await repo.query(p2_dto)
        ref2_count, ref2_keys = await _view_reference_query(session, p2_dto)
        assert p2.count == ref2_count == 4
        # Tie at (day2, id=500) orders source_asset before media_item.
        assert (
            [(i.item_type, i.id) for i in p2.data]
            == ref2_keys
            == [
                ("source_asset", 500),
                ("media_item", 500),
            ]
        )
        assert [t.name for t in p2.data[0].tags] == [
            "hero",
            "summer",
            "brand",
        ]

        oob = await repo.query(
            GallerySearchDto(
                workspace_id=main_ws,
                status=JobStatusEnum.COMPLETED,
                limit=2,
                offset=10,
            )
        )
        assert oob.count == 4
        assert oob.total_pages == 2
        assert oob.data == []

    await _run_with_repo(seeded_gallery_db, _verify)


@pytest.mark.anyio
async def test_postgres_folders_tags_and_search_equivalence(
    seeded_gallery_db: dict[str, Any],
) -> None:
    """Folder, root, multi-tag AND, and text search match the view oracle."""
    main_ws = seeded_gallery_db["main_ws"]
    folder_a = seeded_gallery_db["folder_a"]

    async def _verify(
        repo: UnifiedGalleryRepository, session: AsyncSession
    ) -> None:
        cases = [
            GallerySearchDto(
                workspace_id=main_ws,
                folder_id=folder_a,
                status=JobStatusEnum.COMPLETED,
                limit=20,
                offset=0,
            ),
            GallerySearchDto(
                workspace_id=main_ws,
                is_root=True,
                status=JobStatusEnum.COMPLETED,
                limit=20,
                offset=0,
            ),
            GallerySearchDto(
                workspace_id=main_ws,
                tags=["hero", "summer"],
                status=JobStatusEnum.COMPLETED,
                limit=20,
                offset=0,
            ),
            GallerySearchDto(
                workspace_id=main_ws,
                query="SUNSET",
                status=JobStatusEnum.COMPLETED,
                limit=20,
                offset=0,
            ),
            GallerySearchDto(
                workspace_id=main_ws,
                query="veo-3.0",
                status=JobStatusEnum.COMPLETED,
                limit=20,
                offset=0,
            ),
        ]
        for dto in cases:
            res = await repo.query(dto)
            ref_count, ref_keys = await _view_reference_query(session, dto)
            assert res.count == ref_count
            assert [(i.item_type, i.id) for i in res.data] == ref_keys

        tags_res = await repo.query(cases[2])
        assert [(i.item_type, i.id) for i in tags_res.data] == [
            ("source_asset", 500),
            ("media_item", 500),
        ]
        search_res = await repo.query(cases[3])
        assert [(i.item_type, i.id) for i in search_res.data] == [
            ("media_item", 501),
            ("source_asset", 501),
        ]

    await _run_with_repo(seeded_gallery_db, _verify)


@pytest.mark.anyio
async def test_postgres_types_mime_users_dates_and_visibility_flags(
    seeded_gallery_db: dict[str, Any],
) -> None:
    """Verifies model, status, MIME, user, date, visibility, and empty cases."""
    main_ws = seeded_gallery_db["main_ws"]
    user_b = seeded_gallery_db["user_b"]
    day2 = datetime.datetime(2026, 3, 2, 0, 0, tzinfo=datetime.UTC)

    async def _verify(
        repo: UnifiedGalleryRepository, session: AsyncSession
    ) -> None:
        scenarios: list[tuple[GallerySearchDto, int | None]] = [
            (
                GallerySearchDto(
                    workspace_id=main_ws, status=None, limit=20, offset=0
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    status=JobStatusEnum.PROCESSING,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    item_type="media_item",
                    model=GenerationModelEnum.VEO_3_FAST,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    item_type="source_asset",
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    mime_type=MimeTypeEnum.VIDEO_MP4,
                    status=JobStatusEnum.COMPLETED,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    mime_type=WildcardMimeTypeEnum.IMAGE_WILDCARD,
                    status=None,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    user_email="alice@example.com",
                    status=None,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    status=JobStatusEnum.COMPLETED,
                    limit=20,
                    offset=0,
                ),
                user_b,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    start_date=day2,
                    end_date=day2,
                    status=None,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    include_deleted=True,
                    status=JobStatusEnum.COMPLETED,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
            (
                GallerySearchDto(
                    workspace_id=main_ws,
                    include_external=True,
                    status=JobStatusEnum.COMPLETED,
                    limit=20,
                    offset=0,
                ),
                None,
            ),
        ]
        for dto, filter_user_id in scenarios:
            res = await repo.query(dto, user_id=filter_user_id)
            ref_count, ref_keys = await _view_reference_query(
                session, dto, user_id=filter_user_id
            )
            assert res.count == ref_count
            assert [(i.item_type, i.id) for i in res.data] == ref_keys

        contradiction = await repo.query(
            GallerySearchDto(
                workspace_id=main_ws,
                item_type="source_asset",
                model=GenerationModelEnum.GEMINI_3_PRO_IMAGE,
                limit=20,
                offset=0,
            )
        )
        assert contradiction.count == 0
        assert contradiction.data == []

        unknown_kind = await repo.query(
            GallerySearchDto(
                workspace_id=main_ws,
                item_type="unknown_type",
                limit=20,
                offset=0,
            )
        )
        assert unknown_kind.count == 0
        assert unknown_kind.data == []

    await _run_with_repo(seeded_gallery_db, _verify)


@pytest.mark.anyio
async def test_postgres_per_branch_truncation_equivalence(
    seeded_gallery_db: dict[str, Any],
) -> None:
    """Per-branch limit(offset + limit) matches view oracle when rows > top_n."""
    trunc_ws = seeded_gallery_db["trunc_ws"]

    async def _verify(
        repo: UnifiedGalleryRepository, session: AsyncSession
    ) -> None:
        for offset, limit in [(0, 3), (2, 3), (1, 4), (6, 3)]:
            dto = GallerySearchDto(
                workspace_id=trunc_ws,
                status=None,
                limit=limit,
                offset=offset,
            )
            res = await repo.query(dto)
            ref_count, ref_keys = await _view_reference_query(session, dto)
            assert res.count == ref_count == 12
            assert [(i.item_type, i.id) for i in res.data] == ref_keys

    await _run_with_repo(seeded_gallery_db, _verify)
