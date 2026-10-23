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

"""Keys of ``workflow_runs.step_states``.

Non-loop steps (and ``Loop`` steps) are stored under ``"<step_id>"``; every
iteration of a loop body step is stored under ``"<step_id>#<iteration>"``
(``0``-based). Every reader and writer of ``step_states`` goes through these
helpers so the convention lives in one place.
"""

from collections.abc import Mapping
from typing import TypeVar

ITERATION_SEPARATOR = "#"
# Step state keys: step ids (no '#') optionally followed by '#<iteration>'.
STEP_STATE_KEY_PATTERN = r"^[A-Za-z0-9_-]*(#[0-9]{1,4})?$"

StateT = TypeVar("StateT")


def validate_step_id_chars(step_id: str) -> str:
    """Returns ``step_id``; raises ``ValueError`` if it contains ``#``."""
    if ITERATION_SEPARATOR in step_id:
        raise ValueError(
            f"Invalid step id {step_id!r}: the '{ITERATION_SEPARATOR}' "
            "character is reserved for loop iteration keys."
        )
    return step_id


def step_state_key(step_id: str, iteration: int | None = None) -> str:
    """``step_id`` for non-loop steps, ``"<step_id>#<iteration>"`` otherwise.

    Raises:
        ValueError: ``step_id`` contains ``#`` or ``iteration`` is negative.
    """
    validate_step_id_chars(step_id)
    if iteration is None:
        return step_id
    if isinstance(iteration, bool) or not isinstance(iteration, int):
        raise ValueError(f"Invalid iteration {iteration!r}.")
    if iteration < 0:
        raise ValueError(f"Invalid iteration {iteration!r}: must be >= 0.")
    return f"{step_id}{ITERATION_SEPARATOR}{iteration}"


def parse_step_state_key(key: str) -> tuple[str, int | None]:
    """Splits a ``step_states`` key into ``(step_id, iteration | None)``.

    Keys whose suffix is not a non-negative integer are treated as plain
    (non-loop) step ids.
    """
    step_id, separator, suffix = key.rpartition(ITERATION_SEPARATOR)
    if separator and step_id and suffix.isdigit():
        return step_id, int(suffix)
    return key, None


def base_step_id(key: str) -> str:
    """Step id of a ``step_states`` key (iteration suffix removed)."""
    return parse_step_state_key(key)[0]


def group_step_states(
    step_states: Mapping[str, StateT],
) -> dict[str, list[tuple[int | None, StateT]]]:
    """Groups ``step_states`` by base step id.

    Each list is sorted with the non-iteration record first, then the
    iteration records in numerical order (``#2`` after ``#10`` never
    happens).
    """
    grouped: dict[str, list[tuple[int | None, StateT]]] = {}
    for key, state in step_states.items():
        step_id, iteration = parse_step_state_key(key)
        grouped.setdefault(step_id, []).append((iteration, state))
    for records in grouped.values():
        records.sort(key=lambda item: (item[0] is not None, item[0] or 0))
    return grouped
