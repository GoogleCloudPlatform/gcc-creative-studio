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
"""Response DTOs for item lineage endpoints."""

import datetime

from pydantic import Field

from src.common.base_dto import BaseDto
from src.lineage.schema.item_lineage_model import LineageItemTypeEnum


class LineageNodeDto(BaseDto):
    """One node in an item's primary ancestor spine or derived children."""

    item_type: LineageItemTypeEnum
    id: int
    media_index: int = 0
    mime_type: str | None = None
    model: str | None = None
    title: str | None = None
    prompt: str | None = None
    role: str | None = None
    status: str | None = None
    thumbnail_url: str | None = None
    preview_url: str | None = None
    deleted: bool = False
    created_at: datetime.datetime | None = None


class ItemLineageResponseDto(BaseDto):
    """Full lineage response for a gallery item or source asset."""

    spine: list[LineageNodeDto] = Field(
        default_factory=list,
        description=(
            "Ordered primary inheritance chain from root ancestor to current "
            "item. Empty when the item has no primary parent."
        ),
    )
    derivatives: list[LineageNodeDto] = Field(
        default_factory=list,
        description="Direct active items derived from the current item.",
    )
