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

"""Run details ``history[]`` entries, loop aggregate states and the legacy
read-time ``step_inputs`` fallback."""

import datetime

import pytest

from src.workflows.run_step_entries import build_step_entries
from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    ImageInputs,
    ImageSettings,
    ImageStep,
    LoopInputs,
    LoopSettings,
    LoopStep,
    StepOutputReference,
    StepStatusEnum,
    UserInputStep,
)
from src.workflows.schema.workflow_run_model import StepErrorInfo, StepState

NOW = datetime.datetime(2026, 6, 15, 12, 0, tzinfo=datetime.UTC)
LATER = NOW + datetime.timedelta(minutes=5)
COMPLETED = StepStatusEnum.COMPLETED
RUNNING = StepStatusEnum.RUNNING
FAILED = StepStatusEnum.FAILED
PENDING = StepStatusEnum.PENDING


def _ref(step, output):
    return StepOutputReference(step=step, output=output)


def _loop_steps(end="gen_image"):
    return [
        UserInputStep(step_id="user_input"),
        LoopStep(
            step_id="loop_1",
            inputs=LoopInputs(loop_ending=_ref(end, "loop_ending")),
            settings=LoopSettings(mode="folder", folder_id=42),
        ),
        ImageStep(
            step_id="gen_image",
            inputs=ImageInputs(
                prompt="Studio lighting",
                input_images=_ref("loop_1", "current_item"),
            ),
            settings=ImageSettings(),
        ),
    ]


def _loop_record(total=3, status=COMPLETED):
    return StepState(
        status=status,
        attempts=1,
        started_at=NOW,
        completed_at=NOW if status == COMPLETED else None,
        inputs={
            "mode": "folder",
            "folder_id": 42,
            "folder_name": "Product Photos",
            "item_type": "image",
        },
        outputs=(
            {
                "items": [[100 + n] for n in range(total)],
                "total_iterations": total,
                "total_found": total,
                "truncated": False,
            }
            if status == COMPLETED
            else None
        ),
    )


def _iteration(n, status=COMPLETED):
    done = status == COMPLETED
    return StepState(
        status=status,
        attempts=1,
        started_at=NOW,
        completed_at=LATER if done else None,
        inputs=(
            {"prompt": "Studio lighting", "input_images": [100 + n]}
            if done
            else None
        ),
        outputs={"generated_image": [500 + n]} if done else None,
        error=(
            StepErrorInfo(category="INVALID_INPUT", detail="boom")
            if status == FAILED
            else None
        ),
    )


def _entries(steps, states, user_inputs=None):
    entries = build_step_entries(
        steps, states, user_inputs=user_inputs or {}, started_at=NOW
    )
    return {entry["step_id"]: entry for entry in entries}


def test_user_input_entry_has_history_only():
    entries = _entries(
        _loop_steps(), {"loop_1": _loop_record()}, {"topic": "cats"}
    )

    user_entry = entries["user_input"]
    assert user_entry["history"] == [
        {"step_inputs": {}, "step_outputs": {"topic": "cats"}}
    ]
    assert "step_inputs" not in user_entry
    assert "step_outputs" not in user_entry


def test_spec_example_iteration_running():
    states = {
        "loop_1": _loop_record(),
        "gen_image#0": _iteration(0),
        "gen_image#1": _iteration(1),
        "gen_image#2": _iteration(2, RUNNING),
    }

    entries = _entries(_loop_steps(), states)

    loop_entry = entries["loop_1"]
    assert loop_entry["state"] == "STATE_IN_PROGRESS"
    assert loop_entry["total_iterations"] == 3
    assert loop_entry["history"] == [
        {
            "step_inputs": states["loop_1"].inputs,
            "step_outputs": states["loop_1"].outputs,
        }
    ]
    assert loop_entry["end_time"] is None

    body = entries["gen_image"]
    assert body["state"] == "STATE_IN_PROGRESS"
    assert body["total_iterations"] == 3
    assert body["history"] == [
        {
            "step_inputs": {"prompt": "Studio lighting", "input_images": [100]},
            "step_outputs": {"generated_image": [500]},
        },
        {
            "step_inputs": {"prompt": "Studio lighting", "input_images": [101]},
            "step_outputs": {"generated_image": [501]},
        },
    ]
    assert "step_inputs" not in body
    assert body["end_time"] is None


def test_all_iterations_completed_succeeds():
    states = {
        "loop_1": _loop_record(total=2),
        "gen_image#1": _iteration(1),
        "gen_image#0": _iteration(0),
    }

    entries = _entries(_loop_steps(), states)

    assert entries["loop_1"]["state"] == "STATE_SUCCEEDED"
    assert entries["loop_1"]["end_time"] == LATER.isoformat()
    body = entries["gen_image"]
    assert body["state"] == "STATE_SUCCEEDED"
    # Ordered by iteration number.
    assert [h["step_outputs"] for h in body["history"]] == [
        {"generated_image": [500]},
        {"generated_image": [501]},
    ]
    assert body["end_time"] == LATER.isoformat()


