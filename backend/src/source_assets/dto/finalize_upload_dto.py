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

from pydantic import Field

from src.common.base_dto import AspectRatioEnum, BaseDto
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
)


class FinalizeSourceAssetUploadDto(BaseDto):
    """Request DTO to complete asset registration after successful GCS upload."""

    workspace_id: int = Field(description="The target workspace ID.")
    gcs_uri: str = Field(
        description="The gs:// path where the file was uploaded."
    )
    filename: str = Field(description="The original filename of the asset.")
    mime_type: str = Field(description="The MIME type of the asset.")
    size: int = Field(gt=0, description="The size of the file in bytes.")
    asset_type: AssetTypeEnum | None = Field(
        default=None, description="Asset type classification."
    )
    aspect_ratio: AspectRatioEnum | None = Field(
        default=None, description="Aspect ratio of the media asset."
    )
    scope: AssetScopeEnum | None = Field(
        default=None, description="Scope of the asset."
    )
