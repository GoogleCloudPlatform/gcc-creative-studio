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

"""L3 retry backoff: exponential growth, jitter and a cap.

Pure functions. Defaults mirror ``WORKFLOW_RETRY_BASE_SECONDS`` (30) and
``WORKFLOW_RETRY_MAX_SECONDS`` (900); callers pass the configured values.
"""

import datetime
import random

DEFAULT_BASE_SECONDS = 30.0
DEFAULT_MAX_SECONDS = 900.0
# Bounds the exponent: base * 2**32 already exceeds any sensible cap.
_MAX_EXPONENT = 32


def backoff_ceiling_seconds(
    attempt: int,
    *,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> float:
    """Upper bound of the delay before retrying after failure ``attempt``.

    ``base * 2**(attempt - 1)`` capped at ``max_seconds``; attempts below 1
    are treated as the first one.
    """
    if base_seconds <= 0 or max_seconds <= 0:
        raise ValueError("base_seconds and max_seconds must be positive")
    exponent = min(max(attempt, 1) - 1, _MAX_EXPONENT)
    return min(float(max_seconds), float(base_seconds) * 2**exponent)


def compute_backoff_seconds(
    attempt: int,
    rng: random.Random | None = None,
    *,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> float:
    """Delay with "equal jitter": uniform in ``[ceiling / 2, ceiling]``.

    Half of the delay is guaranteed (quota needs real backoff); the random
    half spreads retries of runs that failed together.
    """
    ceiling = backoff_ceiling_seconds(
        attempt, base_seconds=base_seconds, max_seconds=max_seconds
    )
    generator = rng if rng is not None else random.Random()
    half = ceiling / 2
    return half + generator.uniform(0, half)


def compute_next_retry_at(
    attempt: int,
    now: datetime.datetime,
    rng: random.Random | None = None,
    *,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> datetime.datetime:
    """Earliest dispatch time (``next_retry_at``) after failure ``attempt``.

    Args:
        attempt: 1-based number of the failed attempt.
        now: Current time (inject for deterministic tests).
        rng: Random generator (seed it for deterministic tests).
        base_seconds: Delay ceiling of the first retry.
        max_seconds: Maximum delay ceiling.

    Returns:
        ``now`` plus the jittered, capped exponential delay.
    """
    delay = compute_backoff_seconds(
        attempt, rng, base_seconds=base_seconds, max_seconds=max_seconds
    )
    return now + datetime.timedelta(seconds=delay)
