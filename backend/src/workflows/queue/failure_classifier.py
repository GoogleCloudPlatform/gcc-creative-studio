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

"""Failure taxonomy for workflow steps (spec §6).

Pure functions (no I/O) that turn any error signal we can observe into an
:class:`ErrorCategory` plus a retry decision:

* executor structured error bodies ``{"error_category": ..., "detail": ...}``;
* GCP Workflows ``except`` payloads (``code`` / ``tags`` / ``body``);
* gen-job ``error_message`` strings read from the gallery item;
* exceptions raised by SDKs, ``httpx`` or FastAPI (``HTTPException``).

:func:`is_transient_or_quota` is the predicate shared by the L1 in-process
retries (``src.common.retry``) and ``GeminiService``.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
from google.auth import exceptions as google_auth_exceptions


class ErrorCategory(str, Enum):
    """Failure categories of a workflow step (spec §6)."""

    TRANSIENT = "TRANSIENT"
    QUOTA = "QUOTA"
    STEP_IN_PROGRESS = "STEP_IN_PROGRESS"
    TIMEOUT = "TIMEOUT"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_INPUT = "INVALID_INPUT"
    SAFETY_BLOCK = "SAFETY_BLOCK"
    MISSING_RESOURCE = "MISSING_RESOURCE"
    INTERNAL = "INTERNAL"
    UNKNOWN = "UNKNOWN"
    CAP_EXCEEDED = "CAP_EXCEEDED"


@dataclass(frozen=True)
class Classification:
    """Result of :func:`classify`.

    Attributes:
        category: The failure category.
        retryable: Whether the failure may be retried automatically.
        counts_as_attempt: Whether it consumes a step attempt
            (``WORKFLOW_MAX_STEP_ATTEMPTS``).
        reason: Short fixed explanation; never contains raw error text.
    """

    category: ErrorCategory
    retryable: bool
    counts_as_attempt: bool
    reason: str


# GCP Workflows error tags (``e.tags``) that carry a meaning for us.
TAG_CONNECTION_ERROR = "ConnectionError"
TAG_CONNECTION_FAILED = "ConnectionFailedError"
TAG_TIMEOUT_ERROR = "TimeoutError"

_CONNECTION_TAGS = frozenset({TAG_CONNECTION_ERROR, TAG_CONNECTION_FAILED})

# Categories retried automatically; every other category parks the run in
# NEEDS_ATTENTION. AUTH_EXPIRED is "retried" by waiting for a fresh session.
_RETRYABLE = frozenset(
    {
        ErrorCategory.TRANSIENT,
        ErrorCategory.QUOTA,
        ErrorCategory.STEP_IN_PROGRESS,
        ErrorCategory.TIMEOUT,
        ErrorCategory.AUTH_EXPIRED,
        ErrorCategory.INTERNAL,
        ErrorCategory.UNKNOWN,
    },
)
# Categories that never consume a step attempt.
_NOT_AN_ATTEMPT = frozenset(
    {
        ErrorCategory.STEP_IN_PROGRESS,
        ErrorCategory.AUTH_EXPIRED,
        ErrorCategory.CAP_EXCEEDED,
    },
)
# UNKNOWN failures get a single automatic retry ("L3 once").
_UNKNOWN_MAX_ATTEMPTS = 2

_MAX_DEPTH = 6
_MAX_ITEMS = 20
_MAX_TEXT_CHARS = 8192
_MAX_JSON_CHARS = 65536

_SAFETY_RE = re.compile(
    r"safety|responsible ai|\brai\b|rai_?(?:media_?)?filtered|"
    r"prohibited[_ ]content|\bblocked\b|blocklist|block_?reason|"
    r"\bspii\b|\bcsam\b|sensitive words|usage guidelines|"
    r"content polic(?:y|ies)",
    re.IGNORECASE,
)
_QUOTA_RE = re.compile(
    r"resource[_ ]exhausted|quota|rate[_ ]limit|too many requests",
    re.IGNORECASE,
)
# Only used when no HTTP status is known (e.g. gen-job error messages).
_TRANSIENT_RE = re.compile(
    r"\bunavailable\b|deadline[_ ]exceeded|temporarily|"
    r"connection (?:reset|refused|aborted)|server disconnected",
    re.IGNORECASE,
)

_HINT_KEYS = ("error_category", "errorCategory", "category")
_STATUS_KEYS = (
    "http_status",
    "httpStatus",
    "status_code",
    "statusCode",
    "code",
    "status",
)
# Values are read as text (str) or recursed into (mapping / list).
_CONTENT_KEYS = (
    "message",
    "detail",
    "error_message",
    "errorMessage",
    "reason",
    "msg",
    "status",
    "context",
    "error",
    "body",
    "details",
    "payload",
    "errors",
    "cause",
)

# Exception families mapped to GCP-like network tags. Connect errors mean
# the request never reached the server, so they are connection errors even
# when they are timeouts.
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
_TIMEOUT_ERRORS = (TimeoutError, httpx.TimeoutException)
_CONNECTION_ERRORS = (
    ConnectionError,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
    google_auth_exceptions.TransportError,
)


@dataclass
class _Signals:
    """Signals collected from an error; the outermost value wins."""

    hint: ErrorCategory | None = None
    status: int | None = None
    tags: set[str] = field(default_factory=set)
    texts: list[str] = field(default_factory=list)

    def set_hint(self, value: Any) -> None:
        if self.hint is None:
            self.hint = _parse_category(value)

    def set_status(self, value: Any) -> None:
        if self.status is None and _is_http_status(value):
            self.status = value

    def add_text(self, value: str) -> None:
        if value:
            self.texts.append(value[:_MAX_TEXT_CHARS])

    @property
    def text(self) -> str:
        return "\n".join(self.texts)


def _is_http_status(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 100 <= value <= 599
    )


def _parse_category(value: Any) -> ErrorCategory | None:
    if isinstance(value, ErrorCategory):
        return value
    if isinstance(value, str):
        try:
            return ErrorCategory(value.strip().upper())
        except ValueError:
            return None
    return None


def _safe_attr(obj: Any, name: str) -> Any:
    """``getattr`` that also tolerates properties raising errors."""
    try:
        return getattr(obj, name, None)
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def _safe_str(obj: Any) -> str:
    try:
        return str(obj)
    except Exception:  # pylint: disable=broad-exception-caught
        return type(obj).__name__


def _network_tag(error: BaseException) -> str | None:
    if isinstance(error, _CONNECT_ERRORS):
        return TAG_CONNECTION_ERROR
    if isinstance(error, _TIMEOUT_ERRORS):
        return TAG_TIMEOUT_ERROR
    if isinstance(error, _CONNECTION_ERRORS):
        return TAG_CONNECTION_ERROR
    return None


def _extract_text(text: str, signals: _Signals, depth: int) -> None:
    stripped = text.strip()
    if (
        stripped[:1] in ("{", "[")
        and len(stripped) <= _MAX_JSON_CHARS
        and depth < _MAX_DEPTH
    ):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = None
        if isinstance(parsed, (Mapping, list)):
            _extract(parsed, signals, depth + 1)
            return
    signals.add_text(stripped)


def _extract_mapping(
    data: Mapping[Any, Any], signals: _Signals, depth: int
) -> None:
    for key in _HINT_KEYS:
        signals.set_hint(data.get(key))
    for key in _STATUS_KEYS:
        signals.set_status(data.get(key))
    tags = data.get("tags")
    if isinstance(tags, (list, tuple, set, frozenset)):
        signals.tags.update(_safe_str(tag) for tag in list(tags)[:_MAX_ITEMS])
    for key in _CONTENT_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            _extract_text(value, signals, depth)
        elif isinstance(value, (Mapping, list, tuple)):
            _extract(value, signals, depth + 1)


def _extract_exception(
    error: BaseException, signals: _Signals, depth: int
) -> None:
    signals.set_hint(_safe_attr(error, "error_category"))
    for name in ("status_code", "code", "http_status"):
        signals.set_status(_safe_attr(error, name))
    response = _safe_attr(error, "response")
    if response is not None:
        signals.set_status(_safe_attr(response, "status_code"))
    status = _safe_attr(error, "status")
    if isinstance(status, str):
        signals.add_text(status)
    else:
        signals.set_status(status)
    tag = _network_tag(error)
    if tag:
        signals.tags.add(tag)
    detail = _safe_attr(error, "detail")
    if detail is not None:
        _extract(detail, signals, depth + 1)
    message = _safe_attr(error, "message")
    if isinstance(message, str):
        _extract_text(message, signals, depth)
    signals.add_text(_safe_str(error))
    cause = error.__cause__
    if cause is not None and cause is not error:
        _extract(cause, signals, depth + 1)


def _extract(error: Any, signals: _Signals, depth: int) -> None:
    if error is None or depth > _MAX_DEPTH:
        return
    if isinstance(error, ErrorCategory):
        signals.set_hint(error)
    elif isinstance(error, bool):
        return
    elif isinstance(error, int):
        signals.set_status(error)
    elif isinstance(error, bytes):
        _extract_text(error.decode("utf-8", errors="replace"), signals, depth)
    elif isinstance(error, str):
        _extract_text(error, signals, depth)
    elif isinstance(error, BaseException):
        _extract_exception(error, signals, depth)
    elif isinstance(error, Mapping):
        _extract_mapping(error, signals, depth)
    elif isinstance(error, (list, tuple)):
        for item in error[:_MAX_ITEMS]:
            _extract(item, signals, depth + 1)
    else:
        signals.add_text(_safe_str(error))


def _collect_signals(error: Any) -> _Signals:
    signals = _Signals()
    _extract(error, signals, 0)
    return signals


def _categorize(
    signals: _Signals, has_inflight_job: bool
) -> tuple[ErrorCategory, str]:
    """Maps signals to a category, most specific signal first.

    Explicit category hints win, then auth statuses (401 / 403), then
    safety keywords (before any other status, because gen services report
    safety blocks as 400 / 500), then the remaining statuses and tags.
    """
    hint, status, text = signals.hint, signals.status, signals.text
    generic_hints = (ErrorCategory.INTERNAL, ErrorCategory.UNKNOWN)
    if hint is not None and hint not in generic_hints:
        if hint is ErrorCategory.TIMEOUT and has_inflight_job:
            return (
                ErrorCategory.STEP_IN_PROGRESS,
                "timed out while the generation job is still running",
            )
        return hint, f"reported as {hint.value}"
    if status == 401:
        return ErrorCategory.AUTH_EXPIRED, "authentication expired (HTTP 401)"
    if status == 403:
        return ErrorCategory.FORBIDDEN, "access denied (HTTP 403)"
    if _SAFETY_RE.search(text):
        return (
            ErrorCategory.SAFETY_BLOCK,
            "blocked by a safety or responsible-AI filter",
        )
    if hint is not None:
        return hint, f"reported as {hint.value}"
    if status == 404:
        return ErrorCategory.MISSING_RESOURCE, "resource not found (HTTP 404)"
    if status == 429 or _QUOTA_RE.search(text):
        return ErrorCategory.QUOTA, "quota or rate limit exhausted"
    if TAG_TIMEOUT_ERROR in signals.tags:
        if has_inflight_job:
            return (
                ErrorCategory.STEP_IN_PROGRESS,
                "timed out while the generation job is still running",
            )
        return (
            ErrorCategory.TIMEOUT,
            "timed out before a generation job was created",
        )
    if status == 504 and has_inflight_job:
        return (
            ErrorCategory.STEP_IN_PROGRESS,
            "gateway timeout while the generation job is still running",
        )
    if status in (502, 503, 504) or signals.tags & _CONNECTION_TAGS:
        return ErrorCategory.TRANSIENT, "transient network or service error"
    if status in (400, 422):
        return ErrorCategory.INVALID_INPUT, f"invalid input (HTTP {status})"
    if status is not None and status >= 500:
        return ErrorCategory.INTERNAL, f"internal error (HTTP {status})"
    if status is None and _TRANSIENT_RE.search(text):
        return ErrorCategory.TRANSIENT, "service temporarily unavailable"
    return ErrorCategory.UNKNOWN, "unrecognised error"


def counts_as_attempt(category: ErrorCategory) -> bool:
    """Whether a failure of ``category`` consumes a step attempt."""
    return category not in _NOT_AN_ATTEMPT


def classify(
    error: Any,
    *,
    has_inflight_job: bool = False,
    attempt: int = 1,
    max_attempts: int | None = None,
) -> Classification:
    """Classifies a step failure (spec §6).

    Args:
        error: Exception, error payload (mapping / JSON string / GCP ``e``),
            error message, HTTP status code or :class:`ErrorCategory`.
        has_inflight_job: Whether the step already has a gen job in flight
            (``step_states[step].job_id``). Turns timeouts into
            ``STEP_IN_PROGRESS`` continuations.
        attempt: 1-based number of the failed attempt being classified.
        max_attempts: Step attempt cap (``WORKFLOW_MAX_STEP_ATTEMPTS``).
            Categories that count as attempts stop being retryable once
            ``attempt`` reaches it (``UNKNOWN`` is retried at most once).

    Returns:
        The :class:`Classification`. A plain 504 without an in-flight job
        is ``TRANSIENT``; a timeout signal without one is ``TIMEOUT``.
    """
    signals = _collect_signals(error)
    category, reason = _categorize(signals, has_inflight_job)
    counts = counts_as_attempt(category)
    retryable = category in _RETRYABLE
    if retryable and counts:
        limit = max_attempts
        if category is ErrorCategory.UNKNOWN:
            limit = min(limit or _UNKNOWN_MAX_ATTEMPTS, _UNKNOWN_MAX_ATTEMPTS)
        if limit is not None and attempt >= limit:
            retryable = False
            reason = f"{reason}; attempt cap reached ({attempt}/{limit})"
    return Classification(
        category=category,
        retryable=retryable,
        counts_as_attempt=counts,
        reason=reason,
    )


def is_transient_or_quota(error: Any) -> bool:
    """L1 retry predicate (spec §7.1, Q10).

    True only for quota exhaustion (429 / ``RESOURCE_EXHAUSTED``), HTTP 503
    and network errors. Never for safety blocks, other 4xx, 500, 502 or 504.
    """
    signals = _collect_signals(error)
    category, _ = _categorize(signals, has_inflight_job=False)
    if category is ErrorCategory.QUOTA:
        return True
    if category is ErrorCategory.TRANSIENT:
        return signals.status not in (502, 504)
    return False
