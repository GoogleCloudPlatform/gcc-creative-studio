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

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseStringRepository
from src.database import get_db
from src.system_settings.schema.system_setting_model import (
    SystemSetting,
    SystemSettingModel,
)


class SystemSettingsRepository(
    BaseStringRepository[SystemSetting, SystemSettingModel]
):
    """Handles database operations for SystemSetting objects using string keys as IDs."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=SystemSetting, schema=SystemSettingModel, db=db)
