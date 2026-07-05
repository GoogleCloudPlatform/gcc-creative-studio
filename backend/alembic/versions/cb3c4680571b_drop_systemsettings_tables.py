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

"""Drop SystemSettings tables

Revision ID: cb3c4680571b
Revises: 2af84fd47706
Create Date: 2026-07-03 00:07:39.757335

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cb3c4680571b"
down_revision: Union[str, None] = "c7691a33f1fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("system_settings")


def downgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
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
    )
    # Seed default values that existed prior to this migration
    op.execute(
        "INSERT INTO system_settings (id, value, description) VALUES "
        "('show_gemini_omni', 'false', 'Enable Gemini Omni model visibility')"
    )
    op.execute(
        "INSERT INTO system_settings (id, value, description) VALUES "
        "('gemini_omni_model_name', '', 'Custom model name for Gemini Omni')"
    )
