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

from pydantic import BaseModel, ConfigDict, Field
from src.common.dto.base_search_dto import BaseSearchDto


class TagCreateDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="The name of the tag.")
    workspace_id: int = Field(
        ..., description="The ID of the workspace this tag belongs to."
    )
    color: str | None = Field(
        default=None, description="The color of the tag in hex format."
    )


class TagUpdateDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None, description="The new name of the tag."
    )
    color: str | None = Field(
        default=None, description="The new color of the tag."
    )


class BulkAssignTagsDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: int = Field(
        ..., description="The ID of the workspace these items belong to."
    )
    item_ids: list[int] = Field(..., description="List of IDs of items to tag.")
    item_type: str = Field(..., description="'media_item' or 'source_asset'")
    tag_names: list[str] = Field(
        ..., description="List of tag names to assign."
    )


class TagSearchDto(BaseSearchDto):
    workspace_id: int | None = Field(
        None, description="The ID of the workspace to search within."
    )
    search: str | None = Field(None, description="Search query for tag name.")
    user_id: int | None = Field(None, description="Filter by user ID.")
