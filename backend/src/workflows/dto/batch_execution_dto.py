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

from typing import Any, List, Optional
from pydantic import BaseModel, Field
from src.common.base_dto import BaseDto

class BatchExecutionItemDto(BaseModel):
    """Represents a single row of execution arguments."""
    row_index: int = Field(..., description="The original index from the CSV for tracking")
    args: dict[str, Any] = Field(..., description="The input arguments for this execution")

class BatchExecutionRequestDto(BaseDto):
    """Request DTO for batch execution."""
    items: List[BatchExecutionItemDto] = Field(..., description="List of items to execute")

class BatchItemResultDto(BaseModel):
    """Result of a single batch item execution."""
    row_index: int
    execution_id: Optional[str] = None
    status: str = Field(..., description="SUCCESS or FAILED")
    error: Optional[str] = None

class BatchExecutionResponseDto(BaseDto):
    """Response DTO for batch execution."""
    results: List[BatchItemResultDto]
