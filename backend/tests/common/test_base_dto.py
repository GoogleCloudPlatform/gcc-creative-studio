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
"""Tests for the shared base DTO enums."""

from enum import Enum

import pytest

from src.common.base_dto import (
    GenerationModelEnum,
    normalize_retired_text_model,
)


def test_generation_model_enum_resolves_argon_model_id():
    """The Argon model ID string maps to its enum member."""
    model = GenerationModelEnum("gemini-4-argon")
    assert model is GenerationModelEnum.GEMINI_4_ARGON


def test_generation_model_enum_resolves_hydrogen_model_id():
    """The Hydrogen model ID string maps to its enum member."""
    model = GenerationModelEnum("gemini-4-hydrogen")
    assert model is GenerationModelEnum.GEMINI_4_HYDROGEN


@pytest.mark.parametrize(
    ("raw_model", "expected"),
    [
        ("gemini-2.5-pro", "gemini-4-argon"),
        (GenerationModelEnum.GEMINI_2_5_PRO, "gemini-4-argon"),
        ("gemini-2.5-flash", "gemini-4-hydrogen"),
        (GenerationModelEnum.GEMINI_2_5_FLASH, "gemini-4-hydrogen"),
        ("gemini-4-argon", "gemini-4-argon"),
        ("gemini-4-hydrogen", "gemini-4-hydrogen"),
        ("gemini-3.8-flash", "gemini-3.8-flash"),
        (GenerationModelEnum.GEMINI_3_5_FLASH, "gemini-3.5-flash"),
        ("gemini-2.5-flash-image", "gemini-2.5-flash-image"),
        ("gemini-2.5-flash-tts", "gemini-2.5-flash-tts"),
    ],
)
def test_normalize_retired_text_model_returns_plain_str(raw_model, expected):
    """Retired Gemini 2.5 text IDs map to Gemini 4 and all outputs are plain strs."""
    normalized = normalize_retired_text_model(raw_model)
    assert normalized == expected
    assert isinstance(normalized, str)
    assert not isinstance(normalized, Enum)
