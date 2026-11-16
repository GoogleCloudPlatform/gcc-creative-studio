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

"""merge personal workspaces and workbench projects heads

Revision ID: a9e4c2f18b07
Revises: c8f3a1b2d4e5, d7e3b1a9c5f2
Create Date: 2026-11-24 17:30:00.000000

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "a9e4c2f18b07"
down_revision: Union[str, Sequence[str], None] = (
    "c8f3a1b2d4e5",
    "d7e3b1a9c5f2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
