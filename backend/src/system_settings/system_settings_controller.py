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

from fastapi import APIRouter, Depends
from src.auth.auth_guard import RoleChecker, get_current_user
from src.users.user_model import UserRoleEnum
from src.system_settings.system_settings_service import SystemSettingsService
from src.system_settings.dto.system_setting_dto import SystemSettingUpdateDto
from src.system_settings.schema.system_setting_model import SystemSettingModel

router = APIRouter(
    prefix="/api/settings",
    tags=["System Settings"],
)


@router.get("/feature-flags", response_model=dict[str, bool])
async def get_feature_flags(
    service: SystemSettingsService = Depends(),
    current_user=Depends(get_current_user),
):
    """Retrieves system feature flags. Accessible by any logged-in user."""
    return await service.get_feature_flags()


@router.put("/admin/{id}", response_model=SystemSettingModel)
async def update_setting(
    id: str,
    dto: SystemSettingUpdateDto,
    service: SystemSettingsService = Depends(),
    current_user=Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN])),
):
    """Updates a system setting by its key. Restricted to Administrators."""
    return await service.update_setting(id, dto.value)


@router.get("/admin/{id}", response_model=SystemSettingModel)
async def get_admin_setting(
    id: str,
    service: SystemSettingsService = Depends(),
    current_user=Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN])),
):
    """Retrieves a system setting by its key. Restricted to Administrators."""
    return await service.get_setting(id)
