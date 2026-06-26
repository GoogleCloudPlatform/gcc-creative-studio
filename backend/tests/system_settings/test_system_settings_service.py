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

from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from src.system_settings.schema.system_setting_model import SystemSettingModel
from src.system_settings.system_settings_service import SystemSettingsService


@pytest.fixture(name="mock_settings_repo")
def fixture_mock_settings_repo():
    """Provides a mocked SystemSettingsRepository."""
    return AsyncMock()


@pytest.fixture(name="settings_service")
def fixture_settings_service(mock_settings_repo):
    """Provides a SystemSettingsService with a mocked repository."""
    return SystemSettingsService(repo=mock_settings_repo)


@pytest.fixture(name="mock_setting")
def fixture_mock_setting():
    """Provides a mock SystemSettingModel."""
    return SystemSettingModel(
        id="show_gemini_omni",
        value="false",
        description="Enable Gemini Omni",
    )


class TestGetSetting:
    """Tests for SystemSettingsService.get_setting."""

    @pytest.mark.anyio
    async def test_found(
        self, settings_service, mock_settings_repo, mock_setting
    ):
        mock_settings_repo.get_by_id.return_value = mock_setting

        result = await settings_service.get_setting("show_gemini_omni")

        assert result == mock_setting
        mock_settings_repo.get_by_id.assert_called_once_with("show_gemini_omni")

    @pytest.mark.anyio
    async def test_not_found(self, settings_service, mock_settings_repo):
        mock_settings_repo.get_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await settings_service.get_setting("non_existent")

        assert exc_info.value.status_code == 404
        assert (
            "System setting 'non_existent' not found." in exc_info.value.detail
        )


class TestGetFeatureFlags:
    """Tests for SystemSettingsService.get_feature_flags."""

    @pytest.mark.anyio
    async def test_feature_flags_filtering(
        self, settings_service, mock_settings_repo, mock_setting
    ):
        # Setup: Return a list containing show_gemini_omni and an unrelated setting
        other_setting = SystemSettingModel(
            id="some_other_config",
            value="true",
            description="Other config",
        )
        mock_settings_repo.find_all.return_value = [mock_setting, other_setting]

        # Action: get_feature_flags
        flags = await settings_service.get_feature_flags()

        # Assert: should only return recognized feature flags as boolean
        assert flags == {"show_gemini_omni": False}
        mock_settings_repo.find_all.assert_called_once()

    @pytest.mark.anyio
    async def test_feature_flag_true_parsing(
        self, settings_service, mock_settings_repo
    ):
        setting_true = SystemSettingModel(
            id="show_gemini_omni",
            value="true",
            description="Enable Gemini Omni",
        )
        mock_settings_repo.find_all.return_value = [setting_true]

        flags = await settings_service.get_feature_flags()

        assert flags == {"show_gemini_omni": True}


class TestUpdateSetting:
    """Tests for SystemSettingsService.update_setting."""

    @pytest.mark.anyio
    async def test_success(
        self, settings_service, mock_settings_repo, mock_setting
    ):
        # Setup mock returns
        mock_settings_repo.get_by_id.return_value = mock_setting
        updated_setting = mock_setting.model_copy(update={"value": "true"})
        mock_settings_repo.update.return_value = updated_setting

        # Action
        result = await settings_service.update_setting(
            "show_gemini_omni", "true"
        )

        # Assertions
        assert result.value == "true"
        mock_settings_repo.get_by_id.assert_called_once_with("show_gemini_omni")
        mock_settings_repo.update.assert_called_once_with(
            "show_gemini_omni", {"value": "true"}
        )

    @pytest.mark.anyio
    async def test_not_found(self, settings_service, mock_settings_repo):
        mock_settings_repo.get_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await settings_service.update_setting("non_existent", "true")

        assert exc_info.value.status_code == 404
        mock_settings_repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_update_failed_db_error(
        self, settings_service, mock_settings_repo, mock_setting
    ):
        mock_settings_repo.get_by_id.return_value = mock_setting
        mock_settings_repo.update.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await settings_service.update_setting("show_gemini_omni", "true")

        assert exc_info.value.status_code == 500
        assert "Failed to update system setting" in exc_info.value.detail
