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

"""update timeline nle models and drop stale clip columns

Revision ID: c3d4e5f6a7b8
Revises: 9c836db56fb1
Create Date: 2026-06-24 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "9c836db56fb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # timelines
    op.add_column(
        "timelines", sa.Column("workspace_id", sa.String(), nullable=True)
    )
    op.add_column("timelines", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column(
        "timelines", sa.Column("session_id", sa.String(), nullable=True)
    )
    op.add_column(
        "timelines", sa.Column("transition_in_type", sa.String(), nullable=True)
    )
    op.add_column(
        "timelines",
        sa.Column("transition_in_duration", sa.Float(), nullable=True),
    )
    op.add_column(
        "timelines",
        sa.Column("transition_out_type", sa.String(), nullable=True),
    )
    op.add_column(
        "timelines",
        sa.Column("transition_out_duration", sa.Float(), nullable=True),
    )
    op.alter_column("timelines", "storyboard_id", nullable=True)

    # video_clips
    op.add_column(
        "video_clips",
        sa.Column(
            "clip_index", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "video_clips",
        sa.Column(
            "trim_offset_seconds",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "video_clips",
        sa.Column("trim_duration_seconds", sa.Float(), nullable=True),
    )
    op.add_column(
        "video_clips",
        sa.Column(
            "first_frame_media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "video_clips",
        sa.Column(
            "first_frame_source_asset_id",
            sa.Integer(),
            sa.ForeignKey("source_assets.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "video_clips",
        sa.Column(
            "last_frame_media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "video_clips",
        sa.Column(
            "last_frame_source_asset_id",
            sa.Integer(),
            sa.ForeignKey("source_assets.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "video_clips", sa.Column("placeholder", sa.String(), nullable=True)
    )
    op.add_column(
        "video_clips",
        sa.Column("transition_to_next_type", sa.String(), nullable=True),
    )
    op.add_column(
        "video_clips",
        sa.Column("transition_to_next_duration", sa.Float(), nullable=True),
    )
    op.drop_column("video_clips", "trim_offset")
    op.drop_column("video_clips", "trim_duration")

    # audio_clips
    op.add_column(
        "audio_clips",
        sa.Column(
            "clip_index", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "placement_video_clip_index",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "placement_offset_seconds",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "trim_offset_seconds",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "audio_clips",
        sa.Column("trim_duration_seconds", sa.Float(), nullable=True),
    )
    op.add_column(
        "audio_clips",
        sa.Column("speed", sa.Float(), server_default="1.0", nullable=False),
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "fade_in_duration_seconds",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "fade_out_duration_seconds",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "audio_clips", sa.Column("placeholder", sa.String(), nullable=True)
    )
    op.drop_column("audio_clips", "start_offset")
    op.drop_column("audio_clips", "trim_offset")
    op.drop_column("audio_clips", "trim_duration")


def downgrade() -> None:
    # audio_clips
    op.add_column(
        "audio_clips", sa.Column("trim_duration", sa.Float(), nullable=True)
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "trim_offset", sa.Float(), server_default="0.0", nullable=False
        ),
    )
    op.add_column(
        "audio_clips",
        sa.Column(
            "start_offset", sa.Float(), server_default="0.0", nullable=False
        ),
    )
    op.drop_column("audio_clips", "placeholder")
    op.drop_column("audio_clips", "fade_out_duration_seconds")
    op.drop_column("audio_clips", "fade_in_duration_seconds")
    op.drop_column("audio_clips", "speed")
    op.drop_column("audio_clips", "trim_duration_seconds")
    op.drop_column("audio_clips", "trim_offset_seconds")
    op.drop_column("audio_clips", "placement_offset_seconds")
    op.drop_column("audio_clips", "placement_video_clip_index")
    op.drop_column("audio_clips", "clip_index")

    # video_clips
    op.add_column(
        "video_clips", sa.Column("trim_duration", sa.Float(), nullable=True)
    )
    op.add_column(
        "video_clips",
        sa.Column(
            "trim_offset", sa.Float(), server_default="0.0", nullable=False
        ),
    )
    op.drop_column("video_clips", "transition_to_next_duration")
    op.drop_column("video_clips", "transition_to_next_type")
    op.drop_column("video_clips", "placeholder")
    op.drop_column("video_clips", "last_frame_source_asset_id")
    op.drop_column("video_clips", "last_frame_media_item_id")
    op.drop_column("video_clips", "first_frame_source_asset_id")
    op.drop_column("video_clips", "first_frame_media_item_id")
    op.drop_column("video_clips", "trim_duration_seconds")
    op.drop_column("video_clips", "trim_offset_seconds")
    op.drop_column("video_clips", "clip_index")

    # timelines
    op.alter_column("timelines", "storyboard_id", nullable=False)
    op.drop_column("timelines", "transition_out_duration")
    op.drop_column("timelines", "transition_out_type")
    op.drop_column("timelines", "transition_in_duration")
    op.drop_column("timelines", "transition_in_type")
    op.drop_column("timelines", "session_id")
    op.drop_column("timelines", "user_id")
    op.drop_column("timelines", "workspace_id")
