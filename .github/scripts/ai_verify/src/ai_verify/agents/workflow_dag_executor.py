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

"""Workflow Engine, DAG Execution & Encrypted Token Safety agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="workflow_dag_executor",
    title="Workflow Engine, DAG & Token Safety",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "DAG loop fan-out bounds, retry/timeout idempotency, encrypted "
        "workflow token isolation, and WorkflowFolderTreeStore scoping."
    ),
    rubric="""Verify **Workflow Engine, DAG Execution & Encrypted Token Safety** only:
- DAG execution & Loop fan-out bounds: preventing unbounded Veo/Imagen loop amplification, enforcing retry/timeout ceilings (`WORKFLOW_MAX_STEP_ATTEMPTS`, `WORKFLOW_MAX_RUN_EXECUTIONS`), releasing running slots on `CancelledError`/crash, and mapping deterministic `422` errors (`OUTPUT_FOLDER_NOT_FOUND`) to non-retryable `INVALID_INPUT` / `NEEDS_ATTENTION`.
- Credential isolation: `WORKFLOW_TOKEN_ENCRYPTION_KEY`-encrypted user tokens never logged, persisted in plaintext, or leaked in step DTOs/errors.
- Editor scoping: `WorkflowFolderTreeStore` stays component-provided in `WorkflowEditorComponent` (never `providedIn: 'root'`, errors never cached) and preview re-signing never dirties reactive forms.""",
)
