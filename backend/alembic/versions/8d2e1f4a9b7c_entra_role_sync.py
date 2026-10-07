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

"""entra_role_sync: add users.roles_checked_at, lowercase emails

Revision ID: 8d2e1f4a9b7c
Revises: c7691a33f1fd
Create Date: 2026-09-25 15:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d2e1f4a9b7c"
down_revision: str | None = "c7691a33f1fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "roles_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    # Emails are now stored lowercase so lookups can use the existing btree
    # index on users.email. Rows whose lowercase form collides with another
    # row are left untouched (they need manual de-duplication).
    op.execute(
        """
        UPDATE users AS u
        SET email = lower(u.email)
        WHERE u.email <> lower(u.email)
          AND (
            SELECT count(*) FROM users AS d
            WHERE lower(d.email) = lower(u.email)
          ) = 1
        """
    )


def downgrade() -> None:
    # Email lowercasing is not reversible.
    op.drop_column("users", "roles_checked_at")
