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

"""Functional Correctness, Async & Database Safety verification agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="correctness",
    title="Correctness, Async & DB Safety",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "Logic bugs, FastAPI/SQLAlchemy AsyncSession & transaction safety, "
        "Alembic rolling-deploy compatibility, and Angular Signal races."
    ),
    rubric="""Verify **Functional Correctness, Async & Database Integrity** only:
- Logic errors, unhandled `None`/empty edge cases, off-by-one or type-coercion bugs (e.g., `str` vs `int` IDs).
- FastAPI / SQLAlchemy `AsyncSession` concurrency hazards, uncommitted/leaked transactions, or reading request `ContextVar`s inside background tasks.
- Alembic migration safety under rolling Cloud Run deployments (dropping active columns/tables, non-null columns without `server_default`, index locks).
- Angular Signal / RxJS race conditions, stale closures, infinite `effect()` write loops, or missing cleanup in `ngOnDestroy`.
- Workflow retry, timeout, or idempotency bugs.""",
)
