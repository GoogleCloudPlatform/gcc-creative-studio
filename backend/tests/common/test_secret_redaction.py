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
"""Tests for token redaction in logs and error details (spec §10)."""

import logging
import sys

import pytest

from src.common.secret_redaction import (
    MAX_ERROR_DETAIL_BYTES,
    REDACTED,
    SecretRedactionFilter,
    install_global_secret_redaction,
    install_secret_redaction,
    redact_secrets,
    sanitize_error_detail,
)
from src.config.logger_config import setup_logging

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"
ACCESS_TOKEN = "ya29.a0AfH6SMBx-secret_token"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (f"Authorization: Bearer {JWT}", JWT),
        ("authorization=Bearer opaque-token-123", "opaque-token-123"),
        (str({"Authorization": f"Bearer {JWT}"}), JWT),
        (str({"headers": {"authorization": "abc123"}}), "abc123"),
        (f"user_auth_header={ACCESS_TOKEN}", ACCESS_TOKEN),
        (f'{{"user_auth_header": "Bearer {JWT}"}}', JWT),
        (f"X-User-Authorization: {ACCESS_TOKEN}", ACCESS_TOKEN),
        (f"token {JWT} leaked", JWT),
        (f"calling with {ACCESS_TOKEN}", ACCESS_TOKEN),
        (f"bearer {JWT}", JWT),
    ],
)
def test_redact_secrets_removes_tokens(text, secret):
    redacted = redact_secrets(text)
    assert secret not in redacted
    assert REDACTED in redacted


def test_redact_secrets_keeps_quotes_around_redacted_values():
    redacted = redact_secrets("{'Authorization': 'abc123', 'x': 1}")
    assert redacted == "{'Authorization': '[REDACTED]', 'x': 1}"


def test_redact_secrets_leaves_other_text_untouched():
    text = "Generation job 812 failed: RESOURCE_EXHAUSTED (step StepA)"
    assert redact_secrets(text) == text


def test_redact_secrets_accepts_non_strings():
    assert redact_secrets(123) == "123"
    assert JWT not in redact_secrets({"authorization": f"Bearer {JWT}"})


def test_sanitize_error_detail_handles_none():
    assert sanitize_error_detail(None) == ""


def test_sanitize_error_detail_redacts_and_keeps_short_text():
    detail = sanitize_error_detail(f"Backend error: Bearer {JWT}")
    assert detail == f"Backend error: Bearer {REDACTED}"


def test_sanitize_error_detail_truncates_to_4kb():
    detail = sanitize_error_detail("x" * 10_000)
    assert len(detail.encode("utf-8")) <= MAX_ERROR_DETAIL_BYTES
    assert detail.endswith("... [truncated]")


def test_sanitize_error_detail_truncates_multibyte_text_safely():
    detail = sanitize_error_detail("é" * 5_000)
    encoded = detail.encode("utf-8")
    assert len(encoded) <= MAX_ERROR_DETAIL_BYTES
    encoded.decode("utf-8")  # still valid UTF-8
    assert detail.endswith("... [truncated]")


def test_sanitize_error_detail_with_tiny_budget_drops_the_suffix():
    assert sanitize_error_detail("abcdefghijkl", max_bytes=5) == "abcde"
    assert sanitize_error_detail("abc", max_bytes=5) == "abc"


def test_sanitize_error_detail_redacts_before_truncating():
    detail = sanitize_error_detail(f"Bearer {JWT}" + "y" * 5_000)
    assert JWT not in detail


def _record(msg, args=(), exc_info=None, stack_info=None):
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
        sinfo=stack_info,
    )


def test_filter_redacts_formatted_message():
    record = _record("headers: %s", ({"Authorization": f"Bearer {JWT}"},))
    assert SecretRedactionFilter().filter(record) is True
    assert JWT not in record.getMessage()
    assert record.args is None


def test_filter_leaves_clean_records_untouched():
    record = _record("job %s done", (812,))
    assert SecretRedactionFilter().filter(record) is True
    assert record.msg == "job %s done"
    assert record.args == (812,)


def test_filter_tolerates_malformed_format_arguments():
    record = _record("%s and %s", ("only one",))
    assert SecretRedactionFilter().filter(record) is True
    assert record.msg == "%s and %s"


def test_filter_redacts_tracebacks_and_stack_info():
    exc_info = None
    try:
        raise ValueError(f"request failed with Bearer {JWT}")
    except ValueError:
        exc_info = sys.exc_info()
    record = _record(
        "failed", exc_info=exc_info, stack_info=f"Stack: token={JWT}"
    )

    SecretRedactionFilter().filter(record)

    assert JWT not in record.exc_text
    assert "ValueError" in record.exc_text
    assert JWT not in record.stack_info


def test_filter_redacts_existing_exc_text():
    record = _record("failed")
    record.exc_text = f"Traceback: Authorization: {ACCESS_TOKEN}"
    SecretRedactionFilter().filter(record)
    assert ACCESS_TOKEN not in record.exc_text


