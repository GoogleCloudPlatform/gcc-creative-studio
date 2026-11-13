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

"""Test Adequacy & Edge-Case Coverage verification agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_FAST

AGENT = StepSpec(
    step_id="test_adequacy",
    title="Test Adequacy & Edge Cases",
    tier=TIER_DUAL_FAST,
    blocking=False,
    description=(
        "Meaningful assertions vs mock tautologies, missing negative/authz "
        "tests, and uncovered critical branches."
    ),
    rubric="""Verify **Test Adequacy & Edge-Case Coverage** using `<TEST_MAPPINGS>` and diffs:
- Flag changed production business logic, security guards, or state machines that have zero corresponding test updates or missing negative/error/authz test cases.
- Detect "coverage theater": heavy mocking where assertions only check mock call counts without verifying actual output, DB state, or error handling.
- Keep severity realistic: use `HIGH` only when critical security/data-integrity paths are untested; use `MEDIUM` for standard missing edge-case tests.""",
)
