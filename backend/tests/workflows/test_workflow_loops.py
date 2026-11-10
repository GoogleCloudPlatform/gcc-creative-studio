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

"""Loop-aware graph analysis, YAML generation and resume reconciliation."""

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

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
    ReferenceMediaOrAsset,
    StepOutputReference,
    StepStatusEnum,
    UserInputDefinition,
    UserInputSettings,
    UserInputStep,
    WorkflowBase,
)
from src.workflows.workflow_yaml_builder import (
    MAX_SOURCE_BYTES,
    analyze_steps,
    build_prior_outputs,
    build_workflow_definition,
    build_workflow_yaml,
    compute_step_hash,
    initial_step_states,
    reconcile_step_states_for_resume,
)

EXECUTOR_URL = "https://executor.example.com/api/workflows-executor"


def _ref(step: str, output: str) -> StepOutputReference:
    return StepOutputReference(step=step, output=output)


def _loop(
    step_id: str = "loop_1",
    *,
    end: str | None = "gen_image",
    mode: str = "folder",
    items_text: Any = None,
    linked_items: Any = None,
) -> LoopStep:
    return LoopStep(
        step_id=step_id,
        inputs=LoopInputs(
            items_text=items_text,
            linked_items=linked_items,
            loop_ending=_ref(end, "loop_ending") if end else None,
        ),
        settings=LoopSettings(
            mode=mode, folder_id=42 if mode == "folder" else None
        ),
    )


def _image(step_id: str = "gen_image", source: str = "loop_1") -> ImageStep:
    return ImageStep(
        step_id=step_id,
        inputs=ImageInputs(
            prompt="Studio lighting",
            input_images=_ref(source, "current_item"),
        ),
        settings=ImageSettings(),
    )


def _upstream_image(step_id: str) -> ImageStep:
    return ImageStep(
        step_id=step_id,
        inputs=ImageInputs(prompt="A product photo"),
        settings=ImageSettings(),
    )


def _photo_input() -> UserInputStep:
    return UserInputStep(
        step_id="user_in",
        settings=UserInputSettings(
            definitions=[UserInputDefinition(name="photo", type="image")]
        ),
    )


def _text(step_id: str, prompt: Any = "Write") -> GenerateTextStep:
    return GenerateTextStep(
        step_id=step_id,
        inputs=GenerateTextInputs(prompt=prompt),
        settings=GenerateTextSettings(model="gemini-2.5-flash", temperature=1),
    )


