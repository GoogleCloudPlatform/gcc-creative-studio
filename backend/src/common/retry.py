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

"""Shared L1 (in-process) retry helpers (spec §7.1).

Only quota (429 / ``RESOURCE_EXHAUSTED``), HTTP 503 and network errors are
retried (:func:`is_transient_or_quota`); safety blocks and other 4xx never
are. Never wrap calls that already created a gen job: retrying those is the
job of the idempotency guard.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    stop_before_delay,
    wait_random_exponential,
)

from src.workflows.queue.failure_classifier import is_transient_or_quota

logger = logging.getLogger(__name__)

L1_MAX_ATTEMPTS = 3
L1_MAX_WAIT_SECONDS = 16

ResultT = TypeVar("ResultT")

__all__ = [
    "L1_MAX_ATTEMPTS",
    "L1_MAX_WAIT_SECONDS",
    "call_with_l1_retry",
    "is_transient_or_quota",
    "l1_async_retrying",
]


def _log_before_sleep(retry_state: RetryCallState) -> None:
    outcome = retry_state.outcome
    error = outcome.exception() if outcome is not None else None
    # Only the exception type: messages may echo request data.
    logger.warning(
        "Transient error on attempt %d (%s); retrying.",
        retry_state.attempt_number,
        type(error).__name__,
    )


def l1_async_retrying(
    *,
    predicate: Callable[[BaseException], bool] = is_transient_or_quota,
    max_attempts: int = L1_MAX_ATTEMPTS,
    max_wait_seconds: float = L1_MAX_WAIT_SECONDS,
    max_total_seconds: float | None = None,
    sleep: Callable[[float], Awaitable[Any]] | None = None,
) -> AsyncRetrying:
    """Builds the L1 ``AsyncRetrying`` controller.

    Random exponential wait (multiplier 1, capped at ``max_wait_seconds``),
    at most ``max_attempts`` attempts, re-raising the last error.

    Args:
        predicate: Errors to retry (default :func:`is_transient_or_quota`).
        max_attempts: Maximum number of attempts.
        max_wait_seconds: Maximum wait between two attempts.
        max_total_seconds: If set, no retry starts once the elapsed time
            plus the next wait would reach it (keeps a request budget).
        sleep: Sleep coroutine (inject for tests).
    """
    stop: Any = stop_after_attempt(max_attempts)
    if max_total_seconds is not None:
        stop = stop | stop_before_delay(max_total_seconds)
    options: dict[str, Any] = {}
    if sleep is not None:
        options["sleep"] = sleep
    return AsyncRetrying(
        retry=retry_if_exception(predicate),
        wait=wait_random_exponential(multiplier=1, max=max_wait_seconds),
        stop=stop,
        reraise=True,
        before_sleep=_log_before_sleep,
        **options,
    )


async def call_with_l1_retry(
    func: Callable[..., Awaitable[ResultT]],
    *args: Any,
    retrying: AsyncRetrying | None = None,
    **kwargs: Any,
) -> ResultT:
    """Awaits ``func(*args, **kwargs)`` with L1 retries."""
    controller = retrying if retrying is not None else l1_async_retrying()
    return await controller(func, *args, **kwargs)
