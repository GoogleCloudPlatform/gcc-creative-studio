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

"""Join upstream's system settings removal with the Entra role sync migrations.

Upstream's settings removal and our Entra role sync changes both follow
c7691a33f1fd. This revision makes them one line again so the automatic
upgrade on startup has a single target. It changes nothing in the database.

Revision ID: 5f0c2a7d9b14
Revises: cb3c4680571b, 9e3f2a5b1c8d
"""

from typing import Sequence, Union

revision: str = "5f0c2a7d9b14"
down_revision: Union[str, Sequence[str], None] = ("cb3c4680571b", "9e3f2a5b1c8d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
