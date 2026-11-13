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

"""Database Schema, Alembic Migrations & SQL View Safety agent."""

# pylint: disable=line-too-long

from ai_verify.agents._base import StepSpec, TIER_DUAL_DEEP

AGENT = StepSpec(
    step_id="db_schema_migrations",
    title="Database, Alembic & SQL View Safety",
    tier=TIER_DUAL_DEEP,
    blocking=True,
    description=(
        "Zero-downtime Alembic migrations, concurrent indexes, downgrade "
        "reversibility, ORM-to-migration sync, and unified_gallery_view."
    ),
    rubric="""Verify **Database Schema, Alembic Migrations & SQL View Safety** only:
- Zero-downtime expand/contract migrations: `op.create_index` needing `postgresql_concurrently=True` on live tables, `ALTER TYPE ... ADD VALUE` transaction locks, non-reversible `downgrade()`, or multiple Alembic heads.
- ORM-to-migration parity: SQLAlchemy column/FK/constraint edits missing an Alembic revision, or breaking `unified_gallery_view` / `backend/README.md` ER diagram consistency.
- Async SQLAlchemy traps: implicit lazy relationship loads (`MissingGreenlet`), missing `deleted_at IS NULL` or `workspace_id` filters, or unique-index race handlers without `begin_nested()` savepoints.""",
)
