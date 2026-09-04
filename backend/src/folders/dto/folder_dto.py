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

"""Data Transfer Objects for Folders."""

from __future__ import annotations

import datetime
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FolderCreateDto(BaseModel):
    """Payload for creating a new folder."""

    name: str = Field(
        ..., min_length=1, max_length=255, description="Name of the folder."
    )
    workspace_id: int = Field(..., description="ID of the workspace.")
    parent_id: int | None = Field(
        default=None,
        description="Parent folder ID, or None for workspace root.",
    )
    color: str | None = Field(
        default=None, description="Optional hex color code for folder badge."
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class FolderUpdateDto(BaseModel):
    """Payload for updating an existing folder."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New name of the folder.",
    )
    parent_id: int | None = Field(
        default=None,
        description="New parent folder ID (or None to move to root).",
    )
    color: str | None = Field(default=None, description="New hex color code.")

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class FolderBreadcrumbDto(BaseModel):
    """Ancestor breadcrumb node."""

    id: int
    name: str
    parent_id: int | None = None

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class FolderResponseDto(BaseModel):
    """Full folder response with item and subfolder counts."""

    id: int
    workspace_id: int
    user_id: int | None = None
    user_email: str
    name: str
    parent_id: int | None = None
    color: str | None = None
    item_count: int = 0
    subfolder_count: int = 0
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class FolderTreeNodeDto(BaseModel):
    """Recursive tree structure for folder navigation and destination picking."""

    id: int
    name: str
    parent_id: int | None = None
    color: str | None = None
    children: list[FolderTreeNodeDto] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class MoveItemsDto(BaseModel):
    """Payload for batch moving media items, source assets, and subfolders."""

    workspace_id: int = Field(
        ..., description="Workspace ID for security check."
    )
    media_item_ids: list[int] = Field(default_factory=list)
    source_asset_ids: list[int] = Field(default_factory=list)
    folder_ids: list[int] = Field(default_factory=list)
    destination_folder_id: int | None = Field(
        default=None,
        description="Target folder ID (None to move to root level).",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )
