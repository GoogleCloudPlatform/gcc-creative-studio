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
"""Tests for Workbench Router."""


from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.workbench.router import router, cleanup_temp_dir
from src.workbench.service import WorkbenchService


@pytest.fixture(name="mock_workbench_service")
def fixture_mock_workbench_service():
    service = AsyncMock()
    service.render_timeline = AsyncMock()
    return service


@pytest.fixture(name="client")
def fixture_client(mock_workbench_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[WorkbenchService] = lambda: mock_workbench_service
    return TestClient(app)


def test_cleanup_temp_dir_success():
    with patch("src.workbench.router.shutil.rmtree") as mock_rmtree:
        cleanup_temp_dir("/fake/temp/dir")
        mock_rmtree.assert_called_once_with("/fake/temp/dir")


def test_cleanup_temp_dir_failure():
    with patch(
        "src.workbench.router.shutil.rmtree",
        side_effect=Exception("mock error"),
    ):
        # Should catch and handle error without raising
        cleanup_temp_dir("/fake/temp/dir")


def test_render_timeline_route_success(client, mock_workbench_service):
    mock_workbench_service.render_timeline.return_value = (
        "/fake/output.mp4",
        "/fake/temp/dir",
    )

    payload = {
        "clips": [
            {
                "assetId": "1",
                "url": "http://example.com/video.mp4",
                "startTime": 0.0,
                "duration": 5.0,
                "offset": 0.0,
                "trackIndex": 0,
                "type": "video",
            }
        ]
    }

    with patch("src.workbench.router.FileResponse") as mock_file_response:
        response = client.post("/api/workbench/render", json=payload)
        assert response.status_code == 200
        mock_workbench_service.render_timeline.assert_called_once()
