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

"""Runtime, Build Compilation & Diff-Coverage Readiness agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_SINGLE_FAST

AGENT = StepSpec(
    step_id="runtime_ci_triage",
    title="Runtime, Build & Diff-Coverage Readiness",
    tier=TIER_SINGLE_FAST,
    blocking=True,
    description=(
        "Import/AOT build integrity, migration round-trip readiness, and "
        "diff-coverage / JUnit telemetry verification."
    ),
    rubric="""Verify **Runtime, Build Compilation & Diff-Coverage Readiness** using `<CI_RUNTIME_TELEMETRY>` and diffs:
- Circular imports, unresolved symbols, strict TypeScript / Angular AOT template compilation hazards, or pytest mock/fixture signature mismatches that will fail runtime execution.
- Alembic `upgrade head` -> `downgrade -1` -> `upgrade head` round-trip executability.
- When `<CI_RUNTIME_TELEMETRY>` is present, flag PR diff-coverage drops (<80% on changed security/business lines), failed tests (excluding documented pre-existing Karma baseline flakes), and build errors.""",
)
