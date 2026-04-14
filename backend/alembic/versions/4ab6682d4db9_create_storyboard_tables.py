"""create_storyboard_tables

Revision ID: 4ab6682d4db9
Revises: 8493cfe9111e
Create Date: 2026-04-14 19:50:19.192265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ab6682d4db9'
down_revision: Union[str, None] = '6fe30cbfe2c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create storyboards table
    op.create_table(
        "storyboards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("template_name", sa.String(), nullable=True),
        sa.Column("bg_music_description", sa.String(), nullable=True),
        sa.Column("bg_music_asset_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create timelines table
    op.create_table(
        "timelines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create scenes table
    op.create_table(
        "scenes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("storyboard_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("first_frame_description", sa.String(), nullable=True),
        sa.Column("first_frame_media_item_id", sa.Integer(), nullable=True),
        sa.Column("first_frame_source_asset_id", sa.Integer(), nullable=True),
        sa.Column("first_frame_generated_url", sa.String(), nullable=True),
        sa.Column("video_description", sa.String(), nullable=True),
        sa.Column("video_duration_seconds", sa.Float(), nullable=True),
        sa.Column("video_media_item_id", sa.Integer(), nullable=True),
        sa.Column("video_source_asset_id", sa.Integer(), nullable=True),
        sa.Column("video_generated_url", sa.String(), nullable=True),
        sa.Column("voiceover_text", sa.String(), nullable=True),
        sa.Column("voiceover_gender", sa.String(), nullable=True),
        sa.Column("voiceover_description", sa.String(), nullable=True),
        sa.Column("voiceover_media_item_id", sa.Integer(), nullable=True),
        sa.Column("voiceover_source_asset_id", sa.Integer(), nullable=True),
        sa.Column("transition_type", sa.String(), nullable=True),
        sa.Column("transition_duration", sa.Float(), nullable=True),
        sa.Column("audio_ambient_description", sa.String(), nullable=True),
        sa.Column("audio_sfx_description", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["storyboard_id"], ["storyboards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create video_clips table
    op.create_table(
        "video_clips",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timeline_id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column("source_asset_id", sa.Integer(), nullable=True),
        sa.Column("trim_offset", sa.Float(), nullable=False),
        sa.Column("trim_duration", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["timeline_id"], ["timelines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create audio_clips table
    op.create_table(
        "audio_clips",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timeline_id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column("source_asset_id", sa.Integer(), nullable=True),
        sa.Column("start_offset", sa.Float(), nullable=False),
        sa.Column("trim_offset", sa.Float(), nullable=False),
        sa.Column("trim_duration", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["timeline_id"], ["timelines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audio_clips")
    op.drop_table("video_clips")
    op.drop_table("scenes")
    op.drop_table("timelines")
    op.drop_table("storyboards")

