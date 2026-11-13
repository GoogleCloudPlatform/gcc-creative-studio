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

from typing import Literal

from src.common.base_dto import BaseDto


class AdminOverviewStats(BaseDto):
    total_users: int
    total_workspaces: int
    images_generated: int
    videos_generated: int
    audios_generated: int
    total_media: int
    user_uploaded_media: int
    overall_total_media: int


class AdminMediaOverTime(BaseDto):
    date: str
    total_generated: int
    images: int
    videos: int
    audios: int


class AdminWorkspaceStats(BaseDto):
    workspace_id: int
    workspace_name: str | None = None
    total_media: int
    images: int
    videos: int
    audios: int


class AdminActiveRole(BaseDto):
    role: str
    count: int


class AdminGenerationHealth(BaseDto):
    status: str
    count: int


class AdminMonthlyActiveUsers(BaseDto):
    month: str
    count: int


VersionStatusLiteral = Literal[
    "up_to_date",
    "update_available",
    "unavailable",
]


class AdminVersionInfo(BaseDto):
    current_version: str
    latest_version: str | None = None
    status: VersionStatusLiteral
    release_url: str | None = None
    release_name: str | None = None
    published_at: str | None = None
    checked_at: str
