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
"""Unit and controller tests for Admin VersionService."""

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

from fastapi import status
import httpx
import pytest

from main import app
from src.admin.dto.admin_response_dto import AdminVersionInfo
from src.admin.version_service import (
    VersionService,
    clear_version_cache,
    get_version_service,
    normalize_calver_str,
    parse_calver,
)

_REPO = "GoogleCloudPlatform/gcc-creative-studio"
_TAG_URL = f"https://github.com/{_REPO}/releases/tag"


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_version_cache()
    yield
    clear_version_cache()


def _make_mock_client_factory(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    calls: list[dict[str, object]] | None = None,
) -> Callable[[], httpx.AsyncClient]:
    async def transport_handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(
                {"url": str(request.url), "headers": dict(request.headers)}
            )
        return await handler(request)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(transport_handler),
            follow_redirects=False,
        )

    return factory


class TestCalverParsing:
    """Tests for CalVer normalization and validation."""

    def test_parse_and_normalize_calver(self):
        assert parse_calver("26.11.12") == (26, 11, 12, 0)
        assert parse_calver("v26.11.12") == (26, 11, 12, 0)
        assert parse_calver(" V26.11.12.1 ") == (26, 11, 12, 1)
        assert normalize_calver_str(" v26.11.12 ") == "26.11.12"
        assert normalize_calver_str("vv26.11.12") == "v26.11.12"
        assert parse_calver("vv26.11.12") is None
        assert parse_calver("VV26.11.12") is None
        assert parse_calver("latest") is None
        assert parse_calver("26.11") is None
        assert parse_calver("26.11.12-beta") is None
        assert parse_calver("") is None
        assert parse_calver(None) is None  # type: ignore[arg-type]


