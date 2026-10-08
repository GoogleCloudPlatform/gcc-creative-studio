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

"""``step_entries`` of ``GET /api/workflows/{id}/runs/{run_id}``.

Every entry exposes a ``history`` array with one
``{"step_inputs", "step_outputs"}`` item per completed record: one for
regular steps, one per completed iteration for loop body steps
(``"<step_id>#<n>"`` records). ``Loop`` steps and their body steps report an
aggregate ``state`` covering every iteration plus ``total_iterations``.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from src.common.secret_redaction import install_secret_redaction
from src.workflows.schema.workflow_model import (
    NodeTypes,
    StepOutputReference,
    StepStatusEnum,
)
from src.workflows.schema.workflow_run_model import StepState
from src.workflows.step_state_keys import group_step_states
from src.workflows.workflow_constants import IMAGE_MODE_ALLOWED_INPUTS
from src.workflows.workflow_utils import interpolate_prompt_variables
from src.workflows.workflow_yaml_builder import LoopInfo, analyze_steps

logger = install_secret_redaction(logging.getLogger(__name__))

STATE_SUCCEEDED = "STATE_SUCCEEDED"
STATE_FAILED = "STATE_FAILED"
STATE_IN_PROGRESS = "STATE_IN_PROGRESS"
STATE_PENDING = "STATE_PENDING"

_STATE_MAP = {
    StepStatusEnum.COMPLETED: STATE_SUCCEEDED,
    StepStatusEnum.FAILED: STATE_FAILED,
    StepStatusEnum.RUNNING: STATE_IN_PROGRESS,
    StepStatusEnum.PENDING: STATE_PENDING,
}
_TERMINAL_STATES = frozenset({STATE_SUCCEEDED, STATE_FAILED})
_IMAGE_OUTPUT_KEYS = (
    "generated_image",
    "edited_image",
    "upscaled_image",
    "image_output",
)

Records = list[tuple[int | None, StepState]]


def _status(state: StepState) -> StepStatusEnum:
    return StepStatusEnum(state.status)


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _completed(records: Records) -> list[StepState]:
    """Completed records, non-iteration first then by iteration."""
    return [
        state
        for _, state in records
        if _status(state) == StepStatusEnum.COMPLETED
    ]


def _loop_graph(
    steps: Sequence[Any],
) -> tuple[Mapping[str, LoopInfo], Mapping[str, str]]:
    """``(loops, loop_of)`` of the snapshot; empty if it is invalid."""
    try:
        graph = analyze_steps(steps)
    except ValueError as error:
        logger.warning("Could not analyze workflow snapshot loops: %s", error)
        return {}, {}
    return graph.loops, graph.loop_of


def _total_iterations(records: Records) -> int | None:
    """``total_iterations`` of a completed ``Loop`` record, else ``None``."""
    for iteration, state in records:
        if iteration is not None:
            continue
        if _status(state) != StepStatusEnum.COMPLETED:
            return None
        total = (state.outputs or {}).get("total_iterations")
        if isinstance(total, int) and not isinstance(total, bool):
            return max(total, 0)
        return None
    return None


def _normalize_outputs(step: Any, outputs: Mapping[str, Any] | None) -> dict:
    """Outputs as shown in the run details (image keys unified)."""
    raw_outputs = dict(outputs or {})
    if step.type != NodeTypes.IMAGE or not raw_outputs:
        return raw_outputs
    img_val = next(
        (
            raw_outputs[key]
            for key in _IMAGE_OUTPUT_KEYS
            if raw_outputs.get(key)
        ),
        None,
    )
    return {"generated_image": img_val} if img_val is not None else raw_outputs


def _resolve_value(
    value: Any, previous_outputs: Mapping[str, Mapping[str, Any]]
) -> Any:
    if isinstance(value, StepOutputReference):
        return previous_outputs.get(value.step, {}).get(value.output)
    if isinstance(value, dict) and "step" in value and "output" in value:
        return previous_outputs.get(value["step"], {}).get(value["output"])
    if isinstance(value, list):
        return [_resolve_value(item, previous_outputs) for item in value]
    return value


def _image_mode(step: Any) -> str:
    settings = step.settings
    if isinstance(settings, BaseModel):
        return getattr(settings, "mode", "generate_image")
    if isinstance(settings, dict):
        return settings.get("mode", "generate_image")
    return "generate_image"


def legacy_step_inputs(
    step: Any, previous_outputs: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Read-time inputs for records persisted before ``StepState.inputs``.

    Resolves ``StepOutputReference`` values against the latest completed
    outputs of upstream steps.
    """
    inputs = step.inputs
    if isinstance(inputs, BaseModel):
        raw_inputs = inputs.model_dump()
    elif isinstance(inputs, dict):
        raw_inputs = inputs
    else:
        raw_inputs = {}

    allowed: Sequence[str] | None = None
    if step.type == NodeTypes.IMAGE:
        allowed = IMAGE_MODE_ALLOWED_INPUTS.get(_image_mode(step), ["prompt"])
    step_inputs = {
        name: _resolve_value(value, previous_outputs)
        for name, value in raw_inputs.items()
        if value is not None and (allowed is None or name in allowed)
    }
    prompt = step_inputs.get("prompt")
    if step.type == NodeTypes.GENERATE_TEXT and isinstance(prompt, str):
        step_inputs["prompt"] = interpolate_prompt_variables(
            prompt=prompt, variables=step_inputs, keep_unresolved=True
        )
    return step_inputs


