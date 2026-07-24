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

"""create_projects_table

Revision ID: fa5148bc6f42
Revises: 959c44325b16
Create Date: 2026-07-03 19:00:24.398216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fa5148bc6f42"
down_revision: Union[str, None] = "959c44325b16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Clear existing data in dependent tables to satisfy NOT NULL project_id constraints
    op.execute("DELETE FROM audio_clips")
    op.execute("DELETE FROM video_clips")
    op.execute("DELETE FROM timelines")
    op.execute("DELETE FROM scenes")
    op.execute("DELETE FROM storyboards")

    # 2. Create projects table
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("thumbnail_media_item_id", sa.Integer(), nullable=True),
        sa.Column("thumbnail_source_asset_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_projects_owner_id"
        ),
        sa.ForeignKeyConstraint(
            ["thumbnail_media_item_id"],
            ["media_items.id"],
            name="fk_projects_thumbnail_media_item_id",
        ),
        sa.ForeignKeyConstraint(
            ["thumbnail_source_asset_id"],
            ["source_assets.id"],
            name="fk_projects_thumbnail_source_asset_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_projects_workspace_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 3. Add project_id columns as non-nullable directly and make them unique
    op.add_column(
        "storyboards", sa.Column("project_id", sa.Integer(), nullable=False)
    )
    op.create_unique_constraint(
        "uq_storyboards_project_id", "storyboards", ["project_id"]
    )
    op.create_foreign_key(
        "fk_storyboards_project_id",
        "storyboards",
        "projects",
        ["project_id"],
        ["id"],
    )

    op.add_column(
        "timelines", sa.Column("project_id", sa.Integer(), nullable=False)
    )
    op.create_unique_constraint(
        "uq_timelines_project_id", "timelines", ["project_id"]
    )
    op.create_foreign_key(
        "fk_timelines_project_id",
        "timelines",
        "projects",
        ["project_id"],
        ["id"],
    )

    # 4. Drop direct workspace_id relation from storyboards and timelines
    op.drop_constraint(
        "storyboards_workspace_id_fkey", "storyboards", type_="foreignkey"
    )
    op.drop_column("storyboards", "workspace_id")

    op.drop_constraint(
        "timelines_workspace_id_fkey", "timelines", type_="foreignkey"
    )
    op.drop_column("timelines", "workspace_id")

    # 5. Drop session_id from storyboards and create sessions table
    op.drop_column("storyboards", "session_id")
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_sessions_project_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Clear existing data in dependent tables
    op.execute("DELETE FROM audio_clips")
    op.execute("DELETE FROM video_clips")
    op.execute("DELETE FROM timelines")
    op.execute("DELETE FROM scenes")
    op.execute("DELETE FROM storyboards")

    if "sessions" in tables:
        op.execute("DELETE FROM sessions")
        # 2. Drop sessions table
        op.drop_table("sessions")

    # 3. Re-add session_id column to storyboards if it doesn't exist
    columns_storyboards = [
        c["name"] for c in inspector.get_columns("storyboards")
    ]
    if "session_id" not in columns_storyboards:
        op.add_column(
            "storyboards", sa.Column("session_id", sa.String(), nullable=True)
        )

    # 4. Re-add workspace_id columns as non-nullable if they don't exist
    columns_timelines = [c["name"] for c in inspector.get_columns("timelines")]
    if "workspace_id" not in columns_storyboards:
        op.add_column(
            "storyboards",
            sa.Column(
                "workspace_id",
                sa.Integer(),
                sa.ForeignKey(
                    "workspaces.id", name="storyboards_workspace_id_fkey"
                ),
                nullable=False,
            ),
        )
    if "workspace_id" not in columns_timelines:
        op.add_column(
            "timelines",
            sa.Column(
                "workspace_id",
                sa.Integer(),
                sa.ForeignKey(
                    "workspaces.id", name="timelines_workspace_id_fkey"
                ),
                nullable=False,
            ),
        )

    # 5. Drop project_id column, FK and unique constraint from timelines
    if "timelines" in tables:
        constraints_timelines = inspector.get_unique_constraints("timelines")
        if any(
            c["name"] == "uq_timelines_project_id"
            for c in constraints_timelines
        ):
            op.drop_constraint(
                "uq_timelines_project_id", "timelines", type_="unique"
            )

        fks_timelines = inspector.get_foreign_keys("timelines")
        if any(fk["name"] == "fk_timelines_project_id" for fk in fks_timelines):
            op.drop_constraint(
                "fk_timelines_project_id", "timelines", type_="foreignkey"
            )
        if "project_id" in columns_timelines:
            op.drop_column("timelines", "project_id")

    # 6. Drop project_id column, FK and unique constraint from storyboards
    if "storyboards" in tables:
        constraints_storyboards = inspector.get_unique_constraints(
            "storyboards"
        )
        if any(
            c["name"] == "uq_storyboards_project_id"
            for c in constraints_storyboards
        ):
            op.drop_constraint(
                "uq_storyboards_project_id", "storyboards", type_="unique"
            )

        fks_storyboards = inspector.get_foreign_keys("storyboards")
        if any(
            fk["name"] == "fk_storyboards_project_id" for fk in fks_storyboards
        ):
            op.drop_constraint(
                "fk_storyboards_project_id", "storyboards", type_="foreignkey"
            )
        if "project_id" in columns_storyboards:
            op.drop_column("storyboards", "project_id")

    # 7. Drop projects table
    if "projects" in tables:
        op.drop_table("projects")