class TestVersionService:
    """Tests for VersionService release checking and in-process caching."""

    @pytest.mark.asyncio
    async def test_up_to_date_without_token_omits_auth_header(self):
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.12",
                    }
                ],
            )

        service = VersionService(
            repo=_REPO,
            github_token="",
            current_version="26.11.12",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await service.get_version_info()

        assert info.current_version == "26.11.12"
        assert info.latest_version == "26.11.12"
        assert info.status == "up_to_date"
        assert info.release_url == f"{_TAG_URL}/v26.11.12"
        assert info.checked_at == "1970-01-01T00:16:40Z"
        assert "authorization" not in calls[0]["headers"]

    @pytest.mark.asyncio
    async def test_hotfix_update_available_and_token_header(self):
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12.1",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.12.1",
                    }
                ],
            )

        service = VersionService(
            repo=_REPO,
            github_token="ghp_testtoken",
            current_version="26.11.12",
            time_fn=lambda: 2000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await service.get_version_info()

        assert info.status == "update_available"
        assert info.latest_version == "26.11.12.1"
        assert calls[0]["headers"]["authorization"] == "Bearer ghp_testtoken"

    @pytest.mark.asyncio
    async def test_ahead_dev_build_is_up_to_date(self):
        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.12",
                    }
                ],
            )

        service = VersionService(
            repo=_REPO,
            current_version="26.12.01",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "up_to_date"

    @pytest.mark.asyncio
    async def test_skips_draft_prerelease_non_calver_and_builds_safe_url(self):
        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    "not-a-dict",
                    {
                        "tag_name": "v99.01.01",
                        "draft": True,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v99.01.01",
                    },
                    {
                        "tag_name": "v98.01.01",
                        "draft": False,
                        "prerelease": True,
                        "html_url": f"{_TAG_URL}/v98.01.01",
                    },
                    {
                        "tag_name": "v1.0.0-rc1",
                        "draft": False,
                        "prerelease": False,
                    },
                    {
                        "tag_name": "v26.11.15",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://evil.example.com/phish",
                    },
                    {
                        "tag_name": "v26.11.10",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.10",
                    },
                ],
            )

        service = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "update_available"
        assert info.latest_version == "26.11.15"
        assert info.release_url == f"{_TAG_URL}/v26.11.15"

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
        self, response_obj: httpx.Response
    ):
        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return response_obj

        service = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "unavailable"
        assert info.current_version == "26.11.12"
        assert info.latest_version is None

    @pytest.mark.asyncio
    async def test_timeout_returns_unavailable(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        service = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await service.get_version_info()
        assert info.status == "unavailable"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("repo", "current_version"),
        [
            ("https://evil.com/owner/repo", "26.11.12"),
            (_REPO, "not-a-calver"),
            (_REPO, "vv26.11.12"),
            ("../orgs", "26.11.12"),
            ("owner/..", "26.11.12"),
            ("./repo", "26.11.12"),
            ("owner/.", "26.11.12"),
        ],
    )
    async def test_invalid_inputs_skip_http(
        self, repo: str, current_version: str
    ):
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP should not be called")

        svc = VersionService(
            repo=repo,
            current_version=current_version,
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        assert (await svc.get_version_info()).status == "unavailable"
        assert not calls

    @pytest.mark.asyncio
    async def test_requests_per_page_100_and_finds_release_past_30_prereleases(
        self,
    ):
        calls: list[dict[str, object]] = []
        items = [
            {
                "tag_name": f"v99.01.{i:02d}",
                "draft": i % 2 == 0,
                "prerelease": i % 2 == 1,
                "html_url": f"{_TAG_URL}/v99.01.{i:02d}",
            }
            for i in range(1, 36)
        ]
        items.append(
            {
                "tag_name": "v26.11.15",
                "draft": False,
                "prerelease": False,
                "html_url": f"{_TAG_URL}/v26.11.15",
            }
        )

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=items)

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await svc.get_version_info()
        assert "per_page=100" in str(calls[0]["url"])
        assert info.status == "update_available"
        assert info.latest_version == "26.11.15"

    @pytest.mark.asyncio
    async def test_shared_cache_hit_refresh_cooldown_and_negative_ttl(self):
        now = 1000.0
        calls: list[dict[str, object]] = []
        mode = {"status": 200, "tag": "v26.11.12"}

        async def handler(unused_request: httpx.Request) -> httpx.Response:
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
                        "html_url": f"{_TAG_URL}/{tag}",
                    }
                ],
            )

        factory = _make_mock_client_factory(handler, calls)
        svc_one = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: now,
            http_client_factory=factory,
        )
        svc_two = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: now,
            http_client_factory=factory,
        )

        first = await svc_one.get_version_info()
        assert first.status == "up_to_date"
        assert len(calls) == 1

        now = 1002.0
        assert (await svc_two.get_version_info()).status == "up_to_date"
        assert len(calls) == 1

        # Refresh within 5s cooldown reuses cache.
        mode["tag"] = "v26.11.15"
        assert (
            await svc_two.get_version_info(refresh=True)
        ).status == "up_to_date"
        assert len(calls) == 1

        # Refresh after >=5s updates shared cache.
        now = 1006.0
        refreshed = await svc_two.get_version_info(refresh=True)
        assert refreshed.status == "update_available"
        assert refreshed.latest_version == "26.11.15"
        assert len(calls) == 2
        assert (await svc_one.get_version_info()).latest_version == "26.11.15"
        assert len(calls) == 2

        # Transient 500 preserves good version, flagging only refresh calls.
        now = 1012.0
        mode["status"] = 500
        preserved = await svc_one.get_version_info(refresh=True)
        assert preserved.latest_version == "26.11.15"
        assert preserved.refresh_failed is True
        assert len(calls) == 3

        now = 1014.0
        throttled = await svc_two.get_version_info(refresh=True)
        assert throttled.latest_version == "26.11.15"
        assert throttled.refresh_failed is True
        non_refresh = await svc_two.get_version_info()
        assert non_refresh.latest_version == "26.11.15"
        assert non_refresh.refresh_failed is False
        assert len(calls) == 3

        # After TTL expires and upstream still fails, enters 60s backoff.
        now = 5000.0
        assert (await svc_two.get_version_info()).latest_version == "26.11.15"
        assert len(calls) == 4
        now = 5030.0
        assert (await svc_one.get_version_info()).latest_version == "26.11.15"
        assert len(calls) == 4

        now = 5065.0
        mode["status"] = 200
        mode["tag"] = "v26.11.16"
        recovered = await svc_two.get_version_info()
        assert recovered.status == "update_available"
        assert recovered.latest_version == "26.11.16"
        assert len(calls) == 5

    @pytest.mark.asyncio
    async def test_cold_start_failure_uses_negative_ttl_and_recovers(self):
        now = 1000.0
        calls: list[dict[str, object]] = []
        mode = {"status": 500}

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            if mode["status"] != 200:
                return httpx.Response(int(mode["status"]))
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.15",
                        "draft": False,
                        "prerelease": False,
                    }
                ],
            )

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: now,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        assert (await svc.get_version_info()).status == "unavailable"
        assert len(calls) == 1

        now = 1030.0
        assert (await svc.get_version_info()).status == "unavailable"
        assert len(calls) == 1

        now = 1065.0
        mode["status"] = 200
        recovered = await svc.get_version_info()
        assert recovered.status == "update_available"
        assert recovered.latest_version == "26.11.15"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_negative_age_clock_rollback_triggers_refetch(self):
        now = 2000.0
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                    }
                ],
            )

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: now,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        await svc.get_version_info()
        assert len(calls) == 1

        now = 1990.0
        await svc.get_version_info()
        assert len(calls) == 2

        now = 1980.0
        await svc.get_version_info(refresh=True)
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_oversized_streaming_response_aborts_cleanly(self):
        chunks_yielded = 0

        class _HugeJsonStream(httpx.AsyncByteStream):
            """Yields >2 MiB of valid JSON chunks."""

            async def __aiter__(self):
                nonlocal chunks_yielded
                chunks_yielded += 1
                yield b'[{"tag_name":"v26.11.15","body":"'
                filler = b"a" * (512 * 1024)
                for _ in range(8):
                    chunks_yielded += 1
                    yield filler
                chunks_yielded += 1
                yield b'"}]'

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_HugeJsonStream())

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await svc.get_version_info()
        assert info.status == "unavailable"
        assert info.latest_version is None
        assert chunks_yielded < 10

    def test_concurrent_singleflight_across_sequential_event_loops(self):
        now = 1000.0
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                    }
                ],
            )

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            time_fn=lambda: now,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )

        async def run_pair():
            return await asyncio.gather(
                svc.get_version_info(), svc.get_version_info()
            )

        r1, r2 = asyncio.run(run_pair())
        assert r1.status == "up_to_date"
        assert r2.status == "up_to_date"
        assert len(calls) == 1

        now = 5000.0
        r3, r4 = asyncio.run(run_pair())
        assert r3.status == "up_to_date"
        assert r4.status == "up_to_date"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_default_http_client_disables_redirects(self):
        svc = get_version_service()
        assert isinstance(svc, VersionService)
        async with svc._http_client_factory() as client:
            assert client.follow_redirects is False


