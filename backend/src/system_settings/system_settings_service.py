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

from fastapi import Depends, HTTPException, status
from src.system_settings.repository.system_settings_repository import (
    SystemSettingsRepository,
)
from src.system_settings.schema.system_setting_model import SystemSettingModel


class SystemSettingsService:
    """Provides business logic for system settings operations."""

    def __init__(self, repo: SystemSettingsRepository = Depends()):
        self.repo = repo

    async def get_setting(self, id: str) -> SystemSettingModel:
        """Retrieves a system setting by its key, raising 404 if not found."""
        setting = await self.repo.get_by_id(id)
        if not setting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"System setting '{id}' not found.",
            )
        return setting

    async def get_feature_flags(self) -> dict[str, bool]:
        """Retrieves all public feature flag system settings as a boolean dictionary."""
        settings = await self.repo.find_all(limit=100)
        flags = {}
        for s in settings:
            # Only return recognized feature flags to keep public API focused
            if s.id in ["show_gemini_omni"]:
                flags[s.id] = s.value.lower() == "true"
        return flags

    async def update_setting(self, id: str, value: str) -> SystemSettingModel:
        """Updates the value of a system setting, raising 404 if not found."""
        setting = await self.repo.get_by_id(id)
        if not setting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"System setting '{id}' not found.",
            )
        updated = await self.repo.update(id, {"value": value})
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update system setting '{id}'.",
            )
        return updated
