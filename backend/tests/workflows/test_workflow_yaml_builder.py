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

"""Unit tests for the GCP Workflows YAML builder."""

from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from src.workflows.schema.workflow_model import (
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    ImageInputs,
    ImageSettings,
    ImageStep,
    NodeTypes,
    StepOutputReference,
    StepStatusEnum,
    UserInputStep,
)
from src.workflows.schema.workflow_run_model import StepState
from src.workflows.workflow_yaml_builder import (
    MAX_SOURCE_BYTES,
    PREDICATE_NAME,
    YAML_HEADER,
    analyze_steps,
    build_prior_outputs,
    build_workflow_definition,
    build_workflow_yaml,
    json_size,
    missing_required_args,
    prior_outputs_args,
    required_args,
)

EXECUTOR_URL = "https://executor.example.com/api/workflows-executor"


def _user_input_step(step_id: str = "input_prompt") -> UserInputStep:
    return UserInputStep(step_id=step_id)


def _text_step(
    step_id: str,
    prompt: Any = "Write a story",
    *,
    extra_inputs: dict[str, Any] | None = None,
) -> GenerateTextStep:
    inputs_data: dict[str, Any] = {"prompt": prompt}
    if extra_inputs:
        inputs_data.update(extra_inputs)
    return GenerateTextStep(
        step_id=step_id,
        inputs=GenerateTextInputs(**inputs_data),
        settings=GenerateTextSettings(
            model="gemini-2.5-flash", temperature=0.7
        ),
    )


def _image_step(step_id: str, prompt: Any = "A cat") -> ImageStep:
    return ImageStep(
        step_id=step_id,
        inputs=ImageInputs(prompt=prompt),
        settings=ImageSettings(),
    )


