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


from src.common.schema.media_item_model import (
    MediaItemModel,
    SourceAssetLink,
    SourceMediaItemLink,
)
from src.tags.schema.tags_model import TagModel


class SourceAssetLinkResponse(SourceAssetLink):
    """Extends the source asset link with a presigned URL and GCS URI for frontend display."""

    presigned_url: str
    gcs_uri: str
    presigned_thumbnail_url: str | None = None
    mime_type: str | None = None


class SourceMediaItemLinkResponse(SourceMediaItemLink):
    """Extends the source media item link with a presigned URL and GCS URI for frontend display."""

    presigned_url: str
    gcs_uri: str
    presigned_thumbnail_url: str | None = None
    mime_type: str | None = None


class MediaItemResponse(MediaItemModel):
    """The response model for a gallery item.
    It includes all fields from the original MediaItem plus a list of
    temporary, presigned URLs for frontend display.
    """

    presigned_urls: list[str] = []
    original_presigned_urls: list[str] | None = None
    presigned_thumbnail_urls: list[str] | None = []
    enriched_source_assets: list[SourceAssetLinkResponse] | None = None
    enriched_source_media_items: list[SourceMediaItemLinkResponse] | None = None
    tags: list[TagModel] | None = None
    user_picture: str | None = None
