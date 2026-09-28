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
"""Tests for the L3 retry backoff (spec §5.4)."""

import datetime
import random

import pytest

from src.workflows.queue.backoff import (
    DEFAULT_BASE_SECONDS,
    DEFAULT_MAX_SECONDS,
    backoff_ceiling_seconds,
    compute_backoff_seconds,
    compute_next_retry_at,
)

NOW = datetime.datetime(2026, 9, 25, 2, 0, tzinfo=datetime.UTC)


class _FixedRandom(random.Random):
    """Random generator whose ``uniform`` returns a fixed fraction."""

    def __init__(self, fraction: float) -> None:
        super().__init__(0)
        self.fraction = fraction

    def uniform(self, a, b):
        return a + (b - a) * self.fraction


def test_defaults_match_the_spec_settings():
    assert DEFAULT_BASE_SECONDS == 30
    assert DEFAULT_MAX_SECONDS == 900


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [
        (1, 30),
        (2, 60),
        (3, 120),
        (4, 240),
        (5, 480),
        (6, 900),  # 960 capped
        (7, 900),
        (1000, 900),  # exponent bounded, no overflow
    ],
)
def test_ceiling_grows_exponentially_and_is_capped(attempt, expected):
    assert backoff_ceiling_seconds(attempt) == expected


@pytest.mark.parametrize("attempt", [0, -1, -100])
def test_attempts_below_one_are_treated_as_the_first(attempt):
    assert backoff_ceiling_seconds(attempt) == 30


def test_ceiling_uses_the_configured_base_and_cap():
    assert backoff_ceiling_seconds(3, base_seconds=10, max_seconds=35) == 35
    assert backoff_ceiling_seconds(2, base_seconds=10, max_seconds=35) == 20


@pytest.mark.parametrize(
    ("base", "cap"), [(0, 900), (-1, 900), (30, 0), (30, -5)]
)
def test_non_positive_settings_are_rejected(base, cap):
    with pytest.raises(ValueError):
        backoff_ceiling_seconds(1, base_seconds=base, max_seconds=cap)


@pytest.mark.parametrize("attempt", [1, 2, 3, 6, 50])
def test_jitter_stays_between_half_and_full_ceiling(attempt):
    rng = random.Random(1234)
    ceiling = backoff_ceiling_seconds(attempt)
    delays = [compute_backoff_seconds(attempt, rng) for _ in range(200)]
    assert all(ceiling / 2 <= delay <= ceiling for delay in delays)
    # Jitter actually spreads the retries.
    assert len(set(delays)) > 1


def test_jitter_bounds_are_reachable():
    assert compute_backoff_seconds(3, _FixedRandom(0.0)) == 60
    assert compute_backoff_seconds(3, _FixedRandom(1.0)) == 120


def test_seeded_rng_is_deterministic():
    first = compute_backoff_seconds(4, random.Random(42))
    second = compute_backoff_seconds(4, random.Random(42))
    assert first == second


def test_default_rng_is_used_when_none_is_given():
    delay = compute_backoff_seconds(2)
    assert 30 <= delay <= 60


def test_capped_attempts_never_exceed_the_maximum():
    rng = random.Random(7)
    for attempt in range(1, 40):
        assert compute_backoff_seconds(attempt, rng) <= DEFAULT_MAX_SECONDS


def test_next_retry_at_adds_the_delay_to_now():
    result = compute_next_retry_at(2, NOW, _FixedRandom(0.5))
    assert result == NOW + datetime.timedelta(seconds=45)
    assert result.tzinfo is datetime.UTC


def test_next_retry_at_respects_custom_settings():
    result = compute_next_retry_at(
        5, NOW, _FixedRandom(1.0), base_seconds=1, max_seconds=4
    )
    assert result == NOW + datetime.timedelta(seconds=4)


def test_next_retry_at_is_always_in_the_future():
    rng = random.Random(99)
    for attempt in (0, 1, 2, 10):
        assert compute_next_retry_at(attempt, NOW, rng) > NOW
