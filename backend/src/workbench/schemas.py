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
"""Pydantic schemas for workbench."""


from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Clip(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    asset_id: str
    url: str
    start_time: float
    duration: float
    offset: float
    track_index: int
    type: Literal["video", "audio"]


class TimelineRequest(BaseModel):
    clips: list[Clip]
    output_format: str = "mp4"
    width: int | None = 1920
    height: int | None = 1080
    hide_video: bool = False
