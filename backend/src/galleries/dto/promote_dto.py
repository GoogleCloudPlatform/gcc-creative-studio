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
"""DTOs for cross-workspace promotion target discovery and execution."""

from typing import Literal

from pydantic import Field

from src.common.base_dto import BaseDto
from src.galleries.dto.bulk_copy_dto import BulkCopyItemDto
from src.galleries.dto.unified_gallery_response import PromotionSummaryDto


class PromoteTargetsRequestDto(BaseDto):
    """Request body for listing writable promotion targets and match counts."""

    source_workspace_id: int = Field(ge=1)
    items: list[BulkCopyItemDto] = Field(min_length=1)


class PromoteTargetWorkspaceDto(BaseDto):
    """Target workspace option enriched with existing vs net-new item counts."""

    workspace_id: int
    workspace_name: str
    scope: str
    current_user_role: str | None = None
    existing_count: int = 0
    new_count: int = 0
    existing_promotion: PromotionSummaryDto | None = None


class PromoteItemsDto(BaseDto):
    """Request body to promote items or folders into a shared workspace."""

    items: list[BulkCopyItemDto] = Field(min_length=1)
    source_workspace_id: int = Field(ge=1)
    target_workspace_id: int = Field(ge=1)
    target_folder_id: int | None = Field(default=None, ge=1)
    clear_target_folder: bool = False
    mode: Literal["update_or_create", "create_new"] = "update_or_create"


class PromoteResultItemDto(BaseDto):
    """Per-item outcome of a promotion operation."""

    source_id: int
    source_type: str
    target_id: int
    target_workspace_id: int
    target_folder_id: int | None = None
    action: Literal["created", "updated"]


class PromoteResponseDto(BaseDto):
    """Summary response for POST /api/gallery/promote."""

    promoted_count: int
    updated_count: int
    created_count: int
    target_workspace_id: int
    target_folder_id: int | None = None
    promoted_items: list[PromoteResultItemDto] = Field(default_factory=list)
