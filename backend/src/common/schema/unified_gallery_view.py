# Copyright 2025 Google LLC
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

import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class UnifiedGalleryView(Base):
    """SQLAlchemy model for the 'unified_gallery_view' VIEW.
    This view combines MediaItems and SourceAssets for the gallery.
    """

    __tablename__ = "unified_gallery_view"

    # We use managed = False because this is a VIEW, not a TABLE.
    # The view is created via Alembic migration.
    __table_args__ = {"info": {"is_view": True}}

    # The ID might not be unique across tables if we just use the original ID,
    # but the view definition selects 'id' from both.
    # To be safe for SQLAlchemy identity map, we might need a composite key or a unique synthetic key.
    # However, for read-only purposes, if we filtering by item_type + id it should be fine.
    # Let's hope the view construction handles uniqueness or we treat (id, item_type) as primary key.

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id"),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True)
    )
    item_type: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )  # 'media_item' or 'source_asset'
    status: Mapped[str | None] = mapped_column(String)
    workspace_name: Mapped[str | None] = mapped_column(String)
    user_picture: Mapped[str | None] = mapped_column(String)
    user_email: Mapped[str | None] = mapped_column(String)
    titles: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    descriptions: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    # Unified arrays for display
    gcs_uris: Mapped[list[str]] = mapped_column(ARRAY(String))
    thumbnail_uris: Mapped[list[str]] = mapped_column(ARRAY(String))
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    # Metadata contains specific fields for each type
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB)