def test_installed_filter_redacts_captured_logs(caplog):
    logger = install_secret_redaction(
        logging.getLogger("tests.secret_redaction.capture")
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info("Calling backend with headers %s", {"Authorization": JWT})
    assert JWT not in caplog.text
    assert REDACTED in caplog.text


def test_install_secret_redaction_is_idempotent():
    logger = logging.getLogger("tests.secret_redaction.idempotent")
    assert install_secret_redaction(logger) is logger
    install_secret_redaction(logger)
    filters = [
        f for f in logger.filters if isinstance(f, SecretRedactionFilter)
    ]
    assert len(filters) == 1


def test_filter_keeps_args_usable_when_the_secret_is_in_a_string_arg():
    # uvicorn's access formatter unpacks record.args as a tuple.
    record = _record(
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1", "GET", f"/x?token={JWT}", "1.1", 200),
    )

    SecretRedactionFilter().filter(record)

    assert record.msg == '%s - "%s %s HTTP/%s" %d'
    assert record.args == (
        "10.0.0.1",
        "GET",
        f"/x?token={REDACTED}",
        "1.1",
        200,
    )
    assert JWT not in record.getMessage()


def test_filter_redacts_mapping_args_in_place():
    record = _record(
        "user %(name)s sent %(token)s", ({"name": "a", "token": JWT},)
    )

    SecretRedactionFilter().filter(record)

    assert record.args == {"name": "a", "token": REDACTED}
    assert record.getMessage() == f"user a sent {REDACTED}"


def test_filter_replaces_the_message_when_the_secret_is_in_the_template():
    record = _record(f"leaked {JWT} for job %s", (812,))

    SecretRedactionFilter().filter(record)

    assert record.args is None
    assert record.msg == f"leaked {REDACTED} for job 812"


def test_filter_leaves_clean_tracebacks_to_the_handler():
    try:
        raise ValueError("job 812 failed")
    except ValueError:
        record = _record("failed", exc_info=sys.exc_info())

    SecretRedactionFilter().filter(record)

    # Unchanged tracebacks are formatted by the handler's own formatter.
    assert record.exc_text is None


@pytest.fixture(name="isolated_logging")
def fixture_isolated_logging():
    """Restores the record factory and the root filters / handlers."""
    root = logging.getLogger()
    factory = logging.getLogRecordFactory()
    root_filters = list(root.filters)
    root_handlers = list(root.handlers)
    handler_filters = {
        handler: list(handler.filters) for handler in root_handlers
    }
    root_level = root.level
    yield root
    logging.setLogRecordFactory(factory)
    root.filters[:] = root_filters
    for handler in list(root.handlers):
        if handler not in root_handlers:
            root.removeHandler(handler)
    for handler in root_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
        handler.filters[:] = handler_filters[handler]
    root.setLevel(root_level)


def _redaction_filters(filterer):
    return [f for f in filterer.filters if isinstance(f, SecretRedactionFilter)]


def test_global_redaction_covers_propagated_records(isolated_logging, caplog):
    install_global_secret_redaction()
    logger = logging.getLogger("tests.secret_redaction.child")  # no filter

    with caplog.at_level(logging.INFO):
        logger.info("Calling backend with headers %s", {"Authorization": JWT})
        logging.getLogger().warning("root saw token=%s", ACCESS_TOKEN)

    assert JWT not in caplog.text
    assert ACCESS_TOKEN not in caplog.text
    assert caplog.text.count(REDACTED) == 2
    assert _redaction_filters(isolated_logging)


def test_global_redaction_covers_non_propagating_loggers(isolated_logging):
    install_global_secret_redaction()
    records = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("tests.secret_redaction.isolated")
    logger.propagate = False
    handler = ListHandler()
    logger.addHandler(handler)
    try:
        logger.warning("Authorization: Bearer %s", JWT)
    finally:
        logger.removeHandler(handler)
        logger.propagate = True

    assert JWT not in records[0].getMessage()


def test_global_redaction_is_idempotent(isolated_logging):
    install_global_secret_redaction()
    factory = logging.getLogRecordFactory()

    install_global_secret_redaction()

    assert logging.getLogRecordFactory() is factory
    assert len(_redaction_filters(isolated_logging)) == 1
    for handler in isolated_logging.handlers:
        assert len(_redaction_filters(handler)) == 1


def test_global_redaction_keeps_clean_log_output(isolated_logging, caplog):
    install_global_secret_redaction()
    logger = logging.getLogger("tests.secret_redaction.clean")

    with caplog.at_level(logging.INFO):
        logger.info("job %s finished in %.1fs", 812, 1.25)

    assert caplog.records[-1].args == (812, 1.25)
    assert "job 812 finished in 1.2s" in caplog.text


def test_setup_logging_installs_global_redaction(isolated_logging, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")

    setup_logging()
    setup_logging()

    assert getattr(logging.getLogRecordFactory(), "secret_redaction_installed")
    assert len(_redaction_filters(isolated_logging)) == 1
    stream_handlers = [
        handler
        for handler in isolated_logging.handlers
        if isinstance(handler, logging.StreamHandler)
        and _redaction_filters(handler)
    ]
    assert stream_handlers
