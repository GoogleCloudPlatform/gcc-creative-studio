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
"""SQLAlchemy model and enums for polymorphic item lineage edges."""

import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class LineageItemTypeEnum(str, Enum):
    """Identifies which gallery table owns a lineage graph node."""

    MEDIA_ITEM = "media_item"
    SOURCE_ASSET = "source_asset"


class LineageRoleEnum(str, Enum):
    """Describes how a parent item contributed to a child item.

    Includes all ``AssetRoleEnum`` values plus explicit iteration/transformation
    roles used on primary inheritance edges.
    """

    INPUT = "input"
    STYLE_REFERENCE = "style_reference"
    START_FRAME = "start_frame"
    END_FRAME = "end_frame"
    MASK = "mask"
    VTO_PERSON = "vto_person"
    VTO_TOP = "vto_top"
    VTO_BOTTOM = "vto_bottom"
    VTO_DRESS = "vto_dress"
    VTO_SHOE = "vto_shoe"
    VIDEO_EXTENSION_SOURCE = "video_extension_source"
    VIDEO_EXTENSION_CHUNK = "video_extension_chunk"
    CONCATENATION_SOURCE = "concatenation_source"
    IMAGE_REFERENCE_STYLE = "image_reference_style"
    IMAGE_REFERENCE_ASSET = "image_reference_asset"
    VIDEO_REFERENCE = "video_reference"
    AUDIO_REFERENCE = "audio_reference"
    YOUTUBE_VIDEO_REFERENCE = "youtube_video_reference"

    # Explicit primary transformation / iteration roles
    IMAGE_EDIT_SOURCE = "image_edit_source"
    CROP_SOURCE = "crop_source"
    UPSCALE_SOURCE = "upscale_source"
    OMNI_EDIT_SOURCE = "omni_edit_source"
    AUDIO_ITERATION_SOURCE = "audio_iteration_source"
    AUDIO_STEM_SOURCE = "audio_stem_source"


class ItemLineage(Base):
    """Directed ``parent -> child`` edge across media items and assets."""

    __tablename__ = "item_lineage"
    __table_args__ = (
        Index(
            "ix_item_lineage_child",
            "workspace_id",
            "child_type",
            "child_id",
        ),
        Index(
            "ix_item_lineage_parent",
            "workspace_id",
            "parent_type",
            "parent_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_type: Mapped[str] = mapped_column(String(16), nullable=False)
    child_id: Mapped[int] = mapped_column(Integer, nullable=False)
    child_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    parent_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    role: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary_parent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    action_summary: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