def _body_state(records: Records, total: int | None) -> str:
    """Aggregate state of a loop body step over its iterations."""
    statuses = [_status(state) for _, state in records]
    if StepStatusEnum.FAILED in statuses:
        return STATE_FAILED
    if total is None:
        # Loop not resolved yet: no iteration can have started.
        return STATE_IN_PROGRESS if statuses else STATE_PENDING
    completed = statuses.count(StepStatusEnum.COMPLETED)
    if completed >= total:
        return STATE_SUCCEEDED
    if not statuses:
        return STATE_PENDING
    return STATE_IN_PROGRESS


def _loop_state(
    loop_records: Records,
    body_records: Sequence[Records],
    total: int | None,
) -> str:
    """Aggregate state of a ``Loop`` step over its whole lifecycle."""
    loop_statuses = [_status(state) for _, state in loop_records]
    body_statuses = [
        _status(state) for records in body_records for _, state in records
    ]
    if StepStatusEnum.FAILED in (*loop_statuses, *body_statuses):
        return STATE_FAILED
    if not loop_statuses:
        return STATE_PENDING
    if StepStatusEnum.COMPLETED not in loop_statuses or total is None:
        return _STATE_MAP.get(loop_statuses[0], STATE_PENDING)
    if total == 0:
        return STATE_SUCCEEDED
    if any(
        status in (StepStatusEnum.RUNNING, StepStatusEnum.PENDING)
        for status in body_statuses
    ):
        return STATE_IN_PROGRESS
    if all(len(_completed(records)) >= total for records in body_records):
        return STATE_SUCCEEDED
    return STATE_IN_PROGRESS


def _error(records: Records) -> dict[str, Any] | None:
    """Error of the first failed record, else of the last record with one."""
    failed = [
        state
        for _, state in records
        if _status(state) == StepStatusEnum.FAILED and state.error
    ]
    with_error = failed or [state for _, state in records if state.error]
    if not with_error:
        return None
    error = with_error[0] if failed else with_error[-1]
    return error.error.model_dump(mode="json", exclude_none=True)


def _entry(
    step_id: str,
    state: str,
    records: Records,
    history: list[dict[str, Any]],
    total_iterations: int | None,
) -> dict[str, Any]:
    """Run details entry; loop entries pass the loop and body records."""
    started = [s.started_at for _, s in records if s.started_at is not None]
    ended = [s.completed_at for _, s in records if s.completed_at is not None]
    # Loop-related entries only end when their aggregate state is terminal.
    is_aggregate = total_iterations is not None or len(records) != 1
    end_time = None
    if ended and (not is_aggregate or state in _TERMINAL_STATES):
        end_time = _iso(max(ended))
    return {
        "step_id": step_id,
        "state": state,
        "history": history,
        "total_iterations": total_iterations,
        "start_time": _iso(min(started)) if started else None,
        "end_time": end_time,
        "attempts": max((s.attempts for _, s in records), default=0),
        "error": _error(records),
    }


def build_step_entries(
    steps: Sequence[Any],
    step_states: Mapping[str, StepState],
    *,
    user_inputs: dict[str, Any],
    started_at: datetime.datetime | None,
) -> list[dict[str, Any]]:
    """Builds the run details ``step_entries``.

    Args:
        steps: Validated steps of the run's ``workflow_snapshot``.
        step_states: ``workflow_runs.step_states`` (flat keys).
        user_inputs: Run ``input_args`` (outputs of the ``USER_INPUT`` step).
        started_at: Run start, used for the ``USER_INPUT`` entry.

    Returns:
        One entry per step (``USER_INPUT`` first). Steps without records
        are skipped, except loop body steps, which are listed as pending
        with an empty ``history``.
    """
    user_input_step = next(
        (step for step in steps if step.type == NodeTypes.USER_INPUT), None
    )
    user_input_step_id = (
        user_input_step.step_id if user_input_step else "user_input"
    )
    previous_outputs: dict[str, dict[str, Any]] = {
        user_input_step_id: user_inputs,
        "user_input": user_inputs,
    }
    entries: list[dict[str, Any]] = [
        {
            "step_id": user_input_step_id,
            "state": STATE_SUCCEEDED,
            "history": [{"step_inputs": {}, "step_outputs": user_inputs}],
            "start_time": _iso(started_at),
            "end_time": _iso(started_at),
        }
    ]

    loops, loop_of = _loop_graph(steps)
    grouped: dict[str, Records] = group_step_states(step_states)
    totals = {
        loop_id: _total_iterations(grouped.get(loop_id, []))
        for loop_id in loops
    }

    for step in steps:
        if step.type == NodeTypes.USER_INPUT:
            continue
        step_id = step.step_id
        records = grouped.get(step_id, [])
        loop_id = loop_of.get(step_id)
        if not records and loop_id is None:
            continue

        history = []
        for state in _completed(records):
            step_outputs = _normalize_outputs(step, state.outputs)
            history.append(
                {
                    "step_inputs": (
                        dict(state.inputs)
                        if state.inputs is not None
                        else legacy_step_inputs(step, previous_outputs)
                    ),
                    "step_outputs": step_outputs,
                }
            )
        if history:
            previous_outputs[step_id] = history[-1]["step_outputs"]

        entry_records = records
        if step_id in loops:
            total = totals[step_id]
            body_records = [
                grouped.get(body_id, []) for body_id in loops[step_id].body
            ]
            aggregate = _loop_state(records, body_records, total)
            entry_records = records + [
                record for body in body_records for record in body
            ]
        elif loop_id is not None:
            total = totals.get(loop_id)
            aggregate = _body_state(records, total)
        else:
            total = None
            aggregate = _STATE_MAP.get(_status(records[0][1]), STATE_PENDING)
        entries.append(
            _entry(step_id, aggregate, entry_records, history, total)
        )
    return entries
