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

"""Base specification and model tier constants shared by all verification agents."""

from dataclasses import dataclass

TIER_DUAL_DEEP = "dual_deep"
TIER_DUAL_FAST = "dual_fast"
TIER_SINGLE_FAST = "single_fast"


@dataclass(frozen=True)
class StepSpec:
    """Self-contained configuration and prompt rubric for one verification agent."""

    step_id: str
    title: str
    tier: str
    blocking: bool
    description: str
    rubric: str = ""
