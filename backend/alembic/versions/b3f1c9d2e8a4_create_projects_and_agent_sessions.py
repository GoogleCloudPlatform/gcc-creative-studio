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

"""create_projects_and_agent_sessions

Turns ``Project`` into a real container for Workbench work. A workspace holds
owner-scoped projects, and a project groups its owner's agent chats (the new
``agent_sessions`` registry), storyboards and timelines.

The backfill is non-destructive:

- Every (workspace, user) that already owns storyboards gets one "Default
  project", and all of that user's records in the workspace are attached to
  it.
- A timeline follows its storyboard, or the storyboard of its session.
- Legacy orphans are the timelines still unattributed after that: no
  storyboard, and no session that owns one. They go to the workspace
  owner's Default project when ``timelines.workspace_id`` names a real
  workspace, even when they carry a ``user_id`` (stamped with the owner only
  when it is NULL). Access follows the project, so such a timeline's creator
  loses it to the workspace owner (the admin, in the public workspace): an
  accepted trade-off, since the pre-projects UI never sent ``user_id`` for
  manual timelines. Otherwise they keep ``project_id = NULL`` and become
  admin-only.

Also adds ``ON DELETE CASCADE`` to the storyboard -> scenes,
storyboard -> timeline and timeline -> clips foreign keys. Without it, a bulk
``DELETE`` of a project or storyboard violates those foreign keys.

Revision ID: b3f1c9d2e8a4
Revises: b7e2d9c4f1a3
Create Date: 2026-10-15 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3f1c9d2e8a4"
down_revision: Union[str, None] = "b7e2d9c4f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PROJECT_NAME = "Default project"

# (table, column, referenced table) of the foreign keys that gain
# ON DELETE CASCADE.
_CASCADE_FKS = (
    ("scenes", "storyboard_id", "storyboards"),
    ("timelines", "storyboard_id", "storyboards"),
    ("video_clips", "timeline_id", "timelines"),
    ("audio_clips", "timeline_id", "timelines"),
)

# ``timelines.workspace_id`` is a string written by clients. The CASE guards
# the cast against non-numeric or oversized values, because Postgres does not
# short-circuit AND in a join condition.
_TIMELINE_WORKSPACE_ID = (
    "CASE WHEN t.workspace_id ~ '^[0-9]{1,9}$' "
    "THEN CAST(t.workspace_id AS INTEGER) END"
)


def _replace_fk(
    table: str, column: str, ref_table: str, ondelete: str | None
) -> None:
    """Recreates the single-column FK on ``table.column`` with ``ondelete``.

    The existing names are looked up rather than hard-coded, because
    environments built through different migration paths may have named
    them differently.
    """
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk.get("name") and fk.get("constrained_columns") == [column]:
            op.drop_constraint(fk["name"], table, type_="foreignkey")
    op.create_foreign_key(
        f"{table}_{column}_fkey",
        table,
        ref_table,
        [column],
        ["id"],
        ondelete=ondelete,
    )


def _backfill() -> None:
    bind = op.get_bind()
    params = {"name": DEFAULT_PROJECT_NAME}

    # 1. One Default project per (workspace, user) that owns storyboards.
    bind.execute(
        sa.text(
            """
            INSERT INTO projects (workspace_id, owner_id, name, is_default)
            SELECT DISTINCT workspace_id, user_id, :name, true
              FROM storyboards
            ON CONFLICT DO NOTHING
            """
        ),
        params,
    )
    bind.execute(
        sa.text(
            """
            UPDATE storyboards s
               SET project_id = p.id
              FROM projects p
             WHERE p.is_default
               AND p.workspace_id = s.workspace_id
               AND p.owner_id = s.user_id
            """
        )
    )

    # 2. Timelines follow their storyboard, and the owner is stamped from it.
    bind.execute(
        sa.text(
            """
            UPDATE timelines t
               SET project_id = s.project_id,
                   user_id = COALESCE(t.user_id, CAST(s.user_id AS VARCHAR))
              FROM storyboards s
             WHERE t.storyboard_id = s.id
            """
        )
    )

    # 3. Timelines without a storyboard, whose session owns one.
    bind.execute(
        sa.text(
            """
            UPDATE timelines t
               SET project_id = x.project_id,
                   user_id = COALESCE(t.user_id, CAST(x.user_id AS VARCHAR))
              FROM (SELECT DISTINCT ON (session_id) session_id, project_id,
                           user_id
                      FROM storyboards
                     WHERE session_id IS NOT NULL AND session_id <> ''
                     ORDER BY session_id, id DESC) x
             WHERE t.project_id IS NULL
               AND t.session_id = x.session_id
            """
        )
    )

    # 4. Orphans go to the workspace owner's Default project, whatever their
    #    user_id (see the module docstring).
    bind.execute(
        sa.text(
            f"""
            INSERT INTO projects (workspace_id, owner_id, name, is_default)
            SELECT DISTINCT w.id, w.owner_id, :name, true
              FROM timelines t
              JOIN workspaces w ON w.id = {_TIMELINE_WORKSPACE_ID}
             WHERE t.project_id IS NULL
            ON CONFLICT DO NOTHING
            """
        ),
        params,
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE timelines t
               SET project_id = p.id,
                   user_id = COALESCE(t.user_id, CAST(w.owner_id AS VARCHAR))
              FROM workspaces w
              JOIN projects p
                ON p.is_default
               AND p.workspace_id = w.id
               AND p.owner_id = w.owner_id
             WHERE t.project_id IS NULL
               AND w.id = {_TIMELINE_WORKSPACE_ID}
            """
        )
    )

    # 5. Register the chats visible from storyboards. Agent Engine holds the
    #    others; the backend adopts them the first time it lists sessions.
    bind.execute(
        sa.text(
            """
            INSERT INTO agent_sessions
                   (session_id, project_id, user_id, workspace_id, app_name)
            SELECT DISTINCT ON (session_id) session_id, project_id, user_id,
                   workspace_id, 'ads_x'
              FROM storyboards
             WHERE session_id IS NOT NULL AND session_id <> ''
             ORDER BY session_id, id DESC
            ON CONFLICT (session_id) DO NOTHING
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_projects_workspace_owner",
        "projects",
        ["workspace_id", "owner_id"],
    )
    op.create_index(
        "uq_projects_default_per_owner",
        "projects",
        ["workspace_id", "owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column(
            "app_name", sa.String(), server_default="ads_x", nullable=False
        ),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.String(length=1000), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_agent_sessions_session_id"),
    )
    op.create_index(
        "ix_agent_sessions_project_id", "agent_sessions", ["project_id"]
    )
    op.create_index(
        "ix_agent_sessions_user_workspace",
        "agent_sessions",
        ["user_id", "workspace_id"],
    )

    op.add_column(
        "storyboards", sa.Column("project_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "storyboards_project_id_fkey",
        "storyboards",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_storyboards_project_id", "storyboards", ["project_id"])

    op.add_column(
        "timelines", sa.Column("project_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "timelines_project_id_fkey",
        "timelines",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_timelines_project_id", "timelines", ["project_id"])

    _backfill()

    # Every storyboard has NOT NULL workspace_id and user_id, so step 1 of
    # the backfill gave each one a project.
    op.alter_column("storyboards", "project_id", nullable=False)

    for table, column, ref_table in _CASCADE_FKS:
        _replace_fk(table, column, ref_table, "CASCADE")


def downgrade() -> None:
    for table, column, ref_table in _CASCADE_FKS:
        _replace_fk(table, column, ref_table, None)

    op.drop_index("ix_timelines_project_id", table_name="timelines")
    op.drop_constraint(
        "timelines_project_id_fkey", "timelines", type_="foreignkey"
    )
    op.drop_column("timelines", "project_id")

    op.drop_index("ix_storyboards_project_id", table_name="storyboards")
    op.drop_constraint(
        "storyboards_project_id_fkey", "storyboards", type_="foreignkey"
    )
    op.drop_column("storyboards", "project_id")

    op.drop_index(
        "ix_agent_sessions_user_workspace", table_name="agent_sessions"
    )
    op.drop_index("ix_agent_sessions_project_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")

    op.drop_index("uq_projects_default_per_owner", table_name="projects")
    op.drop_index("ix_projects_workspace_owner", table_name="projects")
    op.drop_table("projects")
