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
"""Admin version checking service against GitHub Releases."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any
import weakref

import httpx

from src.admin.dto.admin_response_dto import (
    AdminVersionInfo,
    VersionStatusLiteral,
)
from src.config.config_service import config_service
from src.version import APP_VERSION

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600.0
NEGATIVE_CACHE_TTL_SECONDS = 60.0
MIN_REFRESH_INTERVAL_SECONDS = 5.0
DEFAULT_CACHE_PATH = Path("/tmp/creative_studio_version_cache.json")
_REQUEST_TIMEOUT_SECONDS = 5.0
_RELEASES_PER_PAGE = 100
_MAX_CACHE_BYTES = 65_536
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_CALVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")
_REPO_RE = re.compile(
    r"^(?!\.\.?(?:/|$))[A-Za-z0-9_.-]{1,100}/"
    r"(?!\.\.?(?:/|$))[A-Za-z0-9_.-]{1,100}$"
)
_UNSAFE_URL_RE = re.compile(r"(?:^|/)\.\.?(?:/|$)|[\\\s]")

_PROCESS_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = weakref.WeakKeyDictionary()
_IN_MEMORY_CACHE: dict[str, dict[str, Any]] = {}
_UNWRITABLE_CACHE_PATHS: set[str] = set()


def _get_process_lock() -> asyncio.Lock:
    """Returns the singleflight lock bound to the active event loop."""
    loop = asyncio.get_running_loop()
    lock = _PROCESS_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _PROCESS_LOCKS[loop] = lock
    return lock


def normalize_calver_str(raw: str) -> str:
    """Strips whitespace and at most one leading 'v'/'V' prefix."""
    stripped = raw.strip()
    return stripped[1:] if stripped[:1] in ("v", "V") else stripped


def parse_calver(raw: str) -> tuple[int, int, int, int] | None:
    """Parses a 3- or 4-part CalVer string into a comparable 4-tuple."""
    if not isinstance(raw, str):
        return None
    normalized = normalize_calver_str(raw)
    match = _CALVER_RE.fullmatch(normalized)
    if not match:
        return None
    major, minor, patch, hotfix = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        int(hotfix) if hotfix is not None else 0,
    )


def _iso_utc_from_epoch(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class VersionService:
    """Checks installed version against published GitHub Releases."""

    def __init__(
        self,
        repo: str | None = None,
        github_token: str | None = None,
        current_version: str | None = None,
        cache_path: Path | None = None,
        time_fn: Callable[[], float] = time.time,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        raw_repo = config_service.GITHUB_RELEASE_REPO if repo is None else repo
        raw_token = (
            config_service.GITHUB_TOKEN
            if github_token is None
            else github_token
        )
        raw_current = (
            APP_VERSION if current_version is None else current_version
        )
        self._repo = raw_repo.strip()
        self._github_token = raw_token.strip()
        self._current_tuple = parse_calver(raw_current)
        self._current_version = (
            normalize_calver_str(raw_current)
            if isinstance(raw_current, str)
            else ""
        )
        self._cache_path = (
            DEFAULT_CACHE_PATH if cache_path is None else cache_path
        )
        self._time_fn = time_fn
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(
                timeout=_REQUEST_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        )

    def _cache_key(self) -> str:
        return f"{self._repo}|{self._current_version}"

    def _is_valid_release_url(self, url: object) -> bool:
        return (
            isinstance(url, str)
            and url.startswith(f"https://github.com/{self._repo}/")
            and not _UNSAFE_URL_RE.search(url)
        )

    def _read_cache_store(self) -> dict[str, Any]:
        cache_id = str(self._cache_path)
        if cache_id in _UNWRITABLE_CACHE_PATHS:
            return dict(_IN_MEMORY_CACHE.get(cache_id, {}))

        fd = -1
        try:
            fd = os.open(
                self._cache_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            return dict(_IN_MEMORY_CACHE.get(cache_id, {}))
        except OSError as exc:
            logger.warning(
                "Failed to read version cache %s; using memory fallback: %s",
                self._cache_path,
                exc,
            )
            return dict(_IN_MEMORY_CACHE.get(cache_id, {}))

        try:
            st = os.fstat(fd)
            if (
                not stat.S_ISREG(st.st_mode)
                or st.st_uid != os.getuid()
                or st.st_size > _MAX_CACHE_BYTES
            ):
                logger.warning(
                    "Ignoring untrusted or oversized version cache %s",
                    self._cache_path,
                )
                return dict(_IN_MEMORY_CACHE.get(cache_id, {}))
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                fd = -1
                parsed = json.load(handle)
            if isinstance(parsed, dict):
                return parsed
            return {}
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            logger.warning(
                "Failed to read version cache %s; using memory fallback: %s",
                self._cache_path,
                exc,
            )
            return dict(_IN_MEMORY_CACHE.get(cache_id, {}))
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _write_cache_store(self, store: dict[str, Any]) -> None:
        cache_id = str(self._cache_path)
        _IN_MEMORY_CACHE[cache_id] = dict(store)
        tmp_path: str | None = None
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._cache_path.parent),
                prefix=f".{self._cache_path.name}.",
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                json.dump(store, tmp_file)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._cache_path)
            _UNWRITABLE_CACHE_PATHS.discard(cache_id)
        except OSError as exc:
            _UNWRITABLE_CACHE_PATHS.add(cache_id)
            logger.warning(
                "Failed to write version cache %s; kept in memory: %s",
                self._cache_path,
                exc,
            )
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _get_cached_entry(
        self,
    ) -> tuple[float, AdminVersionInfo] | None:
        store = self._read_cache_store()
        entry = store.get(self._cache_key())
        if not isinstance(entry, dict):
            return None
        fetched_at = entry.get("fetched_at")
        raw_info = entry.get("info")
        if (
            isinstance(fetched_at, bool)
            or not isinstance(fetched_at, (int, float))
            or not math.isfinite(fetched_at)
            or not isinstance(raw_info, dict)
        ):
            return None
        try:
            info = AdminVersionInfo.model_validate(raw_info)
        except ValueError:
            return None
        if info.release_url is not None and not self._is_valid_release_url(
            info.release_url
        ):
            return None
        return float(fetched_at), info

    def _store_cached_entry(
        self, fetched_at: float, info: AdminVersionInfo
    ) -> None:
        store = self._read_cache_store()
        store[self._cache_key()] = {
            "fetched_at": fetched_at,
            "info": info.model_dump(),
        }
        self._write_cache_store(store)

    def _unavailable(self, checked_at: str) -> AdminVersionInfo:
        return AdminVersionInfo(
            current_version=self._current_version,
            status="unavailable",
            checked_at=checked_at,
        )

    async def _fetch_and_evaluate(self, now: float) -> AdminVersionInfo:
        checked_at = _iso_utc_from_epoch(now)
        if self._current_tuple is None:
            logger.warning(
                "Invalid installed CalVer string: %r",
                self._current_version,
            )
            return self._unavailable(checked_at)

        if not _REPO_RE.fullmatch(self._repo):
            logger.warning("Invalid GITHUB_RELEASE_REPO format: %r", self._repo)
            return self._unavailable(checked_at)

        url = (
            f"https://api.github.com/repos/{self._repo}"
            f"/releases?per_page={_RELEASES_PER_PAGE}"
        )
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gcc-creative-studio-version-checker",
        }
        if self._github_token:
            headers["Authorization"] = f"Bearer {self._github_token}"

        chunks: list[bytes] = []
        total_bytes = 0
        try:
            async with self._http_client_factory() as client:
                async with client.stream(
                    "GET", url, headers=headers
                ) as response:
                    if response.status_code != 200:
                        logger.warning(
                            "GitHub release check returned HTTP %s for %s",
                            response.status_code,
                            self._repo,
                        )
                        return self._unavailable(checked_at)

                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > _MAX_RESPONSE_BYTES:
                            logger.warning(
                                "GitHub release body exceeded %s bytes for %s",
                                _MAX_RESPONSE_BYTES,
                                self._repo,
                            )
                            return self._unavailable(checked_at)
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            logger.warning(
                "GitHub release check failed for %s: %s",
                self._repo,
                exc,
            )
            return self._unavailable(checked_at)

        try:
            payload = json.loads(b"".join(chunks))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning(
                "GitHub release check returned invalid JSON for %s: %s",
                self._repo,
                exc,
            )
            return self._unavailable(checked_at)

        if not isinstance(payload, list):
            logger.warning(
                "GitHub release check returned non-list payload for %s",
                self._repo,
            )
            return self._unavailable(checked_at)

        best_tuple: tuple[int, int, int, int] | None = None
        best_item: dict[str, Any] | None = None
        best_tag: str | None = None

        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("draft") is True or item.get("prerelease") is True:
                continue
            tag_name = item.get("tag_name")
            if not isinstance(tag_name, str):
                continue
            tag_tuple = parse_calver(tag_name)
            if tag_tuple is None:
                continue
            if best_tuple is None or tag_tuple > best_tuple:
                best_tuple = tag_tuple
                best_item = item
                best_tag = tag_name

        if best_tuple is None or best_item is None or best_tag is None:
            logger.warning(
                "No published CalVer releases found for %s", self._repo
            )
            return self._unavailable(checked_at)

        latest_version = normalize_calver_str(best_tag)
        raw_html_url = best_item.get("html_url")
        release_url = (
            raw_html_url if self._is_valid_release_url(raw_html_url) else None
        )

        raw_name = best_item.get("name")
        release_name = (
            raw_name.strip()
            if isinstance(raw_name, str) and raw_name.strip()
            else None
        )

        raw_published = best_item.get("published_at")
        published_at = (
            raw_published.strip()
            if isinstance(raw_published, str) and raw_published.strip()
            else None
        )

        status_val: VersionStatusLiteral = (
            "update_available"
            if best_tuple > self._current_tuple
            else "up_to_date"
        )

        return AdminVersionInfo(
            current_version=self._current_version,
            latest_version=latest_version,
            status=status_val,
            release_url=release_url,
            release_name=release_name,
            published_at=published_at,
            checked_at=checked_at,
        )

    async def get_version_info(self, refresh: bool = False) -> AdminVersionInfo:
        """Returns cached or freshly fetched version status."""
        async with _get_process_lock():
            now = self._time_fn()
            cached = self._get_cached_entry()
            if cached is not None:
                fetched_at, cached_info = cached
                age = now - fetched_at
                ttl = (
                    NEGATIVE_CACHE_TTL_SECONDS
                    if cached_info.status == "unavailable"
                    else CACHE_TTL_SECONDS
                )
                if refresh:
                    if 0 <= age < MIN_REFRESH_INTERVAL_SECONDS:
                        return cached_info
                elif 0 <= age < ttl:
                    return cached_info

            info = await self._fetch_and_evaluate(now)
            self._store_cached_entry(now, info)
            return info


def get_version_service() -> VersionService:
    """FastAPI dependency provider for VersionService."""
    return VersionService()