def test_failed_iteration_fails_loop_and_body():
    states = {
        "loop_1": _loop_record(),
        "gen_image#0": _iteration(0),
        "gen_image#1": _iteration(1, FAILED),
    }

    entries = _entries(_loop_steps(), states)

    assert entries["loop_1"]["state"] == "STATE_FAILED"
    assert entries["gen_image"]["state"] == "STATE_FAILED"
    assert entries["gen_image"]["error"]["detail"] == "boom"
    assert len(entries["gen_image"]["history"]) == 1


def test_zero_iterations_succeeds_with_empty_history():
    entries = _entries(_loop_steps(), {"loop_1": _loop_record(total=0)})

    assert entries["loop_1"]["state"] == "STATE_SUCCEEDED"
    assert entries["loop_1"]["total_iterations"] == 0
    assert entries["gen_image"]["history"] == []
    assert entries["gen_image"]["state"] == "STATE_SUCCEEDED"


def test_unresolved_loop_has_pending_body():
    entries = _entries(_loop_steps(), {"loop_1": _loop_record(status=RUNNING)})

    assert entries["loop_1"]["state"] == "STATE_IN_PROGRESS"
    assert entries["loop_1"]["total_iterations"] is None
    assert entries["loop_1"]["history"] == []
    body = entries["gen_image"]
    assert body["state"] == "STATE_PENDING"
    assert body["history"] == []
    assert body["total_iterations"] is None


def test_loop_failure_and_pending_loop():
    failed = _entries(_loop_steps(), {"loop_1": _loop_record(status=FAILED)})
    assert failed["loop_1"]["state"] == "STATE_FAILED"

    pending = _entries(_loop_steps(), {"loop_1": _loop_record(status=PENDING)})
    assert pending["loop_1"]["state"] == "STATE_PENDING"


def test_between_iterations_is_in_progress():
    states = {"loop_1": _loop_record(), "gen_image#0": _iteration(0)}

    entries = _entries(_loop_steps(), states)

    assert entries["loop_1"]["state"] == "STATE_IN_PROGRESS"
    assert entries["gen_image"]["state"] == "STATE_IN_PROGRESS"


def test_resolved_loop_before_first_iteration():
    entries = _entries(_loop_steps(), {"loop_1": _loop_record()})

    assert entries["loop_1"]["state"] == "STATE_IN_PROGRESS"
    assert entries["gen_image"]["state"] == "STATE_PENDING"
    assert entries["gen_image"]["total_iterations"] == 3


def test_legacy_record_reconstructs_inputs():
    steps = [
        UserInputStep(step_id="user_input"),
        GenerateTextStep(
            step_id="text",
            inputs=GenerateTextInputs(
                prompt=_ref("user_input", "topic"), extra="x"
            ),
            settings=GenerateTextSettings(
                model="gemini-2.5-flash", temperature=1
            ),
        ),
        ImageStep(
            step_id="img",
            inputs=ImageInputs(
                prompt=_ref("text", "generated_text"), input_image=[9]
            ),
            settings=ImageSettings(mode="generate_image"),
        ),
    ]
    states = {
        "text": StepState(
            status=COMPLETED, outputs={"generated_text": "A cat"}
        ),
        "img": StepState(status=COMPLETED, outputs={"edited_image": [7]}),
    }

    entries = _entries(steps, states, {"topic": "cats"})

    assert entries["text"]["history"][0]["step_inputs"]["prompt"] == "cats"
    assert entries["text"]["total_iterations"] is None
    img = entries["img"]["history"][0]
    assert img["step_inputs"] == {"prompt": "A cat"}
    assert img["step_outputs"] == {"generated_image": [7]}


def test_persisted_inputs_win_over_reconstruction():
    steps = [
        UserInputStep(step_id="user_input"),
        GenerateTextStep(
            step_id="text",
            inputs=GenerateTextInputs(prompt="Hi <name>"),
            settings=GenerateTextSettings(
                model="gemini-2.5-flash", temperature=1
            ),
        ),
    ]
    states = {
        "text": StepState(
            status=COMPLETED,
            inputs={"prompt": "Hi Bob"},
            outputs={"generated_text": "Hello"},
            started_at=NOW,
            completed_at=LATER,
            attempts=2,
        )
    }

    entries = _entries(steps, states)

    entry = entries["text"]
    assert entry["history"][0]["step_inputs"] == {"prompt": "Hi Bob"}
    assert entry["state"] == "STATE_SUCCEEDED"
    assert entry["attempts"] == 2
    assert entry["end_time"] == LATER.isoformat()


@pytest.mark.parametrize("status", [PENDING, RUNNING, FAILED])
def test_non_completed_records_have_empty_history(status):
    steps = [
        GenerateTextStep(
            step_id="text",
            inputs=GenerateTextInputs(prompt="x"),
            settings=GenerateTextSettings(
                model="gemini-2.5-flash", temperature=1
            ),
        ),
    ]

    entries = _entries(steps, {"text": StepState(status=status)})

    assert entries["text"]["history"] == []


def test_invalid_loop_snapshot_falls_back_to_plain_entries():
    steps = _loop_steps(end="missing")

    entries = _entries(steps, {"loop_1": _loop_record()})

    assert entries["loop_1"]["state"] == "STATE_SUCCEEDED"
    assert "gen_image" not in entries
