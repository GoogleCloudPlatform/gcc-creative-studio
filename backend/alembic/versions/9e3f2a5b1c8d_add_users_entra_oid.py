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

"""add users.entra_oid column and unique index

Revision ID: 9e3f2a5b1c8d
Revises: 8d2e1f4a9b7c
Create Date: 2026-09-30 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e3f2a5b1c8d"
down_revision: str | None = "8d2e1f4a9b7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("entra_oid", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_users_entra_oid"), "users", ["entra_oid"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_entra_oid"), table_name="users")
    op.drop_column("users", "entra_oid")
