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

"""API Contract Compatibility & Documentation Drift verification agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_SINGLE_FAST

AGENT = StepSpec(
    step_id="api_docs",
    title="API Contract & Docs Drift",
    tier=TIER_SINGLE_FAST,
    blocking=False,
    description=(
        "Backend DTO/OpenAPI vs Frontend type mismatches, undocumented "
        "env/Terraform variables, and Mermaid/docs accuracy."
    ),
    rubric="""Verify **API Contract Compatibility & Documentation Drift** only:
- Mismatches between Backend FastAPI routes / Pydantic DTO fields (camelCase aliases vs snake_case) and Frontend TypeScript interfaces/services.
- Breaking changes to existing REST request/response shapes or workflow step schemas.
- New environment variables, secrets, or Terraform variables missing from `DEPLOYMENT.md` or `.env.example`, duplicated procedure prose across READMEs, or invalid Mermaid syntax in Markdown.""",
)
