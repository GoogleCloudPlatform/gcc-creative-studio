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

"""create workflow templates table

Revision ID: e5b7a1c93f20
Revises: 7a8b9c0d1e2f
Create Date: 2026-09-08 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b7a1c93f20"
down_revision: str | None = "7a8b9c0d1e2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workflow_templates_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_templates")),
        sa.UniqueConstraint(
            "user_id", "name", name="uq_user_workflow_template_name"
        ),
    )
    op.create_index(
        op.f("ix_workflow_templates_name"),
        "workflow_templates",
        ["name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_templates_user_id"),
        "workflow_templates",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_templates_user_id"),
        table_name="workflow_templates",
    )
    op.drop_index(
        op.f("ix_workflow_templates_name"),
        table_name="workflow_templates",
    )
    op.drop_table("workflow_templates")
