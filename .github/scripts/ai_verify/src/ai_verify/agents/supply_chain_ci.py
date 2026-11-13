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

"""Supply Chain, Lockfiles, Containers & GitHub Actions Hardening agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_FAST

AGENT = StepSpec(
    step_id="supply_chain_ci",
    title="Supply Chain, Lockfiles, Containers & CI",
    tier=TIER_DUAL_FAST,
    blocking=True,
    description=(
        "GitHub Actions SHA pinning & injection safety, lockfile/manifest "
        "sync, license compatibility, and Dockerfile hardening."
    ),
    rubric="""Verify **Supply Chain, Lockfiles, Containers & GitHub Actions Hardening** only:
- GitHub Actions security (`zizmor` rules): third-party `uses:` pinned to immutable 40-char commit SHAs, zero untrusted fork code execution in `workflow_run`/`pull_request_target`, `${{ github.event.* }}` passed via `env:` instead of shell interpolation, and least-privilege `permissions:`.
- Dependency & license hygiene (`<LOCKFILE_DELTAS>` & manifests): manifest changes (`pyproject.toml`, `package.json`) paired with lockfile updates, no copyleft/GPL packages incompatible with Apache-2.0, and `google-genai` used instead of legacy `vertexai` SDK.
- Container & build hygiene: non-root `USER`, `.dockerignore`/`.gcloudignore` secret exclusion, and no dev bundles/sourceMaps in production builds.""",
)
