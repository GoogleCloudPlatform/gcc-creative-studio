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
"""Tests for admin version checking service and controller endpoint."""

from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import status
from fastapi.testclient import TestClient
import httpx
import pytest

from main import app
from src.admin.dto.admin_response_dto import AdminVersionInfo
from src.admin.version_service import (
    VersionService,
    get_version_service,
    normalize_calver_str,
    parse_calver,
)


def _make_mock_client_factory(
    handler,
    calls: list[dict[str, object]] | None = None,
):
    def factory() -> httpx.AsyncClient:
        async def _dispatch(request: httpx.Request) -> httpx.Response:
            if calls is not None:
                calls.append(
                    {
                        "url": str(request.url),
                        "headers": dict(request.headers),
                    }
                )
            return await handler(request)

        return httpx.AsyncClient(transport=httpx.MockTransport(_dispatch))

    return factory


class TestParseCalver:
    """Tests for CalVer normalization and parsing."""

    def test_parses_three_and_four_part_versions(self):
        assert parse_calver("26.11.12") == (26, 11, 12, 0)
        assert parse_calver("v26.11.12") == (26, 11, 12, 0)
        assert parse_calver(" V26.11.12.1 ") == (26, 11, 12, 1)
        assert normalize_calver_str(" v26.11.12 ") == "26.11.12"

    def test_rejects_non_calver_strings(self):
        assert parse_calver("latest") is None
        assert parse_calver("26.11") is None
        assert parse_calver("26.11.12-beta") is None
        assert parse_calver("") is None
        assert parse_calver(None) is None  # type: ignore[arg-type]


