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

"""add_gemini_omni_model_name_setting

Revision ID: c7691a33f1fd
Revises: 5dac63588faa
Create Date: 2026-06-05 18:25:06.744516

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7691a33f1fd"
down_revision: Union[str, None] = "5dac63588faa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Seed default gemini_omni_model_name value
    op.execute(
        "INSERT INTO system_settings (id, value, description) VALUES "
        "('gemini_omni_model_name', '', 'Custom model name for Gemini Omni')"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM system_settings WHERE id = 'gemini_omni_model_name'"
    )
