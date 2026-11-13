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

"""PR Intent Alignment, Completeness & Scope-Creep Guard agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_SINGLE_FAST

AGENT = StepSpec(
    step_id="pr_intent_synthesizer",
    title="PR Intent Alignment & Scope Guard",
    tier=TIER_SINGLE_FAST,
    blocking=False,
    description=(
        "PR objective completeness, GEMINI.md scope-creep guard, and "
        "cross-agent synthesis."
    ),
    rubric="""Verify **PR Intent Alignment, Completeness & Scope-Creep Guard** only:
- Compare PR Title/Description against the actual changed files: flag incomplete feature wiring (e.g., added in DTO/backend but forgotten in UI/router, or leftover debug stubs/`TODO`s blocking the stated goal).
- Enforce `GEMINI.md` Scope Discipline: flag accidental unrelated edits, clobbered config defaults, or out-of-scope refactors in functions unrelated to the PR objective.
- Do NOT repeat code-level bugs already listed in the specialist findings digest below.""",
)