class TestAdminVersionController:
    """Tests for GET /api/admin/version and removal of /api/version."""

    def test_public_api_version_removed(self, api_client):
        response = api_client.get("/api/version")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "path",
        ["/api/admin/version", "/api/admin/version?refresh=true"],
    )
    def test_admin_version_requires_authentication(self, path: str):
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get(path)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize(
        "path",
        ["/api/admin/version", "/api/admin/version?refresh=true"],
    )
    def test_admin_version_forbids_regular_user(self, api_client, path: str):
        response = api_client.get(path)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_version_returns_camel_case_and_forwards_refresh(
        self, admin_client
    ):
        release_url = f"{_TAG_URL}/v26.11.15"
        mock_svc = AsyncMock()
        mock_svc.get_version_info.return_value = AdminVersionInfo(
            current_version="26.11.12",
            latest_version="26.11.15",
            status="update_available",
            release_url=release_url,
            checked_at="2026-11-15T18:05:00Z",
        )
        app.dependency_overrides[get_version_service] = lambda: mock_svc
        try:
            response = admin_client.get("/api/admin/version?refresh=true")
        finally:
            app.dependency_overrides.pop(get_version_service, None)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "currentVersion": "26.11.12",
            "latestVersion": "26.11.15",
            "status": "update_available",
            "releaseUrl": release_url,
            "checkedAt": "2026-11-15T18:05:00Z",
            "refreshFailed": False,
        }
        mock_svc.get_version_info.assert_awaited_once_with(refresh=True)

    def test_admin_version_serializes_refresh_failed_true(self, admin_client):
        mock_svc = AsyncMock()
        mock_svc.get_version_info.return_value = AdminVersionInfo(
            current_version="26.11.12",
            latest_version="26.11.12",
            status="up_to_date",
            checked_at="2026-11-15T18:05:00Z",
            refresh_failed=True,
        )
        app.dependency_overrides[get_version_service] = lambda: mock_svc
        try:
            response = admin_client.get("/api/admin/version?refresh=true")
        finally:
            app.dependency_overrides.pop(get_version_service, None)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["refreshFailed"] is True
