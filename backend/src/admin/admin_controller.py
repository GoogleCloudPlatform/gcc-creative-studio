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

from fastapi import APIRouter, Depends
from src.auth.auth_guard import RoleChecker
from src.users.user_model import UserRoleEnum
from src.admin.admin_service import AdminService
from src.admin.dto.admin_response_dto import (
    AdminOverviewStats,
    AdminMediaOverTime,
    AdminWorkspaceStats,
    AdminActiveRole,
    AdminGenerationHealth,
    AdminMonthlyActiveUsers,
    AdminVersionInfo,
)
from src.admin.version_service import VersionService, get_version_service

router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Dashboard"],
    dependencies=[Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN]))],
)


@router.get("/overview-stats", response_model=AdminOverviewStats)
async def get_overview_stats(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves platform overview statistics.

    Includes total users, workspaces, and media generated counts.
    """
    return await admin_service.get_overview_stats(
        start_date=start_date, end_date=end_date
    )


@router.get("/media-over-time", response_model=list[AdminMediaOverTime])
async def get_media_over_time(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves media generation breakdown over time.

    Grouped by date and media type.
    """
    return await admin_service.get_media_over_time(
        start_date=start_date, end_date=end_date
    )


@router.get("/workspace-stats", response_model=list[AdminWorkspaceStats])
async def get_workspace_stats(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves statistics per workspace.

    Includes total media and breakdown by type for each workspace.
    """
    return await admin_service.get_workspace_stats(
        start_date=start_date, end_date=end_date
    )


@router.get("/active-roles", response_model=list[AdminActiveRole])
async def get_active_roles(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves distribution of active user roles.

    Counts users assigned to each role.
    """
    return await admin_service.get_active_roles(
        start_date=start_date, end_date=end_date
    )


@router.get("/generation-health", response_model=list[AdminGenerationHealth])
async def get_generation_health(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves health statistics for media generation jobs.

    Counts jobs by status (completed, failed, processing, stopped).
    """
    return await admin_service.get_generation_health(
        start_date=start_date, end_date=end_date
    )


@router.get(
    "/active-users-monthly", response_model=list[AdminMonthlyActiveUsers]
)
async def get_active_users_monthly(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves monthly active users evolution.

    Counts distinct users active per month.
    """
    return await admin_service.get_active_users_monthly(
        start_date=start_date, end_date=end_date
    )


@router.post("/cleanup-stuck-jobs")
async def cleanup_stuck_jobs(admin_service: AdminService = Depends()):
    """Cleans up stuck media generation jobs.

    Marks jobs with 'processing' status that are older than 1 hour as 'stopped'.
    """
    count = await admin_service.cleanup_stuck_jobs()
    return {"message": f"Cleaned up {count} stuck jobs", "count": count}


@router.get("/version", response_model=AdminVersionInfo)
async def get_version_info(
    refresh: bool = False,
    version_service: VersionService = Depends(get_version_service),
):
    """Retrieves installed application version and GitHub release status."""
    return await version_service.get_version_info(refresh=refresh)
