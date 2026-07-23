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

from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel
from src.tags.schema.tags_model import TagModel


class UnifiedGalleryItemResponse(BaseModel):
    """Response model for a unified gallery item (MediaItem or SourceAsset)."""

    id: int
    workspace_id: int
    created_at: datetime
    item_type: str  # 'media_item' or 'source_asset'
    status: str | None = None
    gcs_uris: list[str] = []
    thumbnail_uris: list[str] = []
    tags: list[TagModel] = []
    deleted_at: datetime | None = None  # To support frontend filters
    workspace_name: str | None = None
    user_picture: str | None = None
    user_email: str | None = None
    titles: list[str] | None = Field(default_factory=list)
    descriptions: list[str] | None = Field(default_factory=list)
    # Map from 'metadata_' in SQLAlchemy model to 'metadata' in Pydantic
    metadata: dict[str, Any] = Field(
        default_factory=dict, validation_alias="metadata_"
    )

    @field_validator("metadata", mode="after")
    @classmethod
    def convert_metadata_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Converts metadata keys to camelCase for frontend support."""
        if isinstance(v, dict):
            return {to_camel(k): val for k, val in v.items()}
        return v

    @model_validator(mode="after")
    def extract_tags_from_metadata(self) -> "UnifiedGalleryItemResponse":
        """Extracts tags from metadata if present."""
        if self.metadata and "tags" in self.metadata:
            tags_val = self.metadata.pop("tags")
            if isinstance(tags_val, list):
                self.tags = [
                    TagModel.model_validate(t)
                    for t in tags_val
                    if isinstance(t, dict)
                ]
        return self

    # Presigned URLs will be injected by the service
    presigned_urls: list[str] = []
    presigned_thumbnail_urls: list[str] = []

    # For compatibility with frontend expecting specific fields at top level,
    # we might want to flatten metadata or keep it nested.
    # The plan implied "UnifiedGalleryItem" response.
    # Frontend likely needs to know which fields to access.
    # For simplicity, we can pass metadata as is, and let frontend map it.

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        from_attributes=True,
    )
