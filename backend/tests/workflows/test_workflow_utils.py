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
"""Tests for Workflow utility functions."""

from src.workflows.workflow_utils import interpolate_prompt_variables


def test_interpolate_prompt_variables_basic():
    prompt = "Create a story about <animal> in <city>."
    variables = {
        "animal": "dog",
        "city": "Paris",
    }
    result = interpolate_prompt_variables(prompt, variables)
    assert result == "Create a story about dog in Paris."


def test_interpolate_prompt_variables_missing_keep_unresolved_true():
    prompt = "Hello <name>, score is <score>, missing is <missing>."
    variables = {
        "name": "Alice",
        "score": 100,
    }
    result = interpolate_prompt_variables(
        prompt, variables, keep_unresolved=True
    )
    assert result == "Hello Alice, score is 100, missing is <missing>."


def test_interpolate_prompt_variables_missing_keep_unresolved_false():
    prompt = "Hello <name>, score is <score>, missing is <missing>."
    variables = {
        "name": "Alice",
        "score": 100,
    }
    result = interpolate_prompt_variables(
        prompt, variables, keep_unresolved=False
    )
    assert result == "Hello Alice, score is 100, missing is ."


def test_interpolate_prompt_variables_dict_values():
    prompt = (
        "Generated: <gen_text> and Text: <text_only> and Empty: <empty_dict>"
    )
    variables = {
        "gen_text": {"generated_text": "sample output"},
        "text_only": {"text": "plain output"},
        "empty_dict": {},
    }
    result = interpolate_prompt_variables(prompt, variables)
    assert (
        result == "Generated: sample output and Text: plain output and Empty: "
    )


def test_interpolate_prompt_variables_none_or_empty():
    assert interpolate_prompt_variables("") == ""
    assert interpolate_prompt_variables(None) == ""
    assert (
        interpolate_prompt_variables("Hello <name>", None, keep_unresolved=True)
        == "Hello <name>"
    )
    assert (
        interpolate_prompt_variables(
            "Hello <name>", None, keep_unresolved=False
        )
        == "Hello "
    )


def test_interpolate_prompt_variables_case_insensitive():
    prompt = "Create a <ANIMAL> wearing a <Style> in <City>."
    variables = {
        "animal": "cat",
        "STYLE": "fedora",
        "city": "Tokyo",
    }
    result = interpolate_prompt_variables(prompt, variables)
    assert result == "Create a cat wearing a fedora in Tokyo."
