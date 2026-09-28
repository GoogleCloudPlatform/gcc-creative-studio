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
"""Tests for the shared L1 retry helper (spec §7.1)."""

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from google.genai import errors as genai_errors
from tenacity import AsyncRetrying

from src.common.retry import (
    L1_MAX_ATTEMPTS,
    L1_MAX_WAIT_SECONDS,
    call_with_l1_retry,
    is_transient_or_quota,
    l1_async_retrying,
)
from src.workflows.queue import failure_classifier

pytestmark = pytest.mark.anyio


class _Flaky:
    """Async callable failing with ``errors`` before returning ``result``."""

    def __init__(self, *errors: BaseException, result="ok") -> None:
        self.errors = list(errors)
        self.result = result
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        self.args = args
        self.kwargs = kwargs
        if self.errors:
            raise self.errors.pop(0)
        return self.result


def _quota_error() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429, {"error": {"code": 429, "message": "Resource exhausted"}}
    )


def test_settings_match_the_spec():
    assert L1_MAX_ATTEMPTS == 3
    assert L1_MAX_WAIT_SECONDS == 16


def test_predicate_is_the_shared_classifier_predicate():
    assert is_transient_or_quota is failure_classifier.is_transient_or_quota


def test_controller_is_configured_with_the_classifier_predicate():
    controller = l1_async_retrying()
    assert isinstance(controller, AsyncRetrying)
    assert controller.reraise is True
    assert controller.stop.max_attempt_number == L1_MAX_ATTEMPTS


async def test_retries_quota_and_network_errors_then_succeeds():
    sleep = AsyncMock()
    func = _Flaky(_quota_error(), httpx.ConnectError("refused"))

    result = await call_with_l1_retry(
        func, "a", retrying=l1_async_retrying(sleep=sleep), key="b"
    )

    assert result == "ok"
    assert func.calls == 3
    assert func.args == ("a",)
    assert func.kwargs == {"key": "b"}
    assert sleep.await_count == 2
    assert all(0 <= call.args[0] <= 16 for call in sleep.await_args_list)


@pytest.mark.parametrize(
    "error",
    [
        genai_errors.ClientError(
            400, {"error": {"message": "Request blocked by safety filters"}}
        ),
        genai_errors.ClientError(400, {"error": {"message": "bad request"}}),
        genai_errors.ServerError(500, {"error": {"message": "internal"}}),
        ValueError("bug"),
    ],
)
async def test_non_transient_errors_are_raised_immediately(error):
    sleep = AsyncMock()
    func = _Flaky(error)

    with pytest.raises(type(error)):
        await call_with_l1_retry(func, retrying=l1_async_retrying(sleep=sleep))

    assert func.calls == 1
    sleep.assert_not_awaited()


async def test_gives_up_after_the_last_attempt_and_reraises():
    sleep = AsyncMock()
    errors = [_quota_error() for _ in range(5)]
    func = _Flaky(*errors)

    with pytest.raises(genai_errors.ClientError) as exc_info:
        await call_with_l1_retry(func, retrying=l1_async_retrying(sleep=sleep))

    assert exc_info.value is errors[2]
    assert func.calls == L1_MAX_ATTEMPTS
    assert sleep.await_count == L1_MAX_ATTEMPTS - 1


async def test_custom_attempt_budget():
    sleep = AsyncMock()
    func = _Flaky(httpx.ConnectError("x"), httpx.ConnectError("y"))

    with pytest.raises(httpx.ConnectError):
        await call_with_l1_retry(
            func,
            retrying=l1_async_retrying(
                max_attempts=2, max_wait_seconds=1, sleep=sleep
            ),
        )

    assert func.calls == 2
    assert all(call.args[0] <= 1 for call in sleep.await_args_list)


async def test_default_controller_does_not_sleep_on_success():
    func = _Flaky(result=42)
    with patch("asyncio.sleep", AsyncMock()) as sleep:
        assert await call_with_l1_retry(func) == 42
    sleep.assert_not_awaited()


async def test_default_controller_uses_asyncio_sleep_between_attempts():
    func = _Flaky(httpx.ConnectError("refused"), result="done")
    with patch("asyncio.sleep", AsyncMock()) as sleep:
        assert await call_with_l1_retry(func) == "done"
    sleep.assert_awaited_once()


async def test_retry_log_names_the_error_type_only(caplog):
    secret = "Bearer eyJhbGciOiJSUzI1NiJ9.payload.signature"
    func = _Flaky(httpx.ConnectError(f"refused with {secret}"))

    with caplog.at_level(logging.WARNING, logger="src.common.retry"):
        await call_with_l1_retry(
            func, retrying=l1_async_retrying(sleep=AsyncMock())
        )

    assert "ConnectError" in caplog.text
    assert "attempt 1" in caplog.text
    assert "eyJhbGciOiJSUzI1NiJ9" not in caplog.text
