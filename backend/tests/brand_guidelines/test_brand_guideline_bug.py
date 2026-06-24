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
"""Temporary tests to verify brand guideline serialization bugs."""

from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError
from src.multimodal.gemini_service import GeminiService


@pytest.fixture(name="gemini_service")
def fixture_gemini_service():
    with patch(
        "src.multimodal.gemini_service.GeminiModelSetup.init"
    ) as mock_init:
        mock_client = MagicMock()
        mock_init.return_value = mock_client
        service = GeminiService()
        service.client = mock_client
        return service


def test_aggregate_brand_info_one_item_missing_name(gemini_service):
    # Simulate partial result from Gemini that is missing 'name'
    partial_results = [
        {
            "colorPalette": ["#000000"],
            "toneOfVoiceSummary": "cool",
            "visualStyleSummary": "sleek",
        }
    ]
    # This should raise ValidationError because 'name' is required in BrandGuidelineModel
    with pytest.raises(ValidationError) as exc_info:
        gemini_service.aggregate_brand_info(partial_results)

    assert "name" in str(exc_info.value)
    print(
        "\n[CONFIRMED] ValidationError raised as expected when 'name' is missing in single partial result."
    )


def test_aggregate_brand_info_multiple_items_gemini_missing_name(
    gemini_service,
):
    partial_results = [
        {"colorPalette": ["#000000"], "toneOfVoiceSummary": "cool"},
        {"colorPalette": ["#FFFFFF"], "visualStyleSummary": "sleek"},
    ]

    # Mock Gemini response to NOT include 'name'
    mock_response = MagicMock()
    mock_response.text = '{"colorPalette": ["#000000", "#FFFFFF"], "toneOfVoiceSummary": "cool", "visualStyleSummary": "sleek"}'
    gemini_service.client.models.generate_content.return_value = mock_response

    # This returns None because ValidationError is caught inside aggregate_brand_info
    res = gemini_service.aggregate_brand_info(partial_results)
    assert res is None
    print(
        "\n[CONFIRMED] aggregate_brand_info returned None as expected due to internal ValidationError (missing 'name')."
    )
