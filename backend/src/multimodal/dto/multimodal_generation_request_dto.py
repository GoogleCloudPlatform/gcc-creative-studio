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

from typing import Annotated, Any
from pydantic import Field, AliasChoices
from src.common.base_dto import BaseDto, GenerationModelEnum


class MultimodalGenerationRequestDto(BaseDto):
    workspace_id: Annotated[
        int,
        Field(description="The workspace ID this request belongs to."),
    ]
    prompt: Annotated[
        str,
        Field(description="The text prompt to send to the model."),
    ]
    media_items: Annotated[
        list[int] | None,
        Field(
            default=None,
            validation_alias=AliasChoices(
                "media_items", "mediaItems", "media_item_ids", "mediaItemIds"
            ),
            description="Optional list of MediaItem IDs to include.",
        ),
    ]
    assets: Annotated[
        list[int] | None,
        Field(
            default=None,
            validation_alias=AliasChoices(
                "assets", "source_asset_ids", "sourceAssetIds"
            ),
            description="Optional list of SourceAsset IDs to include.",
        ),
    ]
    model: Annotated[
        GenerationModelEnum,
        Field(
            default=GenerationModelEnum.GEMINI_3_5_FLASH,
            description="The Gemini model to use.",
        ),
    ]
    config: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description="Optional configuration parameters for the model.",
        ),
    ]

    @property
    def media_item_ids(self) -> list[int] | None:
        return self.media_items

    @property
    def source_asset_ids(self) -> list[int] | None:
        return self.assets


class MultimodalGenerationResponseDto(BaseDto):
    text: str
