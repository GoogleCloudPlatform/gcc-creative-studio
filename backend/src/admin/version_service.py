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
"""Checks GitHub releases for newer Creative Studio CalVer versions."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
import time
import weakref

import httpx

from src.admin.dto.admin_response_dto import AdminVersionInfo
from src.config.config_service import config_service
from src.version import APP_VERSION

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 3600
NEGATIVE_CACHE_TTL_SECONDS = 60
MIN_REFRESH_INTERVAL_SECONDS = 5
_GITHUB_TIMEOUT_SECONDS = 5.0
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CALVER_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})(?:\.(\d+))?$")


@dataclass
class _CacheEntry:
    info: AdminVersionInfo
    fetched_at: float
    expires_at: float
    last_attempt_at: float
    last_failed: bool = False
    has_good: bool = False


_CACHE: dict[str, _CacheEntry] = {}
_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = weakref.WeakKeyDictionary()


def clear_version_cache() -> None:
    """Clears the in-process release cache and singleflight locks."""
    _CACHE.clear()
    _LOCKS.clear()


def normalize_calver_str(raw: str) -> str:
    """Strips whitespace and at most one leading v/V tag prefix."""
    text = raw.strip()
    return text[1:] if text[:1] in ("v", "V") else text


def parse_calver(raw: str) -> tuple[int, int, int, int] | None:
    """Parses YY.MM.DD[.hotfix] into a comparable 4-int tuple, or None."""
    if not isinstance(raw, str):
        return None
    m = _CALVER_RE.fullmatch(normalize_calver_str(raw))
    if not m:
        return None
    yy, mm, dd, patch = m.groups()
    return (int(yy), int(mm), int(dd), int(patch or 0))


def _is_valid_repo(repo: str) -> bool:
    if not _REPO_RE.fullmatch(repo):
        return False
    owner, name = repo.split("/", 1)
    return owner not in {".", ".."} and name not in {".", ".."}


def _default_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_GITHUB_TIMEOUT_SECONDS, follow_redirects=False
    )


class VersionService:
    """Compares installed APP_VERSION against published GitHub releases."""

    def __init__(
        self,
        repo: str | None = None,
        github_token: str | None = None,
        current_version: str | None = None,
        time_fn: Callable[[], float] | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._repo = (
            config_service.GITHUB_RELEASE_REPO if repo is None else repo
        ).strip()
        tok = (
            config_service.GITHUB_TOKEN
            if github_token is None
            else github_token
        )
        self._github_token = tok.strip()
        cur = APP_VERSION if current_version is None else current_version
        self._current_tuple = parse_calver(cur)
        self._current_version = normalize_calver_str(cur)
        self._time_fn = time.time if time_fn is None else time_fn
        self._http_client_factory = http_client_factory or _default_http_client
        self._cache_key = f"{self._repo}|{self._current_version}"

    def _get_lock(self) -> asyncio.Lock:
        loop_locks = _LOCKS.setdefault(asyncio.get_running_loop(), {})
        lock = loop_locks.get(self._cache_key)
        if lock is None:
            lock = loop_locks[self._cache_key] = asyncio.Lock()
        return lock

    def _unavailable(
        self, checked_at: str, refresh_failed: bool = False
    ) -> AdminVersionInfo:
        return AdminVersionInfo(
            current_version=self._current_version,
            status="unavailable",
            checked_at=checked_at,
            refresh_failed=refresh_failed,
        )

    def _cached_response(
        self, entry: _CacheEntry | None, now: float, refresh: bool
    ) -> AdminVersionInfo | None:
        if (
            entry is None
            or now < entry.fetched_at
            or now < entry.last_attempt_at
        ):
            return None
        if refresh:
            if now - entry.last_attempt_at < MIN_REFRESH_INTERVAL_SECONDS:
                return entry.info.model_copy(
                    update={"refresh_failed": entry.last_failed}
                )
            return None
        return entry.info if now < entry.expires_at else None

    async def _fetch_latest_release(
        self,
    ) -> tuple[str, tuple[int, int, int, int]] | None:
        url = f"https://api.github.com/repos/{self._repo}/releases?per_page=100"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "gcc-creative-studio-version-check",
        }
        if self._github_token:
            headers["Authorization"] = f"Bearer {self._github_token}"

        try:
            async with self._http_client_factory() as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code != 200:
                        logger.warning(
                            "GitHub release check returned HTTP %s",
                            resp.status_code,
                        )
                        return None
                    chunks, total = [], 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > _MAX_RESPONSE_BYTES:
                            logger.warning(
                                "GitHub release payload exceeded %d bytes",
                                _MAX_RESPONSE_BYTES,
                            )
                            return None
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            logger.warning("GitHub release check failed: %s", exc)
            return None

        try:
            payload = json.loads(b"".join(chunks))
        except (ValueError, UnicodeDecodeError):
            logger.warning("GitHub release check returned invalid JSON")
            return None
        if not isinstance(payload, list):
            return None

        best: tuple[str, tuple[int, int, int, int]] | None = None
        for rel in payload:
            if (
                not isinstance(rel, dict)
                or rel.get("draft")
                or rel.get("prerelease")
            ):
                continue
            tag = rel.get("tag_name")
            if not isinstance(tag, str):
                continue
            parsed = parse_calver(tag.strip())
            if parsed is not None and (best is None or parsed > best[1]):
                best = (tag.strip(), parsed)
        return best

    async def _resolve_live(
        self, prev: _CacheEntry | None, now: float, refresh: bool
    ) -> AdminVersionInfo:
        checked_at = datetime.fromtimestamp(now, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if not _is_valid_repo(self._repo) or self._current_tuple is None:
            logger.warning(
                "Invalid release check config: repo=%r version=%r",
                self._repo,
                self._current_version,
            )
            return self._unavailable(checked_at, refresh_failed=refresh)

        best = await self._fetch_latest_release()
        if best is not None:
            tag, tag_tuple = best
            status = (
                "update_available"
                if tag_tuple > self._current_tuple
                else "up_to_date"
            )
            info = AdminVersionInfo(
                current_version=self._current_version,
                latest_version=normalize_calver_str(tag),
                status=status,
                release_url=f"https://github.com/{self._repo}/releases/tag/{tag}",
                checked_at=checked_at,
            )
            _CACHE[self._cache_key] = _CacheEntry(
                info, now, now + CACHE_TTL_SECONDS, now, False, True
            )
            return info

        fallback = (
            prev.info.model_copy(update={"refresh_failed": False})
            if prev is not None and prev.has_good
            else self._unavailable(checked_at)
        )
        _CACHE[self._cache_key] = _CacheEntry(
            fallback,
            now,
            now + NEGATIVE_CACHE_TTL_SECONDS,
            now,
            refresh,
            bool(prev and prev.has_good),
        )
        return fallback.model_copy(update={"refresh_failed": refresh})

    async def get_version_info(self, refresh: bool = False) -> AdminVersionInfo:
        """Returns cached or newly fetched release status for admins."""
        now = self._time_fn()
        if (
            hit := self._cached_response(
                _CACHE.get(self._cache_key), now, refresh
            )
        ) is not None:
            return hit
        async with self._get_lock():
            now = self._time_fn()
            entry = _CACHE.get(self._cache_key)
            if (hit := self._cached_response(entry, now, refresh)) is not None:
                return hit
            return await self._resolve_live(entry, now, refresh)


def get_version_service() -> VersionService:
    """FastAPI dependency provider for VersionService."""
    return VersionService()
