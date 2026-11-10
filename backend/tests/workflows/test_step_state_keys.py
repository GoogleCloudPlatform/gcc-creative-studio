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

"""Tests of the flat ``"<step_id>#<iteration>"`` step state keys."""

import pytest

from src.workflows.dto.workflow_run_dto import RunFinishedCallbackDto
from src.workflows.step_state_keys import (
    base_step_id,
    group_step_states,
    parse_step_state_key,
    step_state_key,
    validate_step_id_chars,
)


def test_step_state_key_builds_flat_keys():
    assert step_state_key("gen") == "gen"
    assert step_state_key("gen", 0) == "gen#0"
    assert step_state_key("gen", 12) == "gen#12"


@pytest.mark.parametrize("iteration", [-1, True, "1", 1.0])
def test_step_state_key_rejects_bad_iterations(iteration):
    with pytest.raises(ValueError):
        step_state_key("gen", iteration)


def test_step_state_key_rejects_hash_in_step_id():
    with pytest.raises(ValueError, match="reserved"):
        step_state_key("gen#1", 2)
    with pytest.raises(ValueError):
        validate_step_id_chars("a#b")
    assert validate_step_id_chars("a-b_c") == "a-b_c"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("gen", ("gen", None)),
        ("gen#0", ("gen", 0)),
        ("gen#10", ("gen", 10)),
        ("gen#x", ("gen#x", None)),
        ("#3", ("#3", None)),
        ("gen#", ("gen#", None)),
    ],
)
def test_parse_step_state_key(key, expected):
    assert parse_step_state_key(key) == expected


def test_base_step_id():
    assert base_step_id("gen#4") == "gen"
    assert base_step_id("gen") == "gen"


def test_group_step_states_orders_numerically():
    grouped = group_step_states(
        {"gen#10": "c", "gen#2": "b", "loop": "l", "gen#0": "a"}
    )
    assert grouped == {
        "gen": [(0, "a"), (2, "b"), (10, "c")],
        "loop": [(None, "l")],
    }


def test_callback_dto_accepts_iteration_keys_only():
    dto = RunFinishedCallbackDto(
        execution_id="e1", status="FAILED", step_id="gen#3"
    )
    assert dto.step_id == "gen#3"
    for bad in ("gen#x", "gen#1#2", "gen 1"):
        with pytest.raises(ValueError):
            RunFinishedCallbackDto(
                execution_id="e1", status="FAILED", step_id=bad
            )
