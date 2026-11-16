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

from src.common.base_dto import GenerationModelEnum


def test_generation_model_enum_resolves_argon_model_id():
    """The Argon model ID string maps to its enum member."""
    model = GenerationModelEnum("gemini-4-argon")
    assert model is GenerationModelEnum.GEMINI_4_ARGON
