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
"""Tests for Workbench Controller."""


import os
import tempfile
from unittest.mock import AsyncMock
import pytest
from fastapi import status

from main import app
from src.workbench.dto.workbench_dto import TimelineResponse
from src.workbench.workbench_service import WorkbenchService


@pytest.fixture(name="mock_workbench_service")
def fixture_mock_workbench_service():
    """Provides a mocked WorkbenchService."""
    return AsyncMock()


from fastapi.security import HTTPAuthorizationCredentials
from src.workbench.workbench_controller import security


@pytest.fixture(name="override_workbench_service", autouse=True)
def fixture_override_workbench_service(mock_workbench_service):
    """Overrides the WorkbenchService and security dependency in the app."""
    app.dependency_overrides[WorkbenchService] = lambda: mock_workbench_service
    app.dependency_overrides[security] = lambda: HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="mock"
    )
    yield
    if WorkbenchService in app.dependency_overrides:
        del app.dependency_overrides[WorkbenchService]
    if security in app.dependency_overrides:
        del app.dependency_overrides[security]


class TestWorkbenchController:
    """Tests for Workbench Controller endpoints."""

    def test_render_timeline(self, api_client, mock_workbench_service):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"dummy video content")
            tf_path = tf.name

        temp_dir = tempfile.mkdtemp()
        mock_workbench_service.render_timeline.return_value = (
            tf_path,
            temp_dir,
        )

        payload = {
            "clips": [
                {
                    "assetId": "1",
                    "url": "http://example.com/v.mp4",
                    "startTime": 0.0,
                    "duration": 5.0,
                    "offset": 0.0,
                    "trackIndex": 0,
                    "type": "video",
                }
            ]
        }
        response = api_client.post("/api/workbench/render", json=payload)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "video/mp4"

        if os.path.exists(tf_path):
            os.remove(tf_path)

    def test_create_timeline(self, api_client, mock_workbench_service):
        mock_res = TimelineResponse(
            timeline_id=1, workspace_id="ws1", title="New"
        )
        mock_workbench_service.create_timeline.return_value = mock_res

        payload = {
            "workspace_id": "ws1",
            "title": "New",
            "video_clips": [],
            "audio_clips": [],
            "transitions": [],
        }
        response = api_client.post("/api/workbench/timelines", json=payload)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["timeline_id"] == 1
        assert response.json()["title"] == "New"

    def test_get_timeline_found(self, api_client, mock_workbench_service):
        mock_res = TimelineResponse(
            timeline_id=2, workspace_id="ws1", title="Found"
        )
        mock_workbench_service.get_timeline.return_value = mock_res

        response = api_client.get("/api/workbench/timelines/2")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["timeline_id"] == 2

    def test_get_timeline_not_found(self, api_client, mock_workbench_service):
        mock_workbench_service.get_timeline.return_value = None

        response = api_client.get("/api/workbench/timelines/999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Timeline not found"

    def test_list_timelines(self, api_client, mock_workbench_service):
        mock_res = [
            TimelineResponse(timeline_id=3, workspace_id="ws1", title="T3")
        ]
        mock_workbench_service.list_timelines.return_value = mock_res

        response = api_client.get(
            "/api/workbench/timelines", params={"storyboard_id": 30}
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["timeline_id"] == 3

    def test_update_timeline_found(self, api_client, mock_workbench_service):
        mock_res = TimelineResponse(
            timeline_id=4, workspace_id="ws1", title="Updated"
        )
        mock_workbench_service.update_timeline.return_value = mock_res

        payload = {
            "workspace_id": "ws1",
            "title": "Updated",
            "video_clips": [],
            "audio_clips": [],
            "transitions": [],
        }
        response = api_client.put("/api/workbench/timelines/4", json=payload)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Updated"

    def test_update_timeline_not_found(
        self, api_client, mock_workbench_service
    ):
        mock_workbench_service.update_timeline.return_value = None

        payload = {
            "workspace_id": "ws1",
            "title": "Updated",
            "video_clips": [],
            "audio_clips": [],
            "transitions": [],
        }
        response = api_client.put("/api/workbench/timelines/999", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_timeline_found(self, api_client, mock_workbench_service):
        mock_workbench_service.delete_timeline.return_value = True

        response = api_client.delete("/api/workbench/timelines/5")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_timeline_not_found(
        self, api_client, mock_workbench_service
    ):
        mock_workbench_service.delete_timeline.return_value = False

        response = api_client.delete("/api/workbench/timelines/999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
