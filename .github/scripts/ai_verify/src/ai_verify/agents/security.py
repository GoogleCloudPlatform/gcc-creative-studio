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

"""Security & Authorization Boundaries verification agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="security",
    title="Security & AuthZ",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "Auth bypasses, workspace/folder multi-tenant IDOR, injection "
        "risks, secrets exposure, and IAM over-privilege."
    ),
    rubric="""Verify **Security & Authorization Boundaries** only:
- Authentication bypasses (`auth_guard`, `Depends(get_current_user)`, `isLocal` leakage to non-local paths).
- Multi-tenant / workspace / folder IDOR (`workspace_id` scoping, missing `ensure_can_*` owner/subtree checks on destructive folder or media mutations).
- Command injection, SSRF, path traversal, SQL injection, unsafe deserialization, or shell quoting bugs in `bootstrap.sh`/ffmpeg/subprocess calls.
- Prompt injection or privilege escalation in Izumi agent / workflow execution paths (`X-User-Authorization`, `is_agent_request`).
- Secrets exposure or over-privileged IAM / GitHub Actions permissions.""",
)
