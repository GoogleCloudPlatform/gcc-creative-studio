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
"""Tests for Brand Guideline Service Background Worker."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.brand_guidelines.brand_guideline_service import (
    _process_brand_guideline_in_background,
)
from src.common.schema.media_item_model import JobStatusEnum


@pytest.mark.xfail(
    reason="Exposes download failure handling bug in brand guideline worker"
)
@patch("src.database.WorkerDatabase")
def test_process_brand_guideline_download_failure(mock_worker_db_class):
    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    # Patch dependencies inside the worker
    with (
        patch(
            "src.brand_guidelines.brand_guideline_service.BrandGuidelineRepository"
        ) as mock_repo_class,
        patch(
            "src.brand_guidelines.brand_guideline_service.GcsService"
        ) as mock_gcs_class,
        patch(
            "src.brand_guidelines.brand_guideline_service.GeminiService"
        ) as mock_gemini_class,
    ):
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo

        mock_gcs = MagicMock()
        mock_gcs_class.return_value = mock_gcs
        # Simulate download failure by returning None
        mock_gcs.download_bytes_from_gcs.return_value = None
        mock_gcs.upload_bytes_to_gcs.return_value = None

        mock_gemini = MagicMock()
        mock_gemini_class.return_value = mock_gemini

        # Call the worker
        _process_brand_guideline_in_background(
            guideline_id=1,
            name="Test Guideline",
            original_filename="test.pdf",
            source_gcs_uri="gs://bucket/test.pdf",
            workspace_id=1,
        )

        # Assertions
        # 1. download_bytes_from_gcs should have been called
        mock_gcs.download_bytes_from_gcs.assert_called_once_with(
            "gs://bucket/test.pdf"
        )

        # 2. upload_bytes_to_gcs should NOT have been called because download failed
        mock_gcs.upload_bytes_to_gcs.assert_not_called()

        # 3. The repository should have been updated with FAILED status
        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args
        assert call_args is not None
        assert call_args[0][0] == 1  # guideline_id
        assert call_args[0][1]["status"] == JobStatusEnum.FAILED
        assert "Failed to download" in call_args[0][1]["error_message"]
