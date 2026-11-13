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

"""System Architecture & Repository Hard Rules verification agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_FAST

AGENT = StepSpec(
    step_id="architecture",
    title="Architecture & Repo Hard Rules",
    tier=TIER_DUAL_FAST,
    blocking=True,
    description=(
        "Hexagonal feature boundaries, Angular Service/Signal rules, and "
        "GEMINI.md operational & infrastructure invariants."
    ),
    rubric="""Verify **System Architecture & Repository Hard Rules (`GEMINI.md`)** only:
- Modular, feature-driven (Hexagonal) cohesion: clean boundaries across domains; controllers delegate business logic to services and DB access to repositories.
- Angular rules: API calls strictly inside Services (never `HttpClient`/`fetch` in components), Signals-first state, no `console.log`/`info`/`debug` in app code.
- Repository operational invariants listed in `<REPO_RULES>` (no hardcoded GCP regions, no `assert_*` methods on mockable classes, no Cloud Run env-var restart drift, Workbench layout/URL single-writer contracts).""",
)
