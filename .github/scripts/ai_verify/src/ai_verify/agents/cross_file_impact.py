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

"""Cross-File Call Graph & Untouched-Caller Compatibility agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="cross_file_impact",
    title="Cross-File Call Graph & Breaking Changes",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "Untouched caller/consumer compatibility across changed signatures, "
        "DTOs, DI bindings, and overflow file summaries."
    ),
    rubric="""Verify **Cross-File Call Graph & Untouched-Caller Compatibility** using `<CROSS_FILE_CALLERS>` and `<OVERFLOW_FILE_SUMMARIES>`:
- Check every untouched caller, route consumer, DI binding, and test mock referencing modified functions, methods, classes, Pydantic DTOs, or TypeScript interfaces for broken signatures, renamed fields, changed return/exception contracts, or stale default arguments.
- Inspect `<OVERFLOW_FILE_SUMMARIES>` (when present on large PRs) to flag any cross-module contract breaks involving truncated files.""",
)
