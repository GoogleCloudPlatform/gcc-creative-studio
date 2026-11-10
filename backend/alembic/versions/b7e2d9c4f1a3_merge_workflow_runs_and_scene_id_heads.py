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

"""merge workflow runs queue and scene_id heads

Both branches fork from ``e5f6a7b8c9d0`` and touch unrelated tables
(``workflow_runs`` vs ``scenes``), so this merge is a no-op that only
reunifies the revision graph into a single head.

Revision ID: b7e2d9c4f1a3
Revises: 31a0c8217a51, a1c2e3f4b5d6
Create Date: 2026-10-14 14:55:00.000000

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "b7e2d9c4f1a3"
down_revision: Union[str, None] = ("31a0c8217a51", "a1c2e3f4b5d6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
