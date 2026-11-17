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

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, update
from src.database import get_db
from src.users.user_model import User
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceScopeEnum,
)
from src.source_assets.schema.source_asset_model import SourceAsset
from src.common.schema.media_item_model import MediaItem, JobStatusEnum
from src.admin.dto.admin_response_dto import (
    AdminOverviewStats,
    AdminMediaOverTime,
    AdminWorkspaceStats,
    AdminActiveRole,
    AdminGenerationHealth,
)
from datetime import datetime, timedelta, timezone


class AdminRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    def _apply_date_filters(
        self, query, model, start_date: str | None, end_date: str | None
    ):
        if start_date:
            query = query.where(
                model.created_at >= datetime.strptime(start_date, "%Y-%m-%d")
            )
        if end_date:
            query = query.where(
                model.created_at
                < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            )
        return query

    async def get_overview_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> AdminOverviewStats:
        users_query = select(func.count(User.id))
        workspaces_query = select(func.count(Workspace.id)).where(
            Workspace.scope != WorkspaceScopeEnum.PERSONAL.value
        )
        uploaded_query = select(func.count(SourceAsset.id)).where(
            SourceAsset.promoted_from_source_asset_id.is_(None)
        )

        if end_date:
            users_query = users_query.where(
                User.created_at
                < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            )
            workspaces_query = workspaces_query.where(
                Workspace.created_at
                < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            )

        uploaded_query = self._apply_date_filters(
            uploaded_query, SourceAsset, start_date, end_date
        )

        scalar_users = (await self.db.execute(users_query)).scalar_one()
        scalar_workspaces = (
            await self.db.execute(workspaces_query)
        ).scalar_one()
        scalar_uploaded = (await self.db.execute(uploaded_query)).scalar_one()

        query_media = select(
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("image/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("images"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("video/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("videos"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("audio/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("audios"),
        ).where(MediaItem.promoted_from_media_item_id.is_(None))
        query_media = self._apply_date_filters(
            query_media, MediaItem, start_date, end_date
        )
        media_counts = (await self.db.execute(query_media)).first()

        images = int(media_counts.images or 0) if media_counts else 0
        videos = int(media_counts.videos or 0) if media_counts else 0
        audios = int(media_counts.audios or 0) if media_counts else 0

        return AdminOverviewStats(
            total_users=scalar_users or 0,
            total_workspaces=scalar_workspaces or 0,
            images_generated=images,
            videos_generated=videos,
            audios_generated=audios,
            total_media=images + videos + audios,
            user_uploaded_media=scalar_uploaded or 0,
            overall_total_media=(images + videos + audios)
            + (scalar_uploaded or 0),
        )

    async def get_media_over_time(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminMediaOverTime]:
        query = select(
            func.date(MediaItem.created_at).label("date"),
            func.sum(func.cardinality(MediaItem.gcs_uris)).label("count"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("image/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("images"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("video/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("videos"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("audio/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("audios"),
        ).where(MediaItem.promoted_from_media_item_id.is_(None))
        query = self._apply_date_filters(query, MediaItem, start_date, end_date)
        query = query.group_by(func.date(MediaItem.created_at)).order_by(
            func.date(MediaItem.created_at)
        )
        media_over_time = (await self.db.execute(query)).all()

        return [
            AdminMediaOverTime(
                date=str(row.date),
                total_generated=row.count,
                images=int(row.images or 0),
                videos=int(row.videos or 0),
                audios=int(row.audios or 0),
            )
            for row in media_over_time
        ]

    async def get_workspace_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminWorkspaceStats]:
        stmt = select(
            MediaItem.workspace_id,
            Workspace.name.label("workspace_name"),
            func.sum(func.cardinality(MediaItem.gcs_uris)).label("count"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("image/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("images"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("video/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("videos"),
            func.sum(
                case(
                    (
                        MediaItem.mime_type.like("audio/%"),
                        func.cardinality(MediaItem.gcs_uris),
                    ),
                    else_=0,
                )
            ).label("audios"),
        ).join(Workspace, Workspace.id == MediaItem.workspace_id)
        stmt = stmt.where(Workspace.scope != WorkspaceScopeEnum.PERSONAL.value)

        stmt = self._apply_date_filters(stmt, MediaItem, start_date, end_date)

        stmt = (
            stmt.group_by(MediaItem.workspace_id, Workspace.name)
            .order_by(func.sum(func.cardinality(MediaItem.gcs_uris)).desc())
            .limit(10)
        )

        workspace_stats = (await self.db.execute(stmt)).all()

        return [
            AdminWorkspaceStats(
                workspace_id=row.workspace_id,
                workspace_name=row.workspace_name,
                total_media=row.count,
                images=int(row.images or 0),
                videos=int(row.videos or 0),
                audios=int(row.audios or 0),
            )
            for row in workspace_stats
        ]

    async def get_active_roles(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminActiveRole]:
        active_emails = (
            select(MediaItem.user_email)
            .where(MediaItem.promoted_from_media_item_id.is_(None))
            .distinct()
        )
        active_emails = self._apply_date_filters(
            active_emails, MediaItem, start_date, end_date
        )

        query = (
            select(
                func.unnest(User.roles).label("role"),
                func.count(func.distinct(User.id)).label("count"),
            )
            .where(User.email.in_(active_emails))
            .group_by("role")
        )

        roles_stats = (await self.db.execute(query)).all()

        return [
            AdminActiveRole(role=row.role, count=row.count)
            for row in roles_stats
        ]

    async def get_generation_health(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminGenerationHealth]:
        query = select(
            MediaItem.status.label("status"),
            func.count(MediaItem.id).label("count"),
        ).where(MediaItem.promoted_from_media_item_id.is_(None))
        query = self._apply_date_filters(query, MediaItem, start_date, end_date)
        query = query.group_by(MediaItem.status)
        health_stats = (await self.db.execute(query)).all()

        return [
            AdminGenerationHealth(status=row.status, count=row.count)
            for row in health_stats
        ]

    async def get_active_users_monthly_counts(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, int]:
        query = select(
            func.to_char(MediaItem.created_at, "YYYY-MM").label("month"),
            func.count(func.distinct(MediaItem.user_email)).label("count"),
        ).where(MediaItem.promoted_from_media_item_id.is_(None))
        query = self._apply_date_filters(query, MediaItem, start_date, end_date)
        query = query.group_by("month").order_by("month")
        results = (await self.db.execute(query)).all()
        return {row.month: row.count for row in results}

    async def cleanup_stuck_jobs(self) -> int:
        """Marks processing jobs older than 1 hour as stopped."""
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        query = (
            update(MediaItem)
            .where(MediaItem.status == JobStatusEnum.PROCESSING.value)
            .where(MediaItem.created_at < one_hour_ago)
            .values(status=JobStatusEnum.STOPPED.value)
        )
        result = await self.db.execute(query)
        await self.db.commit()
        return result.rowcount
