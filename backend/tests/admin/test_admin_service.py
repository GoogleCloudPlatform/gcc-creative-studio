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

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.admin.admin_service import AdminService
from src.admin.dto.admin_response_dto import (
    AdminOverviewStats,
    AdminMediaOverTime,
    AdminWorkspaceStats,
    AdminActiveRole,
    AdminGenerationHealth,
    AdminMonthlyActiveUsers,
)


@pytest.mark.asyncio
async def test_get_overview_stats():
    mock_repo = MagicMock()
    mock_repo.get_overview_stats = AsyncMock(
        return_value=AdminOverviewStats(
            total_users=10,
            total_workspaces=5,
            images_generated=100,
            videos_generated=50,
            audios_generated=25,
            total_media=175,
            user_uploaded_media=2,
            overall_total_media=177,
        )
    )

    service = AdminService(admin_repo=mock_repo)
    result = await service.get_overview_stats()

    assert result.total_users == 10
    assert result.total_workspaces == 5
    assert result.images_generated == 100
    assert result.videos_generated == 50
    assert result.audios_generated == 25
    assert result.total_media == 175


@pytest.mark.asyncio
async def test_get_media_over_time():
    mock_repo = MagicMock()
    mock_repo.get_media_over_time = AsyncMock(
        return_value=[
            AdminMediaOverTime(
                date="2026-04", total_generated=10, images=5, videos=3, audios=2
            )
        ]
    )

    service = AdminService(admin_repo=mock_repo)
    result = await service.get_media_over_time()
    assert len(result) == 1
    assert result[0].date == "2026-04"
    assert result[0].total_generated == 10


@pytest.mark.asyncio
async def test_get_workspace_stats():
    mock_repo = MagicMock()
    mock_repo.get_workspace_stats = AsyncMock(
        return_value=[
            AdminWorkspaceStats(
                workspace_id=1,
                workspace_name="Test Workspace",
                total_media=10,
                images=5,
                videos=3,
                audios=2,
            )
        ]
    )

    service = AdminService(admin_repo=mock_repo)
    result = await service.get_workspace_stats()
    assert len(result) == 1
    assert result[0].workspace_id == 1
    assert result[0].total_media == 10


@pytest.mark.asyncio
async def test_get_active_roles():
    mock_repo = MagicMock()
    mock_repo.get_active_roles = AsyncMock(
        return_value=[AdminActiveRole(role="ADMIN", count=2)]
    )

    service = AdminService(admin_repo=mock_repo)
    result = await service.get_active_roles()
    assert len(result) == 1
    assert result[0].role == "ADMIN"
    assert result[0].count == 2


@pytest.mark.asyncio
async def test_get_generation_health():
    mock_repo = MagicMock()
    mock_repo.get_generation_health = AsyncMock(
        return_value=[AdminGenerationHealth(status="COMPLETED", count=8)]
    )

    service = AdminService(admin_repo=mock_repo)
    result = await service.get_generation_health()
    assert len(result) == 1
    assert result[0].status == "COMPLETED"
    assert result[0].count == 8


@pytest.mark.asyncio
async def test_get_active_users_monthly():
    from unittest.mock import patch
    from datetime import datetime

    mock_repo = MagicMock()
    mock_repo.get_active_users_monthly_counts = AsyncMock(
        return_value={"2026-04": 3}
    )

    with patch("src.admin.admin_service.datetime") as mock_datetime:
        mock_datetime.today.return_value = datetime(2026, 7, 1)
        service = AdminService(admin_repo=mock_repo)
        result = await service.get_active_users_monthly()
        assert len(result) == 7  # Default 180 days should yield 7 months


@pytest.mark.asyncio
async def test_cleanup_stuck_jobs():
    mock_repo = MagicMock()
    mock_repo.cleanup_stuck_jobs = AsyncMock(return_value=5)

    service = AdminService(admin_repo=mock_repo)
    result = await service.cleanup_stuck_jobs()
    assert result == 5
