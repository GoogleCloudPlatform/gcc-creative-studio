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

"""Registry of all 15 explicit PR verification agents."""

from ai_verify.agents._base import (
    StepSpec,
    TIER_DUAL_DEEP,
    TIER_DUAL_FAST,
    TIER_SINGLE_FAST,
)
from ai_verify.agents.agent_media_pipeline import AGENT as AGENT_MEDIA_PIPELINE
from ai_verify.agents.api_docs import AGENT as API_DOCS
from ai_verify.agents.architecture import AGENT as ARCHITECTURE
from ai_verify.agents.correctness import AGENT as CORRECTNESS
from ai_verify.agents.cross_file_impact import AGENT as CROSS_FILE_IMPACT
from ai_verify.agents.db_schema_migrations import AGENT as DB_SCHEMA_MIGRATIONS
from ai_verify.agents.frontend_ux_a11y import AGENT as FRONTEND_UX_A11Y
from ai_verify.agents.infra_migration import AGENT as INFRA_MIGRATION
from ai_verify.agents.pr_intent_synthesizer import (
    AGENT as PR_INTENT_SYNTHESIZER,
)
from ai_verify.agents.quality_perf import AGENT as QUALITY_PERF
from ai_verify.agents.runtime_ci_triage import AGENT as RUNTIME_CI_TRIAGE
from ai_verify.agents.security import AGENT as SECURITY
from ai_verify.agents.supply_chain_ci import AGENT as SUPPLY_CHAIN_CI
from ai_verify.agents.test_adequacy import AGENT as TEST_ADEQUACY
from ai_verify.agents.workflow_dag_executor import (
    AGENT as WORKFLOW_DAG_EXECUTOR,
)

ALL_AGENTS: tuple[StepSpec, ...] = (
    SECURITY,
    CORRECTNESS,
    ARCHITECTURE,
    INFRA_MIGRATION,
    DB_SCHEMA_MIGRATIONS,
    AGENT_MEDIA_PIPELINE,
    WORKFLOW_DAG_EXECUTOR,
    SUPPLY_CHAIN_CI,
    CROSS_FILE_IMPACT,
    FRONTEND_UX_A11Y,
    TEST_ADEQUACY,
    QUALITY_PERF,
    RUNTIME_CI_TRIAGE,
    API_DOCS,
    PR_INTENT_SYNTHESIZER,
)

__all__ = [
    "ALL_AGENTS",
    "StepSpec",
    "TIER_DUAL_DEEP",
    "TIER_DUAL_FAST",
    "TIER_SINGLE_FAST",
]
