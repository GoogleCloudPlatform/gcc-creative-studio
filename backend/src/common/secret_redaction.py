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

"""Keeps bearer tokens out of logs and persisted error details (spec §10)."""

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

REDACTED = "[REDACTED]"
# ``last_error_detail`` / step error details are capped at 4 KB (spec §5.1).
MAX_ERROR_DETAIL_BYTES = 4096
_TRUNCATION_SUFFIX = "... [truncated]"

_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9\-._~+/]+=*")
_GOOGLE_ACCESS_TOKEN_RE = re.compile(r"\bya29\.[A-Za-z0-9\-._~+/]+=*")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")
_AUTH_KEY_VALUE_RE = re.compile(
    r"(?i)(?P<key>[\"']?"
    r"(?:x-user-authorization|authorization|user_auth_header)"
    r"[\"']?\s*[:=]\s*)"
    # Already redacted values are left alone (redaction is idempotent).
    r"(?!\[REDACTED\])"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
)


def _redact_key_value(match: re.Match[str]) -> str:
    key = match.group("key")
    value = match.group("value")
    quote = value[0] if value[0] in "\"'" else ""
    return f"{key}{quote}{REDACTED}{quote}"


def redact_secrets(value: Any) -> str:
    """Returns ``value`` as text with bearer tokens / auth headers redacted.

    Covers ``Bearer <token>``, Google access tokens (``ya29.``), JWTs (ID
    tokens) and ``Authorization`` / ``X-User-Authorization`` /
    ``user_auth_header`` key-value pairs.
    """
    text = value if isinstance(value, str) else str(value)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", text)
    text = _GOOGLE_ACCESS_TOKEN_RE.sub(REDACTED, text)
    text = _JWT_RE.sub(REDACTED, text)
    return _AUTH_KEY_VALUE_RE.sub(_redact_key_value, text)


def sanitize_error_detail(
    value: Any, max_bytes: int = MAX_ERROR_DETAIL_BYTES
) -> str:
    """Redacts secrets and truncates to ``max_bytes`` UTF-8 bytes."""
    text = redact_secrets("" if value is None else value)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = _TRUNCATION_SUFFIX.encode("utf-8")
    if max_bytes <= len(suffix):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    kept = encoded[: max_bytes - len(suffix)]
    return kept.decode("utf-8", errors="ignore") + _TRUNCATION_SUFFIX


def _redact_arg(value: Any) -> Any:
    return redact_secrets(value) if isinstance(value, str) else value


def _redact_in_args(record: logging.LogRecord) -> bool:
    """Redacts the string arguments of ``record`` in place, if that suffices.

    Keeps ``record.args`` usable by formatters that read them (e.g. the
    uvicorn access log formatter unpacks a tuple). Returns ``False`` when
    the secret is not in a string argument (then the caller replaces the
    whole message).
    """
    args = record.args
    if isinstance(args, tuple):
        new_args: Any = tuple(_redact_arg(arg) for arg in args)
    elif isinstance(args, Mapping):
        new_args = {key: _redact_arg(value) for key, value in args.items()}
    else:
        return False
    try:
        candidate = str(record.msg) % new_args
    except Exception:  # pylint: disable=broad-exception-caught
        return False
    if redact_secrets(candidate) != candidate:
        return False
    record.args = new_args
    return True


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from messages and tracebacks.

    A filter attached to a logger only sees records created on that logger
    (not records propagated from child loggers); use
    :func:`install_global_secret_redaction` to cover every log record.
    Records without secrets are left untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pylint: disable=broad-exception-caught
            # Malformed format arguments: let the handler report it.
            return True
        redacted = redact_secrets(message)
        if redacted != message and not _redact_in_args(record):
            record.msg = redacted
            record.args = None
        if record.exc_info or record.exc_text:
            traceback_text = (
                record.exc_text
                or logging.Formatter().formatException(record.exc_info)
            )
            redacted_traceback = redact_secrets(traceback_text)
            # Only set when needed, so handlers keep formatting exceptions
            # with their own formatter otherwise.
            if redacted_traceback != traceback_text:
                record.exc_text = redacted_traceback
        if record.stack_info:
            record.stack_info = redact_secrets(record.stack_info)
        return True


def install_secret_redaction(logger: logging.Logger) -> logging.Logger:
    """Adds a :class:`SecretRedactionFilter` to ``logger`` (idempotent)."""
    if not any(isinstance(f, SecretRedactionFilter) for f in logger.filters):
        logger.addFilter(SecretRedactionFilter())
    return logger


_FACTORY_MARKER = "secret_redaction_installed"


def _redacting_record_factory(
    factory: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    redaction_filter = SecretRedactionFilter()

    def create_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        redaction_filter.filter(record)
        return record

    setattr(create_record, _FACTORY_MARKER, True)
    return create_record


def install_global_secret_redaction() -> None:
    """Redacts secrets from every log record of the process (idempotent).

    Call once at startup, after the root handlers are configured:

    1. the log record factory redacts each record when it is created, so
       every logger is covered (propagated records, loggers that do not
       propagate such as uvicorn's, and handlers added later);
    2. the root logger gets a :class:`SecretRedactionFilter`;
    3. every handler already attached to the root logger gets one too
       (defense in depth if a library replaces the record factory).
    """
    factory = logging.getLogRecordFactory()
    if not getattr(factory, _FACTORY_MARKER, False):
        logging.setLogRecordFactory(_redacting_record_factory(factory))
    root_logger = install_secret_redaction(logging.getLogger())
    for handler in root_logger.handlers:
        if not any(
            isinstance(f, SecretRedactionFilter) for f in handler.filters
        ):
            handler.addFilter(SecretRedactionFilter())
