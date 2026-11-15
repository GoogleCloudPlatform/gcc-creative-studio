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

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from src.media_templates.schema.media_template_model import IndustryEnum


class CreatePromptTemplateDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        Field(
            min_length=1,
            description="The display name of the template, e.g., 'Cinematic Rolex Watch Ad'.",
        ),
    ]
    description: Annotated[
        str,
        Field(
            min_length=1,
            description="A brief explanation of what the template is for and its intended use case.",
        ),
    ]

    # --- Categorization & Filtering Fields ---
    industry: IndustryEnum | None = Field(
        default=None,
        description="The target industry for this template.",
    )
    brand: str | None = Field(
        default=None,
        description="The specific brand this template is inspired by, e.g., 'IKEA'.",
    )
    tags: list[str] | None = Field(
        default_factory=list,
        description="A list of searchable keywords for filtering, e.g., ['futuristic', 'vibrant'].",
    )
