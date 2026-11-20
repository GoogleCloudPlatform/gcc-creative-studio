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

"""Code Quality, Cloud Run Memory & Performance verification agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_FAST

AGENT = StepSpec(
    step_id="quality_perf",
    title="Code Quality & Cloud Run Perf",
    tier=TIER_DUAL_FAST,
    blocking=False,
    description=(
        "N+1 DB queries, loop-await bottlenecks, unstreamed media memory "
        "spikes on Cloud Run, and resource leaks."
    ),
    rubric="""Verify **Code Quality, Cloud Run Memory & Performance** only:
- N+1 database queries or sequential `await` calls inside loops that should be batched.
- Buffering large video/audio/image payloads in memory instead of streaming/tempfiles (Cloud Run OOM risk).
- Unbounded retries/polls, unclosed file/HTTP handles, or Angular template getters / `*ngFor` without `trackBy` causing repeated re-renders.""",
)
