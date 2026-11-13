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

"""Infrastructure, Terraform, Cloud Build & bootstrap.sh Blast-Radius agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="infra_migration",
    title="Infra, Terraform & Bootstrap Blast Radius",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "Terraform force-recreate/ignore_changes safety, V1->V2 Cloud SQL "
        "migration traps, Cloud Run revision/secret drift, and bootstrap.sh."
    ),
    rubric="""Verify **Infrastructure, Terraform, Cloud Build & `bootstrap.sh` Blast Radius** only:
- Terraform destructive `force_new` replacements on stateful Cloud SQL/GCS/Cloud Build resources, or removing `lifecycle.ignore_changes` on Cloud Run container image (breaks VPC deadlock dummy-image flow).
- `bootstrap.sh` traps: `write_state` not setting shell variables in-memory, silent detection branches, `gcloud` stderr captured in `$(...)` breaking SA impersonation, or Secret Manager writes missing a forced same-image Cloud Run refresh.
- V1 (`creative-studio-db-<hex>`, `cstudio-be`) vs V2 (`cs-<env>-db-<hex>`, `cs-<env>-backend`) dual handling, Cloud Run CPU/RAM ratios (8Gi requires >=2 vCPU), and `cloudbuild-deploy.yaml` `--configuration=production` parity.""",
)