class TestVersionService:
    """Tests for VersionService release checking and caching."""

    @pytest.mark.asyncio
    async def test_up_to_date_normalizes_leading_v(self, tmp_path: Path):
        calls: list[dict[str, object]] = []

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12",
                        "published_at": "2026-11-12T20:00:00Z",
                    }
                ],
            )

        service = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await service.get_version_info()

        assert info.current_version == "26.11.12"
        assert info.latest_version == "26.11.12"
        assert info.status == "up_to_date"
        assert info.release_url == (
            "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12"
        )
        assert info.release_name == "v26.11.12"
        assert info.published_at == "2026-11-12T20:00:00Z"
        assert info.checked_at == "1970-01-01T00:16:40Z"
        assert "authorization" not in calls[0]["headers"]

    @pytest.mark.asyncio
    async def test_hotfix_update_available_and_token_header(
        self, tmp_path: Path
    ):
        calls: list[dict[str, object]] = []

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12.1",
                        "name": "Hotfix 1",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12.1",
                        "published_at": "2026-11-12T22:00:00Z",
                    }
                ],
            )

        service = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            github_token="ghp_testtoken",
            current_version="26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 2000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await service.get_version_info()

        assert info.status == "update_available"
        assert info.latest_version == "26.11.12.1"
        assert calls[0]["headers"]["authorization"] == "Bearer ghp_testtoken"

    @pytest.mark.asyncio
    async def test_ahead_dev_build_is_up_to_date(self, tmp_path: Path):
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12",
                    }
                ],
            )

        service = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.12.01",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "up_to_date"

    @pytest.mark.asyncio
    async def test_skips_draft_prerelease_non_calver_and_strips_bad_url(
        self, tmp_path: Path
    ):
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    "not-a-dict",
                    {
                        "tag_name": "v99.01.01",
                        "draft": True,
                        "prerelease": False,
                        "html_url": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v99.01.01",
                    },
                    {
                        "tag_name": "v98.01.01",
                        "draft": False,
                        "prerelease": True,
                        "html_url": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v98.01.01",
                    },
                    {
                        "tag_name": "v1.0.0-rc1",
                        "draft": False,
                        "prerelease": False,
                    },
                    {
                        "tag_name": "v26.11.15",
                        "name": " ",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://evil.example.com/phish",
                        "published_at": " ",
                    },
                    {
                        "tag_name": "v26.11.10",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.10",
                    },
                ],
            )

        service = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "update_available"
        assert info.latest_version == "26.11.15"
        assert info.release_url is None
        assert info.release_name is None
        assert info.published_at is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response_obj",
        [
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"message": "unexpected object"}),
            httpx.Response(200, content=b"{not-json"),
            httpx.Response(403, json={"message": "rate limit"}),
            httpx.Response(500, text="server error"),
        ],
    )
    async def test_graceful_unavailable_on_empty_or_bad_responses(
        self, tmp_path: Path, response_obj: httpx.Response
    ):
        async def handler(_request: httpx.Request) -> httpx.Response:
            return response_obj

        service = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "unavailable"
        assert info.current_version == "26.11.12"
        assert info.latest_version is None

    @pytest.mark.asyncio
    async def test_timeout_returns_unavailable(self, tmp_path: Path):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        service = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "unavailable"

    @pytest.mark.asyncio
    async def test_invalid_repo_or_current_version_skips_http(
        self, tmp_path: Path
    ):
        calls: list[dict[str, object]] = []

        async def handler(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP should not be called")

        bad_repo_svc = VersionService(
            repo="https://evil.com/owner/repo",
            current_version="26.11.12",
            cache_path=tmp_path / "cache1.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        assert (await bad_repo_svc.get_version_info()).status == "unavailable"

        bad_ver_svc = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="not-a-calver",
            cache_path=tmp_path / "cache2.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        assert (await bad_ver_svc.get_version_info()).status == "unavailable"
        assert calls == []

    @pytest.mark.asyncio
    async def test_shared_cache_hit_refresh_cooldown_and_negative_ttl(
        self, tmp_path: Path
    ):
        now = 1000.0
        calls: list[dict[str, object]] = []
        mode = {"status": 200, "tag": "v26.11.12"}

        async def handler(_request: httpx.Request) -> httpx.Response:
            if mode["status"] != 200:
                return httpx.Response(int(mode["status"]))
            tag = str(mode["tag"])
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": tag,
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/{tag}",
                    }
                ],
            )

        cache_file = tmp_path / "shared_cache.json"
        factory = _make_mock_client_factory(handler, calls)

        worker_one = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.11.12",
            cache_path=cache_file,
            time_fn=lambda: now,
            http_client_factory=factory,
        )
        worker_two = VersionService(
            repo="GoogleCloudPlatform/gcc-creative-studio",
            current_version="26.11.12",
            cache_path=cache_file,
            time_fn=lambda: now,
            http_client_factory=factory,
        )

        first = await worker_one.get_version_info()
        assert first.status == "up_to_date"
        assert len(calls) == 1

        # Separate worker instance reuses shared JSON cache within 1h.
        now = 1002.0
        second = await worker_two.get_version_info()
        assert second.status == "up_to_date"
        assert len(calls) == 1

        # Refresh within <5s cooldown reuses cached value.
        mode["tag"] = "v26.11.15"
        cooldown_res = await worker_two.get_version_info(refresh=True)
        assert cooldown_res.status == "up_to_date"
        assert len(calls) == 1

        # Refresh after >=5s bypasses 1h cache and updates shared cache.
        now = 1006.0
        refreshed = await worker_two.get_version_info(refresh=True)
        assert refreshed.status == "update_available"
        assert refreshed.latest_version == "26.11.15"
        assert len(calls) == 2

        # Worker one sees the refreshed value from disk cache without HTTP call.
        assert (
            await worker_one.get_version_info()
        ).latest_version == "26.11.15"
        assert len(calls) == 2

        # Negative cache expires after 60s.
        now = 1012.0
        mode["status"] = 500
        unavail = await worker_one.get_version_info(refresh=True)
        assert unavail.status == "unavailable"
        assert len(calls) == 3

        now = 1050.0
        assert (await worker_two.get_version_info()).status == "unavailable"
        assert len(calls) == 3

        now = 1075.0
        mode["status"] = 200
        recovered = await worker_two.get_version_info()
        assert recovered.status == "update_available"
        assert len(calls) == 4


class TestAdminVersionController:
    """Tests for GET /api/admin/version and removal of /api/version."""

    def test_public_api_version_removed(self, api_client):
        response = api_client.get("/api/version")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_admin_version_requires_authentication(self):
        app.dependency_overrides.clear()
        with TestClient(app) as unauth_client:
            response = unauth_client.get("/api/admin/version")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_admin_version_forbids_regular_user(self, api_client):
        response = api_client.get("/api/admin/version")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_version_returns_camel_case_and_forwards_refresh(
        self, admin_client
    ):
        mock_svc = AsyncMock()
        mock_svc.get_version_info.return_value = AdminVersionInfo(
            current_version="26.11.12",
            latest_version="26.11.15",
            status="update_available",
            release_url="https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15",
            release_name="v26.11.15",
            published_at="2026-11-15T18:00:00Z",
            checked_at="2026-11-15T18:05:00Z",
        )
        app.dependency_overrides[get_version_service] = lambda: mock_svc

        response = admin_client.get("/api/admin/version?refresh=true")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "currentVersion": "26.11.12",
            "latestVersion": "26.11.15",
            "status": "update_available",
            "releaseUrl": "https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15",
            "releaseName": "v26.11.15",
            "publishedAt": "2026-11-15T18:00:00Z",
            "checkedAt": "2026-11-15T18:05:00Z",
        }
        mock_svc.get_version_info.assert_awaited_once_with(refresh=True)