def _step_map(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Indexes a GCP Workflows steps list by step name."""
    out: dict[str, dict[str, Any]] = {}
    for entry in steps:
        for name, spec in entry.items():
            out[name] = spec
    return out


class TestAnalyzeSteps:
    """Dependency analysis and topological ordering tests."""

    def test_topological_sort_reorders_dependent_steps(self):
        # step_b depends on step_a, but step_b is listed first.
        step_b = _image_step(
            "step_b",
            prompt=StepOutputReference(step="step_a", output="generated_text"),
        )
        step_a = _text_step(
            "step_a",
            prompt=StepOutputReference(step="user_in", output="topic"),
        )
        user_in = _user_input_step("user_in")

        graph = analyze_steps([step_b, step_a, user_in])

        assert [s.step_id for s in graph.order] == [
            "user_in",
            "step_a",
            "step_b",
        ]
        assert [s.step_id for s in graph.call_steps] == ["step_a", "step_b"]
        assert graph.user_input_ids == frozenset({"user_in"})
        assert graph.dependencies["step_b"] == frozenset({"step_a"})
        assert graph.dependencies["step_a"] == frozenset({"user_in"})
        assert graph.referenced_outputs == {
            "step_a": frozenset({"generated_text"}),
            "step_b": frozenset(),
        }

    def test_ties_preserve_definition_order(self):
        steps = [
            _text_step("first_independent"),
            _text_step("second_independent"),
            _image_step("third_independent"),
        ]
        graph = analyze_steps(steps)
        assert [s.step_id for s in graph.order] == [
            "first_independent",
            "second_independent",
            "third_independent",
        ]

    def test_duplicate_step_ids_raise_value_error(self):
        steps = [_text_step("dup_step"), _image_step("dup_step")]
        with pytest.raises(ValueError, match="Duplicate step ids: dup_step"):
            analyze_steps(steps)

    def test_cycle_detected_raises_value_error(self):
        step_a = _text_step(
            "step_a",
            prompt=StepOutputReference(step="step_b", output="generated_text"),
        )
        step_b = _text_step(
            "step_b",
            prompt=StepOutputReference(step="step_a", output="generated_text"),
        )
        with pytest.raises(ValueError, match="Cycle detected"):
            analyze_steps([step_a, step_b])

    def test_unknown_step_reference_is_ignored_in_dependencies(self):
        step_a = _text_step(
            "step_a",
            prompt=StepOutputReference(
                step="external_step", output="generated_text"
            ),
        )
        graph = analyze_steps([step_a])
        assert graph.dependencies["step_a"] == frozenset()


class TestRequiredArgsAndPriorOutputs:
    """Tests for required_args, missing_required_args and prior_outputs."""

    def test_required_args_and_missing_required_args(self):
        user_in = _user_input_step("user_in")
        step_a = _text_step(
            "step_a",
            prompt="Write about <topic>",
            extra_inputs={
                "topic": [
                    StepOutputReference(step="user_in", output="user_topic"),
                    {
                        "nested": StepOutputReference(
                            step="user_in", output="style"
                        )
                    },
                ]
            },
        )
        steps = [user_in, step_a]

        assert required_args(steps) == ["style", "user_topic", "workspace_id"]
        assert missing_required_args(steps, None) == [
            "style",
            "user_topic",
            "workspace_id",
        ]
        assert missing_required_args(
            steps,
            {"workspace_id": 1, "user_topic": "cats", "style": None},
        ) == ["style"]
        assert (
            missing_required_args(
                steps,
                {"workspace_id": 1, "user_topic": "cats", "style": "noir"},
            )
            == []
        )

    def test_required_args_empty_when_no_call_steps(self):
        assert required_args([_user_input_step("user_in")]) == []

    def test_build_prior_outputs_filters_to_referenced_outputs(self):
        step_a = _text_step("step_a")
        step_b = _image_step(
            "step_b",
            prompt=StepOutputReference(step="step_a", output="generated_text"),
        )
        step_c = _text_step("step_c")
        steps = [step_a, step_b, step_c]

        step_states = {
            "step_a": StepState(
                status=StepStatusEnum.COMPLETED,
                outputs={
                    "generated_text": "hello",
                    "unreferenced_blob": "x" * 1000,
                },
            ),
            "step_b": {
                "status": StepStatusEnum.COMPLETED.value,
                "outputs": {"images": [10, 20]},
            },
            "step_c": StepState(
                status=StepStatusEnum.FAILED,
                outputs={"generated_text": "ignored"},
            ),
            "invalid": "not-a-mapping",
        }

        prior = build_prior_outputs(steps, step_states)

        # step_a includes only referenced output; step_b has {} so its gate still skips it.
        assert prior == {
            "step_a": {"generated_text": "hello"},
            "step_b": {},
        }

    def test_prior_outputs_args_inline_vs_fetch_checkpoint(self):
        step_a = _text_step("step_a")
        step_b = _image_step(
            "step_b",
            prompt=StepOutputReference(step="step_a", output="generated_text"),
        )
        steps = [step_a, step_b]

        assert prior_outputs_args(steps, {}) == {}

        small_state = {
            "step_a": {
                "status": StepStatusEnum.COMPLETED.value,
                "outputs": {"generated_text": "short text"},
            }
        }
        inline_args = prior_outputs_args(steps, small_state)
        assert inline_args == {
            "prior_outputs": {"step_a": {"generated_text": "short text"}}
        }

        large_state = {
            "step_a": {
                "status": StepStatusEnum.COMPLETED.value,
                "outputs": {"generated_text": "a" * 40_000},
            }
        }
        assert json_size(large_state) > 32 * 1024
        checkpoint_args = prior_outputs_args(steps, large_state)
        assert checkpoint_args == {"fetch_checkpoint": True}


class TestBuildWorkflowYaml:
    """Tests for YAML structure, gates, retry policy, callbacks and limits."""

    def test_build_workflow_yaml_structure_and_expressions(self):
        user_in = _user_input_step("user_in")
        step_a = _text_step(
            "step_a",
            prompt=StepOutputReference(step="user_in", output="prompt_text"),
        )
        step_b = _image_step(
            "step_b",
            prompt=StepOutputReference(step="step_a", output="generated_text"),
        )

        yaml_text = build_workflow_yaml(
            [user_in, step_a, step_b],
            executor_url=EXECUTOR_URL + "/",
            step_timeout_seconds=300,
        )

        assert yaml_text.startswith(YAML_HEADER)
        assert "# Generated by Creative Studio. Do not edit." in yaml_text
        # Ensure _NoAliasDumper emitted no YAML anchors or aliases.
        assert "&id" not in yaml_text
        assert "*id" not in yaml_text

        parsed = yaml.safe_load(yaml_text)
        assert "main" in parsed
        assert PREDICATE_NAME in parsed
        assert parsed["main"]["params"] == ["args"]

        main_steps = _step_map(parsed["main"]["steps"])
        assert "init" in main_steps
        assert "run_steps" in main_steps
        assert "success_gate" in main_steps
        assert "report_success" in main_steps
        assert "done" in main_steps

        # Verify init declares <step>_out variables before the try block.
        init_assignments = {
            k: v
            for item in main_steps["init"]["assign"]
            for k, v in item.items()
        }
        assert init_assignments["executor_url"] == EXECUTOR_URL
        assert init_assignments["step_a_out"] is None
        assert init_assignments["step_b_out"] is None

        # Verify run_steps try block contains checkpoint + step gates + calls.
        try_steps = _step_map(main_steps["run_steps"]["try"]["steps"])
        assert "checkpoint_gate" in try_steps
        assert "load_checkpoint" in try_steps
        assert "save_checkpoint" in try_steps
        assert "prior_gate" in try_steps
        assert "init_outputs" in try_steps

        # Step A gate skips to step_b_gate when step_a_out != null.
        assert try_steps["step_a_gate"]["switch"] == [
            {"condition": "${step_a_out != null}", "next": "step_b_gate"}
        ]
        # Step B gate skips to steps_done when step_b_out != null.
        assert try_steps["step_b_gate"]["switch"] == [
            {"condition": "${step_b_out != null}", "next": "steps_done"}
        ]

        # Step A marker and call body.
        assert try_steps["step_a_mark"]["assign"] == [
            {"current_step": "step_a"}
        ]
        step_a_call = try_steps["step_a"]["try"]
        assert step_a_call["call"] == "http.post"
        assert step_a_call["args"]["url"] == f"{EXECUTOR_URL}/generate_text"
        assert step_a_call["args"]["timeout"] == 300
        assert step_a_call["args"]["body"]["run_id"] == "${run_id}"
        assert step_a_call["args"]["body"]["step_id"] == "step_a"
        assert step_a_call["args"]["body"]["execution_id"] == "${exec_id}"
        assert (
            step_a_call["args"]["body"]["workspace_id"]
            == "${args.workspace_id}"
        )
        # User input stays ${args.prompt_text}.
        assert (
            step_a_call["args"]["body"]["inputs"]["prompt"]
            == "${args.prompt_text}"
        )
        assert try_steps["step_a"]["retry"] == {
            "predicate": f"${{{PREDICATE_NAME}}}",
            "max_retries": 3,
            "backoff": {
                "initial_delay": 5,
                "max_delay": 120,
                "multiplier": 2,
            },
        }
        assert try_steps["step_a_save"]["assign"] == [
            {"step_a_out": "${step_a_result.body}"}
        ]

        # Step B reads ${step_a_out.generated_text} instead of step_a_result.
        step_b_call = try_steps["step_b"]["try"]
        assert (
            step_b_call["args"]["body"]["inputs"]["prompt"]
            == "${step_a_out.generated_text}"
        )

        # Verify except block reports failure and reraises.
        except_steps = _step_map(main_steps["run_steps"]["except"]["steps"])
        assert "failure_gate" in except_steps
        assert "report_failure" in except_steps
        assert except_steps["reraise"] == {"raise": "${e}"}
        failure_body = except_steps["report_failure"]["try"]["args"]["body"]
        assert failure_body == {
            "execution_id": "${exec_id}",
            "status": "FAILED",
            "step_id": "${current_step}",
            "error": "${e}",
        }

        # Verify success callback and return map.
        success_body = main_steps["report_success"]["try"]["args"]["body"]
        assert success_body == {
            "execution_id": "${exec_id}",
            "status": "SUCCEEDED",
        }
        assert main_steps["done"]["return"] == {
            "step_a": "${step_a_out}",
            "step_b": "${step_b_out}",
        }

    def test_is_transient_subworkflow_checks_504_and_retry_safe(self):
        defn = build_workflow_definition(
            [_text_step("step_a")], executor_url=EXECUTOR_URL
        )
        sub = defn[PREDICATE_NAME]
        assert sub["params"] == ["e"]
        sub_steps = _step_map(sub["steps"])
        assert "check_retry_safe" in sub_steps
        retry_safe_cond = sub_steps["check_retry_safe"]["switch"][0][
            "condition"
        ]
        assert "retry_safe" in retry_safe_cond
        check_tags_switches = sub_steps["check_tags"]["switch"]
        assert any("code == 504" in s["condition"] for s in check_tags_switches)
        assert any(
            "TimeoutError" in s["condition"] for s in check_tags_switches
        )

    def test_non_identifier_output_uses_bracket_notation(self):
        step_a = _text_step("step_a")
        step_b = _text_step(
            "step_b",
            prompt=StepOutputReference(step="step_a", output="weird key"),
        )
        defn = build_workflow_definition(
            [step_a, step_b], executor_url=EXECUTOR_URL
        )
        try_steps = _step_map(
            _step_map(defn["main"]["steps"])["run_steps"]["try"]["steps"]
        )
        prompt_expr = try_steps["step_b"]["try"]["args"]["body"]["inputs"][
            "prompt"
        ]
        assert prompt_expr == '${step_a_out["weird key"]}'

    def test_many_steps_split_assignments_into_chunks_of_50(self):
        steps = [_text_step(f"step_{i}") for i in range(55)]
        defn = build_workflow_definition(steps, executor_url=EXECUTOR_URL)
        main_steps = _step_map(defn["main"]["steps"])
        assert "init" in main_steps
        assert "init_2" in main_steps
        try_steps = _step_map(main_steps["run_steps"]["try"]["steps"])
        assert "init_outputs" in try_steps
        assert "init_outputs_2" in try_steps

    @pytest.mark.parametrize(
        "bad_step_id",
        ["1starts_with_digit", "has-dash", "", "a" * 129, 123],
    )
    def test_invalid_step_id_raises_value_error(self, bad_step_id):
        fake_step = SimpleNamespace(
            step_id=bad_step_id,
            type=NodeTypes.GENERATE_TEXT,
            inputs={},
            settings={},
        )
        with pytest.raises(ValueError, match="Invalid step id"):
            build_workflow_definition([fake_step], executor_url=EXECUTOR_URL)

    def test_reserved_user_input_name_raises_value_error(self):
        user_in = _user_input_step("user_in")
        step_a = _text_step(
            "step_a",
            prompt=StepOutputReference(step="user_in", output="run_id"),
        )
        with pytest.raises(
            ValueError, match="User input names are reserved: run_id"
        ):
            build_workflow_definition(
                [user_in, step_a], executor_url=EXECUTOR_URL
            )

    def test_step_id_clashing_with_generated_step_name_raises(self):
        with pytest.raises(
            ValueError,
            match="Step ids clash with generated workflow step names: init",
        ):
            build_workflow_definition(
                [_text_step("init")], executor_url=EXECUTOR_URL
            )

    @pytest.mark.parametrize("bad_timeout", [0, -5, 1801, True, "300"])
    def test_invalid_step_timeout_raises_value_error(self, bad_timeout):
        with pytest.raises(ValueError, match="Invalid step timeout"):
            build_workflow_definition(
                [_text_step("step_a")],
                executor_url=EXECUTOR_URL,
                step_timeout_seconds=bad_timeout,  # type: ignore[arg-type]
            )

    def test_oversized_yaml_raises_value_error(self):
        big_prompt = "x" * (MAX_SOURCE_BYTES + 1024)
        with pytest.raises(ValueError, match="too large to deploy"):
            build_workflow_yaml(
                [_text_step("step_a", prompt=big_prompt)],
                executor_url=EXECUTOR_URL,
            )
