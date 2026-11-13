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

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
from src.auth.auth_guard import get_current_user
from src.database import get_db

_REPO = "GoogleCloudPlatform/gcc-creative-studio"
_TAG_URL = f"https://github.com/{_REPO}/releases/tag"


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
        assert normalize_calver_str("vv26.11.12") == "v26.11.12"
        assert parse_calver("vv26.11.12") is None
        assert parse_calver("VV26.11.12") is None
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

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12",
                        "name": "v26.11.12",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.12",
                        "published_at": "2026-11-12T20:00:00Z",
                    }
                ],
            )

        service = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await service.get_version_info()

        assert info.current_version == "26.11.12"
        assert info.latest_version == "26.11.12"
        assert info.status == "up_to_date"
        assert info.release_url == f"{_TAG_URL}/v26.11.12"
        assert info.release_name == "v26.11.12"
        assert info.published_at == "2026-11-12T20:00:00Z"
        assert info.checked_at == "1970-01-01T00:16:40Z"
        assert "authorization" not in calls[0]["headers"]

    @pytest.mark.asyncio
    async def test_hotfix_update_available_and_token_header(
        self, tmp_path: Path
    ):
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.12.1",
                        "name": "Hotfix 1",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.12.1",
                        "published_at": "2026-11-12T22:00:00Z",
                    }
                ],
            )

        service = VersionService(
            repo=_REPO,
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
                        "html_url": f"{_TAG_URL}/v26.11.10",
                    },
                ],
            )

        service = VersionService(
            repo=_REPO,
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
        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return response_obj

        service = VersionService(
            repo=_REPO,
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
            repo=_REPO,
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

        async def handler(unused_request: httpx.Request) -> httpx.Response:
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
            repo=_REPO,
            current_version="not-a-calver",
            cache_path=tmp_path / "cache2.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        assert (await bad_ver_svc.get_version_info()).status == "unavailable"
        assert not calls

    @pytest.mark.asyncio
    async def test_shared_cache_hit_refresh_cooldown_and_negative_ttl(
        self, tmp_path: Path
    ):
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

    @pytest.mark.asyncio
    async def test_double_v_current_version_rejected_without_http(
        self, tmp_path: Path
    ):
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP should not be called")

        svc = VersionService(
            repo=_REPO,
            current_version="vv26.11.12",
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await svc.get_version_info()
        assert info.status == "unavailable"
        assert not calls

    @pytest.mark.asyncio
    async def test_requests_per_page_100_and_finds_release_past_30_prereleases(
        self, tmp_path: Path
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
            cache_path=tmp_path / "cache.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler, calls),
        )
        info = await svc.get_version_info()
        assert "per_page=100" in str(calls[0]["url"])
        assert info.status == "update_available"
        assert info.latest_version == "26.11.15"

    @pytest.mark.asyncio
    async def test_unwritable_cache_fallback_cleans_temp_and_ignores_stale_disk(
        self, tmp_path: Path
    ):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    f"{_REPO}|26.11.12": {
                        "fetched_at": 990.0,
                        "info": {
                            "current_version": "26.11.12",
                            "latest_version": "26.01.01",
                            "status": "up_to_date",
                            "checked_at": "1970-01-01T00:16:30Z",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        now = 1000.0
        tag = "v26.11.15"
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
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
        svc1 = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=cache_file,
            time_fn=lambda: now,
            http_client_factory=factory,
        )
        svc2 = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=cache_file,
            time_fn=lambda: now,
            http_client_factory=factory,
        )

        with patch(
            "src.admin.version_service.os.replace",
            side_effect=PermissionError("read-only"),
        ):
            res1 = await svc1.get_version_info(refresh=True)
        assert res1.latest_version == "26.11.15"
        assert len(calls) == 1
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
        assert not leftovers

        # Memory cache takes precedence over stale disk file while unwritable
        now = 1002.0
        res2 = await svc2.get_version_info()
        assert res2.latest_version == "26.11.15"
        assert len(calls) == 1

        # Once disk becomes writable again, refresh persists and recovers
        now = 5000.0
        tag = "v26.11.16"
        res3 = await svc2.get_version_info()
        assert res3.latest_version == "26.11.16"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_corrupt_nan_bool_tampered_url_and_symlink_cache_recovery(
        self, tmp_path: Path
    ):
        calls: list[dict[str, object]] = []

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v26.11.15",
                        "draft": False,
                        "prerelease": False,
                        "html_url": f"{_TAG_URL}/v26.11.15",
                    }
                ],
            )

        factory = _make_mock_client_factory(handler, calls)
        cache_key = f"{_REPO}|26.11.12"
        base_info = {
            "current_version": "26.11.12",
            "latest_version": "26.11.12",
            "status": "up_to_date",
            "release_url": f"{_TAG_URL}/v26.11.12",
            "checked_at": "1970-01-01T00:16:40Z",
        }
        nan_entry = {cache_key: {"fetched_at": float("nan"), "info": base_info}}
        bad_payloads = [
            "{not-json",
            json.dumps(nan_entry),
            json.dumps({cache_key: {"fetched_at": True, "info": base_info}}),
            json.dumps(
                {
                    cache_key: {
                        "fetched_at": 999.0,
                        "info": {
                            **base_info,
                            "release_url": "https://evil.example.com/phish",
                        },
                    }
                }
            ),
            json.dumps(
                {
                    cache_key: {
                        "fetched_at": 999.0,
                        "info": {
                            **base_info,
                            "release_url": (
                                f"https://github.com/{_REPO}/../../evil"
                            ),
                        },
                    }
                }
            ),
        ]

        for idx, content in enumerate(bad_payloads):
            cache_file = tmp_path / f"bad_{idx}.json"
            cache_file.write_text(content, encoding="utf-8")
            svc = VersionService(
                repo=_REPO,
                current_version="26.11.12",
                cache_path=cache_file,
                time_fn=lambda: 1000.0,
                http_client_factory=factory,
            )
            info = await svc.get_version_info()
            assert info.latest_version == "26.11.15"

        assert len(calls) == len(bad_payloads)

        # Symlink cache is ignored on read via O_NOFOLLOW; target stays intact
        target_file = tmp_path / "secret_target.json"
        target_file.write_text("untouched", encoding="utf-8")
        symlink_cache = tmp_path / "symlink_cache.json"
        os.symlink(target_file, symlink_cache)

        sym_svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=symlink_cache,
            time_fn=lambda: 1000.0,
            http_client_factory=factory,
        )
        sym_info = await sym_svc.get_version_info()
        assert sym_info.latest_version == "26.11.15"
        assert len(calls) == len(bad_payloads) + 1
        assert target_file.read_text(encoding="utf-8") == "untouched"

    @pytest.mark.asyncio
    async def test_negative_age_clock_rollback_triggers_refetch(
        self, tmp_path: Path
    ):
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
                        "html_url": f"{_TAG_URL}/v26.11.12",
                    }
                ],
            )

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=tmp_path / "clock.json",
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
    async def test_rejects_dot_segment_repos_and_unsafe_release_urls(
        self, tmp_path: Path
    ):
        calls: list[dict[str, object]] = []

        async def fail_if_called(unused_req: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP should not be called")

        for bad_repo in ("../orgs", "owner/..", "./repo", "owner/."):
            svc = VersionService(
                repo=bad_repo,
                current_version="26.11.12",
                cache_path=tmp_path / f"repo_{abs(hash(bad_repo))}.json",
                time_fn=lambda: 1000.0,
                http_client_factory=_make_mock_client_factory(
                    fail_if_called, calls
                ),
            )
            assert (await svc.get_version_info()).status == "unavailable"
        assert not calls

        unsafe_urls = [
            f"https://github.com/{_REPO}/../../evil",
            f"https://github.com/{_REPO}/./evil",
            f"https://github.com/{_REPO}/releases\\evil",
            f"{_TAG_URL}/v1 evil",
            f"https://github.com/{_REPO}-evil/releases/tag/v26.11.15",
        ]
        for idx, bad_url in enumerate(unsafe_urls):

            async def handler(
                unused_request: httpx.Request, url_val: str = bad_url
            ) -> httpx.Response:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "tag_name": "v26.11.15",
                            "draft": False,
                            "prerelease": False,
                            "html_url": url_val,
                        }
                    ],
                )

            svc = VersionService(
                repo=_REPO,
                current_version="26.11.12",
                cache_path=tmp_path / f"url_{idx}.json",
                time_fn=lambda: 1000.0,
                http_client_factory=_make_mock_client_factory(handler),
            )
            info = await svc.get_version_info()
            assert info.status == "update_available"
            assert info.release_url is None

    @pytest.mark.asyncio
    async def test_oversized_streaming_response_aborts_cleanly(
        self, tmp_path: Path
    ):
        chunks_yielded = 0

        class _HugeValidJsonStream(httpx.AsyncByteStream):
            """Yields >2 MiB of valid JSON chunks."""

            async def __aiter__(self):
                nonlocal chunks_yielded
                chunks_yielded += 1
                yield (
                    b'[{"tag_name":"v26.11.15","draft":false,'
                    b'"prerelease":false,"body":"'
                )
                filler = b"a" * (512 * 1024)
                for _ in range(8):
                    chunks_yielded += 1
                    yield filler
                chunks_yielded += 1
                yield b'"}]'

        async def handler(unused_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_HugeValidJsonStream())

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=tmp_path / "huge.json",
            time_fn=lambda: 1000.0,
            http_client_factory=_make_mock_client_factory(handler),
        )
        info = await svc.get_version_info()
        assert info.status == "unavailable"
        assert info.latest_version is None
        assert chunks_yielded < 10

    def test_concurrent_singleflight_across_sequential_event_loops(
        self, tmp_path: Path
    ):
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
                        "html_url": f"{_TAG_URL}/v26.11.12",
                    }
                ],
            )

        svc = VersionService(
            repo=_REPO,
            current_version="26.11.12",
            cache_path=tmp_path / "loops.json",
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

        # Second event loop after TTL must acquire its own loop-bound lock
        now = 5000.0
        r3, r4 = asyncio.run(run_pair())
        assert r3.status == "up_to_date"
        assert r4.status == "up_to_date"
        assert len(calls) == 2


class TestAdminVersionController:
    """Tests for GET /api/admin/version and removal of /api/version.

    Uses ``TestClient(app)`` without entering ``lifespan`` so running in
    ``tests/admin/`` (alphabetically before ``tests/auth/`` and ``tests/e2e/``)
    does not register global post-auth DB hooks on the shared engine pool.
    """

    def test_public_api_version_removed(self, mock_user, db_session_mock):
        async def override_get_db():
            yield db_session_mock

        prev_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = override_get_db
        try:
            response = TestClient(app).get("/api/version")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(prev_overrides)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "path",
        ["/api/admin/version", "/api/admin/version?refresh=true"],
    )
    def test_admin_version_requires_authentication(
        self, db_session_mock, path: str
    ):
        async def override_get_db():
            yield db_session_mock

        prev_overrides = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = override_get_db
        try:
            response = TestClient(app).get(path)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(prev_overrides)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize(
        "path",
        ["/api/admin/version", "/api/admin/version?refresh=true"],
    )
    def test_admin_version_forbids_regular_user(
        self, mock_user, db_session_mock, path: str
    ):
        async def override_get_db():
            yield db_session_mock

        prev_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = override_get_db
        try:
            response = TestClient(app).get(path)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(prev_overrides)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_version_returns_camel_case_and_forwards_refresh(
        self, mock_admin, db_session_mock
    ):
        async def override_get_db():
            yield db_session_mock

        release_url = f"{_TAG_URL}/v26.11.15"
        mock_svc = AsyncMock()
        mock_svc.get_version_info.return_value = AdminVersionInfo(
            current_version="26.11.12",
            latest_version="26.11.15",
            status="update_available",
            release_url=release_url,
            release_name="v26.11.15",
            published_at="2026-11-15T18:00:00Z",
            checked_at="2026-11-15T18:05:00Z",
        )
        prev_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_admin
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_version_service] = lambda: mock_svc
        try:
            response = TestClient(app).get("/api/admin/version?refresh=true")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(prev_overrides)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "currentVersion": "26.11.12",
            "latestVersion": "26.11.15",
            "status": "update_available",
            "releaseUrl": release_url,
            "releaseName": "v26.11.15",
            "publishedAt": "2026-11-15T18:00:00Z",
            "checkedAt": "2026-11-15T18:05:00Z",
        }
        mock_svc.get_version_info.assert_awaited_once_with(refresh=True)
