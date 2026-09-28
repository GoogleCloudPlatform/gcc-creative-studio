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

"""workflow_runs queue and checkpoint

Adds the queue / checkpoint columns to ``workflow_runs`` (all nullable)
and the ``workflow_user_sessions`` token-store table, then makes the
existing rows fit the single run model:

* ``status`` ``failed`` / ``scheduled`` -> ``needs_attention`` (there is no
  ``FAILED`` run status any more; ``scheduled`` was never written).
* ``execution_ids`` is backfilled with ``[{"execution_id": id,
  "started_at": started_at}]`` where it is NULL (legacy row ids ARE GCP
  execution ids, so the reconciler can sync them).

All other new columns stay NULL on existing rows; code treats NULL as
``{}`` / ``0`` / "changed". ``attempt_count`` and ``session_wait_seconds``
only get their ``DEFAULT 0`` for rows inserted after this revision.

The downgrade is LOSSY: ``needs_attention`` / ``step_failed`` -> ``failed``
(the origin of a ``needs_attention`` row is not preserved) and ``queued`` ->
``canceled``; all new columns, indexes and tables are dropped.

Revision ID: 31a0c8217a51
Revises: 8fc57c521452
Create Date: 2026-09-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31a0c8217a51"
down_revision: str | None = "8fc57c521452"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNS = "workflow_runs"
_SESSIONS = "workflow_user_sessions"


def _run_columns() -> list[sa.Column]:
    """New nullable ``workflow_runs`` columns (spec §5.1), in order."""
    return [
        sa.Column(
            "input_args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("definition_hash", sa.String(length=64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queue_reason", sa.String(), nullable=True),
        sa.Column(
            "waiting_for_session_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("session_wait_seconds", sa.Integer(), nullable=True),
        sa.Column("current_step_id", sa.String(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.Column(
            "execution_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "step_states",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("canceled_by_user", sa.Boolean(), nullable=True),
    ]


# (index name, columns) for the new workflow_runs indexes (spec §5.1).
_RUN_INDEXES: list[tuple[str, list]] = [
    ("ix_workflow_runs_status_next_retry_at", ["status", "next_retry_at"]),
    ("ix_workflow_runs_user_id_status", ["user_id", "status"]),
    (
        "ix_workflow_runs_workflow_id_queued_at",
        ["workflow_id", sa.text("queued_at DESC")],
    ),
    ("ix_workflow_runs_workflow_id_status", ["workflow_id", "status"]),
]

# Counters default to 0 for new rows only (existing rows keep NULL).
_ZERO_DEFAULT_COLUMNS = ("session_wait_seconds", "attempt_count")

# Data statements (spec §5.5). Module-level so the migration test can
# re-apply the backfill and check that it only fills NULL rows.
MIGRATE_STATUS_SQL = (
    "UPDATE workflow_runs SET status = 'needs_attention' "
    "WHERE status IN ('failed', 'scheduled')"
)
BACKFILL_EXECUTION_IDS_SQL = (
    "UPDATE workflow_runs SET execution_ids = jsonb_build_array("
    "jsonb_build_object('execution_id', id, 'started_at', started_at)) "
    "WHERE execution_ids IS NULL"
)


def upgrade() -> None:
    # --- Schema: workflow_runs ---
    for column in _run_columns():
        op.add_column(_RUNS, column)
    # Added without a default first so existing rows stay NULL, then the
    # default is set for rows inserted from now on.
    for column_name in _ZERO_DEFAULT_COLUMNS:
        op.alter_column(_RUNS, column_name, server_default=sa.text("0"))
    for index_name, columns in _RUN_INDEXES:
        op.create_index(index_name, _RUNS, columns, unique=False)

    # --- Schema: token store (one row per user, latest token only) ---
    op.create_table(
        _SESSIONS,
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=True),
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_dispatched_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workflow_user_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", name=op.f("pk_workflow_user_sessions")
        ),
    )

    # --- Data: existing rows fit the single run model (spec §5.5) ---
    op.execute(MIGRATE_STATUS_SQL)
    op.execute(BACKFILL_EXECUTION_IDS_SQL)


def downgrade() -> None:
    # --- Data (LOSSY, see module docstring) ---
    op.execute(
        "UPDATE workflow_runs SET status = 'failed' "
        "WHERE status IN ('needs_attention', 'step_failed')"
    )
    op.execute(
        "UPDATE workflow_runs SET status = 'canceled' WHERE status = 'queued'"
    )

    # --- Schema ---
    op.drop_table(_SESSIONS)
    for index_name, _ in reversed(_RUN_INDEXES):
        op.drop_index(index_name, table_name=_RUNS)
    for column in reversed(_run_columns()):
        op.drop_column(_RUNS, column.name)