def _step_map(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in steps:
        for name, spec in entry.items():
            out[name] = spec
            for block in (spec.get("try"), spec.get("for")):
                if isinstance(block, dict) and "steps" in block:
                    out.update(_step_map(block["steps"]))
    return out


def _run_steps(definition: dict[str, Any]) -> list[dict[str, Any]]:
    main = _step_map(definition["main"]["steps"])
    return main["run_steps"]["try"]["steps"]


def _resolve_body(steps: list[Any]) -> dict[str, Any]:
    """Body of the ``/resolve-loop-items`` call of ``loop_1``."""
    definition = build_workflow_definition(steps, executor_url=EXECUTOR_URL)
    return _step_map(_run_steps(definition))["loop_1"]["try"]["args"]["body"]


class TestStepIdValidation:
    def test_hash_in_step_id_is_rejected_by_schema(self):
        with pytest.raises(ValidationError):
            _text("bad#1")

    def test_hash_in_snapshot_step_is_rejected(self):
        with pytest.raises(ValidationError):
            WorkflowBase.model_validate(
                {
                    "name": "wf",
                    "steps": [
                        {"step_id": "a#0", "type": "user_input"},
                    ],
                }
            )

    def test_loop_step_round_trips_through_union(self):
        workflow = WorkflowBase.model_validate(
            {
                "name": "wf",
                "steps": [
                    _loop().model_dump(mode="json"),
                    _image().model_dump(mode="json"),
                ],
            }
        )
        assert isinstance(workflow.steps[0], LoopStep)
        assert workflow.steps[0].settings.mode == "folder"

    def test_linked_loop_round_trips_through_union(self):
        linked_loop = _loop(
            mode="linked_items",
            linked_items=[
                _ref("img_a", "generated_image"),
                _ref("user_in", "photo"),
            ],
        )

        workflow = WorkflowBase.model_validate(
            {
                "name": "wf",
                "steps": [
                    linked_loop.model_dump(mode="json"),
                    _image().model_dump(mode="json"),
                ],
            }
        )

        loop_step = workflow.steps[0]
        assert isinstance(loop_step, LoopStep)
        assert loop_step.settings.mode == "linked_items"
        assert loop_step.inputs.linked_items == [
            _ref("img_a", "generated_image"),
            _ref("user_in", "photo"),
        ]

    def test_linked_items_accepts_single_reference(self):
        inputs = LoopInputs.model_validate(
            {"linked_items": {"step": "img_a", "output": "generated_image"}}
        )

        assert inputs.linked_items == _ref("img_a", "generated_image")

    def test_linked_items_round_trip_mixed_refs_and_picks(self):
        linked_items = [
            {"step": "img_a", "output": "generated_image"},
            {
                "previewUrl": "https://signed",
                "sourceMediaItem": {
                    "mediaItemId": 103,
                    "mediaIndex": 2,
                    "role": "input",
                },
            },
            {"previewUrl": "", "sourceAssetId": 7},
            101,
        ]

        loop_step = LoopStep.model_validate(
            {
                "step_id": "loop_1",
                "type": "loop",
                "inputs": {"linked_items": linked_items},
                "settings": {"mode": "linked_items"},
            }
        )
        parsed = loop_step.inputs.linked_items

        assert [type(entry) for entry in parsed] == [
            StepOutputReference,
            ReferenceMediaOrAsset,
            ReferenceMediaOrAsset,
            int,
        ]
        round_tripped = LoopStep.model_validate(
            loop_step.model_dump(mode="json")
        )
        assert round_tripped.inputs.linked_items == parsed

    def test_linked_items_accepts_single_gallery_pick(self):
        inputs = LoopInputs.model_validate(
            {"linked_items": {"previewUrl": "", "sourceAssetId": 7}}
        )

        assert inputs.linked_items == ReferenceMediaOrAsset(
            previewUrl="", sourceAssetId=7
        )

    def test_linked_items_rejects_text(self):
        with pytest.raises(ValidationError):
            LoopInputs.model_validate({"linked_items": ["hello"]})

    def test_old_loop_payload_still_validates(self):
        loop_step = LoopStep.model_validate(
            {
                "step_id": "loop_1",
                "type": "loop",
                "inputs": {"items_text": "a,b"},
                "settings": {"mode": "text_input"},
            }
        )

        assert loop_step.inputs.linked_items is None
        assert loop_step.settings.mode == "text_input"

    def test_unknown_loop_mode_is_rejected(self):
        with pytest.raises(ValidationError):
            LoopSettings(mode="everything")


class TestAnalyzeLoops:
    def test_valid_loop_excludes_back_edge(self):
        graph = analyze_steps([_loop(), _image()])

        assert [step.step_id for step in graph.order] == [
            "loop_1",
            "gen_image",
        ]
        assert graph.dependencies["loop_1"] == frozenset()
        assert graph.loops["loop_1"].end_step_id == "gen_image"
        assert graph.loops["loop_1"].body == ("gen_image",)
        assert graph.loop_of == {"gen_image": "loop_1"}
        assert graph.top_level_call_steps == ()

    def test_multi_step_body_in_order(self):
        steps = [
            _loop(end="caption"),
            _text("caption", prompt=_ref("gen_image", "generated_image")),
            _image(),
        ]

        graph = analyze_steps(steps)

        assert graph.loops["loop_1"].body == ("gen_image", "caption")

    @pytest.mark.parametrize(
        ("steps", "message"),
        [
            ([_loop(end=None), _image()], "must have its 'loop_ending'"),
            ([_loop(end="missing"), _image()], "must have its 'loop_ending'"),
            ([_loop(end="loop_1"), _image()], "must have its 'loop_ending'"),
            ([_loop(end="other"), _text("other")], "'current_item' output"),
            (
                [_loop(end="other"), _image(), _text("other")],
                "not reachable",
            ),
            (
                [
                    _loop(),
                    _image(),
                    _text("after", prompt=_ref("gen_image", "generated_image")),
                ],
                "cannot connect to downstream steps",
            ),
            (
                [
                    _loop(end="gen_image"),
                    _image(),
                    _text("sneaky", prompt=_ref("gen_image", "loop_ending")),
                ],
                "'loop_ending' outputs can only connect",
            ),
        ],
        ids=[
            "missing-ending",
            "unknown-ending",
            "self-ending",
            "unconnected-current-item",
            "unreachable-end",
            "post-loop-continuation",
            "loop-ending-to-non-loop",
        ],
    )
    def test_invalid_loops(self, steps, message):
        with pytest.raises(ValueError, match=message):
            analyze_steps(steps)

    def test_nested_loops_are_rejected(self):
        inner = LoopStep(
            step_id="loop_2",
            inputs=LoopInputs(
                items_text=_ref("loop_1", "current_item"),
                loop_ending=_ref("gen_image", "loop_ending"),
            ),
            settings=LoopSettings(mode="text_input"),
        )
        steps = [_loop(), inner, _image(source="loop_2")]

        with pytest.raises(ValueError):
            analyze_steps(steps)

    def test_one_step_cannot_end_two_loops(self):
        loop_2 = _loop("loop_2", end="gen_image")
        with pytest.raises(ValueError, match="more than one loop"):
            analyze_steps([_loop(), loop_2, _image()])

    def test_overlapping_bodies_are_rejected(self):
        shared = ImageStep(
            step_id="shared",
            inputs=ImageInputs(
                prompt="x",
                input_images=[
                    _ref("loop_1", "current_item"),
                    _ref("loop_2", "current_item"),
                ],
            ),
            settings=ImageSettings(),
        )
        steps = [
            _loop(end="shared"),
            _loop("loop_2", end="other"),
            shared,
            _image("other", source="loop_2"),
        ]
        with pytest.raises(ValueError):
            analyze_steps(steps)


class TestLoopYaml:
    def test_folder_loop_yaml_structure(self):
        user_in = UserInputStep(step_id="user_in")
        steps = [user_in, _text("pre"), _loop(), _image()]

        definition = build_workflow_definition(steps, executor_url=EXECUTOR_URL)
        run_steps = _step_map(_run_steps(definition))

        # Loop is never gated; the top-level step's gate jumps to its mark.
        assert "loop_1_gate" not in run_steps
        assert "gen_image_gate" not in run_steps
        pre_gate = run_steps["pre_gate"]["switch"][0]
        assert pre_gate["next"] == "loop_1_mark"

        resolve = run_steps["loop_1"]["try"]["call"]
        assert resolve == "http.post"
        args = run_steps["loop_1"]["try"]["args"]
        assert args["url"] == f"{EXECUTOR_URL}/resolve-loop-items"
        assert args["body"]["step_id"] == "loop_1"
        assert args["body"]["inputs"] == {}
        assert args["body"]["config"]["folder_id"] == 42
        assert args["body"]["config"]["item_type"] == "image"

        loop_block = run_steps["loop_1_loop"]["for"]
        assert loop_block["value"] == "loop_1_item"
        assert loop_block["index"] == "loop_1_idx"
        assert loop_block["in"] == "${loop_1_items}"

        body_args = run_steps["gen_image"]["try"]["args"]["body"]
        assert body_args["iteration"] == "${loop_1_idx}"
        assert body_args["inputs"]["input_images"] == (
            "${loop_1_out.current_item}"
        )
        mark = run_steps["gen_image_mark"]["assign"][0]["current_step"]
        assert mark == '${"gen_image#" + string(loop_1_idx)}'

        init = {
            key: value
            for item in _step_map(definition["main"]["steps"])["init"]["assign"]
            for key, value in item.items()
        }
        assert init["loop_1_items"] is None
        assert init["gen_image_out"] is None

    def test_text_loop_sends_items_text(self):
        steps = [
            _text("pre"),
            _loop(mode="text_input", items_text=_ref("pre", "generated_text")),
            _image(),
        ]

        definition = build_workflow_definition(steps, executor_url=EXECUTOR_URL)
        run_steps = _step_map(_run_steps(definition))

        body = run_steps["loop_1"]["try"]["args"]["body"]
        assert body["inputs"] == {"items_text": "${pre_out.generated_text}"}
        assert body["config"]["mode"] == "text_input"

    def test_linked_loop_sends_linked_items_in_link_order(self):
        linked_loop = _loop(
            mode="linked_items",
            linked_items=[
                _ref("img_b", "generated_image"),
                _ref("user_in", "photo"),
                _ref("img_a", "generated_image"),
            ],
        )
        steps = [
            _photo_input(),
            _upstream_image("img_a"),
            _upstream_image("img_b"),
            linked_loop,
            _image(),
        ]

        definition = build_workflow_definition(steps, executor_url=EXECUTOR_URL)
        run_steps = _step_map(_run_steps(definition))

        body = run_steps["loop_1"]["try"]["args"]["body"]
        assert body["inputs"] == {
            "linked_items": [
                "${img_b_out.generated_image}",
                "${args.photo}",
                "${img_a_out.generated_image}",
            ]
        }
        assert body["config"]["mode"] == "linked_items"
        # Upstreams are top-level, gated steps that run before the loop.
        assert "img_a_gate" in run_steps
        img_b_gate = run_steps["img_b_gate"]["switch"][0]
        assert img_b_gate["next"] == "loop_1_mark"

    def test_linked_loop_single_reference_is_sent_as_list(self):
        steps = [
            _upstream_image("img_a"),
            _loop(
                mode="linked_items",
                linked_items=_ref("img_a", "generated_image"),
            ),
            _image(),
        ]

        body = _resolve_body(steps)

        assert body["inputs"] == {
            "linked_items": ["${img_a_out.generated_image}"]
        }

    def test_linked_loop_mixes_expressions_and_gallery_picks(self):
        linked_loop = _loop(
            mode="linked_items",
            linked_items=[
                ReferenceMediaOrAsset(
                    previewUrl="https://signed", sourceAssetId=7
                ),
                _ref("img_a", "generated_image"),
                ReferenceMediaOrAsset(
                    previewUrl="https://signed",
                    sourceMediaItem={
                        "mediaItemId": 103,
                        "mediaIndex": 2,
                        "role": "${sys.get_env('SECRET')}",
                    },
                ),
                _ref("user_in", "photo"),
                101,
            ],
        )
        steps = [
            _photo_input(),
            _upstream_image("img_a"),
            linked_loop,
            _image(),
        ]

        body = _resolve_body(steps)

        assert body["inputs"] == {
            "linked_items": [
                {"sourceAssetId": 7},
                "${img_a_out.generated_image}",
                {"sourceMediaItem": {"mediaItemId": 103, "mediaIndex": 2}},
                "${args.photo}",
                101,
            ]
        }

    def test_linked_loop_id_less_pick_stays_non_empty(self):
        linked_loop = _loop(
            mode="linked_items",
            linked_items=[ReferenceMediaOrAsset(previewUrl="https://x")],
        )

        body = _resolve_body([linked_loop, _image()])

        assert body["inputs"] == {"linked_items": [{"sourceAssetId": None}]}

    def test_gallery_picks_add_no_dependencies(self):
        linked_loop = _loop(
            mode="linked_items",
            linked_items=[
                ReferenceMediaOrAsset(previewUrl="", sourceAssetId=7),
                _ref("img_a", "generated_image"),
                101,
            ],
        )

        graph = analyze_steps([_upstream_image("img_a"), linked_loop, _image()])

        assert graph.dependencies["loop_1"] == frozenset({"img_a"})
        assert graph.loops["loop_1"].body == ("gen_image",)

    def test_linked_loop_without_links_sends_empty_list(self):
        steps = [_loop(mode="linked_items"), _image()]

        body = _resolve_body(steps)

        assert body["inputs"] == {"linked_items": []}

    @pytest.mark.parametrize(
        ("mode", "expected_inputs"),
        [
            ("folder", {}),
            ("text_input", {"items_text": "a, b"}),
        ],
    )
    def test_linked_items_not_sent_in_other_modes(self, mode, expected_inputs):
        stale_loop = _loop(
            mode=mode,
            items_text="a, b",
            linked_items=[_ref("img_a", "generated_image")],
        )
        steps = [_upstream_image("img_a"), stale_loop, _image()]

        body = _resolve_body(steps)

        assert body["inputs"] == expected_inputs

    def test_linked_upstreams_are_top_level_and_referenced(self):
        steps = [
            _photo_input(),
            _upstream_image("img_a"),
            _loop(
                mode="linked_items",
                linked_items=[
                    _ref("img_a", "generated_image"),
                    _ref("user_in", "photo"),
                ],
            ),
            _image(),
        ]

        graph = analyze_steps(steps)

        assert graph.dependencies["loop_1"] == frozenset({"img_a", "user_in"})
        assert graph.loops["loop_1"].body == ("gen_image",)
        assert [step.step_id for step in graph.top_level_call_steps] == [
            "img_a"
        ]
        assert graph.referenced_outputs["img_a"] == frozenset(
            {"generated_image"}
        )

    def test_body_step_linked_into_other_loop_is_nested(self):
        other_loop = _loop(
            "loop_2",
            end="other",
            mode="linked_items",
            linked_items=[_ref("gen_image", "generated_image")],
        )
        steps = [_loop(), _image(), other_loop, _image("other", "loop_2")]

        with pytest.raises(ValueError, match="Nested loops"):
            analyze_steps(steps)

    def test_yaml_is_valid_and_within_limit(self):
        yaml_text = build_workflow_yaml(
            [_loop(), _image()], executor_url=EXECUTOR_URL
        )

        parsed = yaml.safe_load(yaml_text)
        assert "main" in parsed
        assert len(yaml_text.encode()) < MAX_SOURCE_BYTES

    def test_non_loop_yaml_has_no_loop_blocks(self):
        yaml_text = build_workflow_yaml(
            [_text("a"), _text("b")], executor_url=EXECUTOR_URL
        )
        assert "resolve-loop-items" not in yaml_text
        assert "for:" not in yaml_text


class TestLoopStates:
    def test_initial_states_skip_body_steps(self):
        states = initial_step_states([_loop(), _image()])
        assert set(states) == {"loop_1"}

    def test_prior_outputs_ignore_iteration_records(self):
        states = {
            "pre": {"status": "completed", "outputs": {"generated_text": "x"}},
            "gen_image#0": {
                "status": "completed",
                "outputs": {"generated_image": [1]},
            },
        }
        prior = build_prior_outputs([_text("pre"), _loop(), _image()], states)
        assert "gen_image" not in prior
        assert "gen_image#0" not in prior
        assert "pre" in prior


class TestLoopResume:
    @staticmethod
    def _states(loop_total: int, body: dict[str, dict]) -> dict[str, Any]:
        loop = _loop()
        return {
            "loop_1": {
                "status": StepStatusEnum.COMPLETED.value,
                "definition_hash": compute_step_hash(loop),
                "outputs": {
                    "items": [[n] for n in range(loop_total)],
                    "total_iterations": loop_total,
                    "total_found": loop_total,
                    "truncated": False,
                },
            },
            **body,
        }

    def test_keeps_completed_iterations_and_drops_failed(self):
        steps = [_loop(), _image()]
        states = self._states(
            3,
            {
                "gen_image#0": {
                    "status": "completed",
                    "outputs": {"generated_image": [5]},
                },
                "gen_image#1": {"status": "failed", "attempts": 3},
            },
        )

        reconciled, first = reconcile_step_states_for_resume(
            steps,
            states,
            run_definition_hash="h",
            previous_steps=steps,
        )

        assert "gen_image#0" in reconciled
        assert "gen_image#1" not in reconciled
        assert reconciled["loop_1"]["status"] == "completed"
        assert first == "gen_image"

    def test_keeps_cap_exceeded_job(self):
        steps = [_loop(), _image()]
        states = self._states(
            1,
            {
                "gen_image#0": {
                    "status": "failed",
                    "job_id": 77,
                    "error": {"category": "CAP_EXCEEDED"},
                },
            },
        )

        reconciled, first = reconcile_step_states_for_resume(
            steps, states, run_definition_hash="h", previous_steps=steps
        )

        assert reconciled["gen_image#0"]["job_id"] == 77
        assert reconciled["gen_image#0"]["status"] == "pending"
        assert first == "gen_image"

    def test_all_iterations_done_is_complete(self):
        steps = [_loop(), _image()]
        states = self._states(
            1,
            {
                "gen_image#0": {
                    "status": "completed",
                    "outputs": {"generated_image": [5]},
                },
            },
        )

        _, first = reconcile_step_states_for_resume(
            steps, states, run_definition_hash="h", previous_steps=steps
        )

        assert first is None

    def test_changed_body_definition_drops_iterations(self):
        old_steps = [_loop(), _image()]
        new_image = _image()
        new_image.inputs.prompt = "Different"
        states = self._states(
            1,
            {
                "gen_image#0": {
                    "status": "completed",
                    "outputs": {"generated_image": [5]},
                },
            },
        )

        reconciled, first = reconcile_step_states_for_resume(
            [_loop(), new_image],
            states,
            run_definition_hash="h",
            previous_steps=old_steps,
        )

        assert "gen_image#0" not in reconciled
        assert first == "gen_image"
