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
from fastapi import HTTPException, status

from main import app
from src.projects.dto.project_dto import ProjectResponse
from src.projects.project_service import ProjectService
from src.workbench.dto.workbench_dto import TimelineResponse
from src.workbench.timeline_auth_guard import TimelineAccess, TimelineAuth
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.common.base_dto import (
    GenerationModelEnum,
    MimeTypeEnum,
    AspectRatioEnum,
)
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.common.schema.media_item_model import (
    MimeTypeEnum,
    GenerationModelEnum,
    AspectRatioEnum,
    JobStatusEnum,
)
from src.workbench.workbench_service import WorkbenchService


def _project(project_id=7, workspace_id=1):
    return ProjectResponse(
        id=project_id, workspace_id=workspace_id, owner_id=1, name="P"
    )


@pytest.fixture(name="mock_workbench_service")
def fixture_mock_workbench_service():
    """Provides a mocked WorkbenchService."""
    return AsyncMock()


@pytest.fixture(name="mock_timeline_auth")
def fixture_mock_timeline_auth():
    """The caller owns every timeline (project 7, storyboard 10)."""
    timeline_auth = AsyncMock()
    timeline_auth.authorize.return_value = TimelineAccess(
        timeline_id=1,
        project_id=7,
        storyboard_id=10,
        user_id="1",
        workspace_id=1,
    )
    return timeline_auth


@pytest.fixture(name="mock_project_service")
def fixture_mock_project_service():
    project_service = AsyncMock()
    project_service.resolve_project_for_write.return_value = _project()
    project_service.authorize_storyboard.return_value = _project()
    return project_service


from fastapi.security import HTTPAuthorizationCredentials
from src.workbench.workbench_controller import security


@pytest.fixture(name="override_workbench_service", autouse=True)
def fixture_override_workbench_service(
    mock_workbench_service, mock_timeline_auth, mock_project_service
):
    """Overrides the WorkbenchService and security dependency in the app."""
    app.dependency_overrides[WorkbenchService] = lambda: mock_workbench_service
    app.dependency_overrides[TimelineAuth] = lambda: mock_timeline_auth
    app.dependency_overrides[ProjectService] = lambda: mock_project_service
    app.dependency_overrides[security] = lambda: HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="mock"
    )
    yield
    for dependency in (
        WorkbenchService,
        TimelineAuth,
        ProjectService,
        security,
    ):
        app.dependency_overrides.pop(dependency, None)


class TestWorkbenchController:
    """Tests for Workbench Controller endpoints."""

    def test_render_timeline(self, api_client, mock_workbench_service):
        mock_res = MediaItemResponse(
            id=10,
            workspace_id=1,
            user_email="user@test.com",
            mime_type=MimeTypeEnum.VIDEO_MP4,
            model=GenerationModelEnum.WORKBENCH_RENDER,
            aspect_ratio=AspectRatioEnum.RATIO_16_9,
            status=JobStatusEnum.PROCESSING,
            gcs_uris=["gs://bucket/renders/export.mp4"],
        )
        mock_workbench_service.render_timeline_by_id.return_value = mock_res

        response = api_client.post("/api/workbench/timelines/1/render")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == 10
        assert response.json()["workspaceId"] == 1

        payload = {"timeline_id": 1}
        response_legacy = api_client.post("/api/workbench/render", json=payload)
        assert response_legacy.status_code == status.HTTP_200_OK
        assert response_legacy.json()["id"] == 10

    def test_create_timeline(self, api_client, mock_workbench_service):
        mock_res = TimelineResponse(
            timeline_id=1, storyboard_id=5, workspace_id="ws1", title="New"
        )
        mock_workbench_service.create_timeline.return_value = mock_res

        payload = {
            "storyboardId": 5,
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
        assert (
            response.json().get("storyboard_id") == 5
            or response.json().get("storyboardId") == 5
        )
        # A human request never replaces an existing cut in place.
        assert (
            mock_workbench_service.create_timeline.await_args.kwargs[
                "reuse_for_storyboard"
            ]
            is False
        )
        # Project, owner and workspace are stamped server-side.
        created = mock_workbench_service.create_timeline.await_args.args[0]
        assert created.project_id == 7
        assert created.user_id == "1"
        assert created.workspace_id == "1"

    def test_create_timeline_resolves_the_project_from_the_payload(
        self, api_client, mock_workbench_service, mock_project_service
    ):
        mock_workbench_service.create_timeline.return_value = TimelineResponse(
            timeline_id=1, workspace_id="1", title="New"
        )
        payload = {
            "storyboard_id": "5",
            "project_id": 7,
            "session_id": "s1",
            "workspace_id": "1",
            "user_id": "999",
            "title": "New",
        }

        response = api_client.post("/api/workbench/timelines", json=payload)

        assert response.status_code == status.HTTP_201_CREATED
        mock_project_service.resolve_project_for_write.assert_awaited_once()
        call = mock_project_service.resolve_project_for_write.await_args
        assert call.args[1] == 1
        assert call.kwargs == {
            "project_id": 7,
            "storyboard_id": 5,
            "session_id": "s1",
        }
        # A client-sent owner is never trusted.
        created = mock_workbench_service.create_timeline.await_args.args[0]
        assert created.user_id == "1"

    def test_create_timeline_refused_project_is_not_created(
        self, api_client, mock_workbench_service, mock_project_service
    ):
        mock_project_service.resolve_project_for_write.side_effect = (
            HTTPException(status_code=403, detail="not yours")
        )
        payload = {"workspace_id": "1", "title": "New", "project_id": 8}

        response = api_client.post("/api/workbench/timelines", json=payload)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_workbench_service.create_timeline.assert_not_called()

    def test_create_timeline_from_agent_reuses_storyboard_cut(
        self, api_client, mock_workbench_service
    ):
        from src.common.request_context import is_agent_request

        mock_workbench_service.create_timeline.return_value = TimelineResponse(
            timeline_id=9, storyboard_id=5, workspace_id="ws1", title="Cut"
        )
        payload = {
            "storyboardId": 5,
            "workspace_id": "ws1",
            "title": "Cut",
            "video_clips": [],
            "audio_clips": [],
            "transitions": [],
        }
        # The auth guard sets this for X-User-Authorization requests; the
        # TestClient runs the app in the same context, so set it directly.
        token = is_agent_request.set(True)
        try:
            response = api_client.post("/api/workbench/timelines", json=payload)
        finally:
            is_agent_request.reset(token)
        assert response.status_code == status.HTTP_201_CREATED
        assert (
            mock_workbench_service.create_timeline.await_args.kwargs[
                "reuse_for_storyboard"
            ]
            is True
        )

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
            timeline_id=4, storyboard_id=10, workspace_id="ws1", title="Updated"
        )
        mock_workbench_service.update_timeline.return_value = mock_res

        payload = {
            "storyboard_id": 10,
            "workspace_id": "ws1",
            "title": "Updated",
            "video_clips": [],
            "audio_clips": [],
            "transitions": [],
        }
        response = api_client.put("/api/workbench/timelines/4", json=payload)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Updated"
        assert (
            response.json().get("storyboard_id") == 10
            or response.json().get("storyboardId") == 10
        )

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


class TestTimelineAuthorization:
    """Every timeline-by-id route is owner-scoped (security fix)."""

    def test_foreign_timeline_is_refused_on_every_route(
        self, api_client, mock_workbench_service, mock_timeline_auth
    ):
        mock_timeline_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="Not authorized to access this timeline"
        )
        body = {"workspace_id": "1", "title": "T"}

        responses = [
            api_client.get("/api/workbench/timelines/4"),
            api_client.put("/api/workbench/timelines/4", json=body),
            api_client.delete("/api/workbench/timelines/4"),
            api_client.post("/api/workbench/timelines/4/render"),
            api_client.post("/api/workbench/render", json={"timeline_id": 4}),
        ]

        assert [r.status_code for r in responses] == [403] * 5
        mock_workbench_service.get_timeline.assert_not_called()
        mock_workbench_service.update_timeline.assert_not_called()
        mock_workbench_service.delete_timeline.assert_not_called()
        mock_workbench_service.render_timeline_by_id.assert_not_called()

    def test_render_without_timeline_id_is_400(self, api_client):
        response = api_client.post("/api/workbench/render", json={})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_listing_a_foreign_storyboard_is_refused(
        self, api_client, mock_workbench_service, mock_project_service
    ):
        mock_project_service.authorize_storyboard.side_effect = HTTPException(
            status_code=403, detail="Not authorized to use this storyboard"
        )

        response = api_client.get(
            "/api/workbench/timelines", params={"storyboard_id": 30}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_workbench_service.list_timelines.assert_not_called()

    def test_update_stamps_server_side_fields(
        self, api_client, mock_workbench_service, mock_project_service
    ):
        mock_workbench_service.update_timeline.return_value = TimelineResponse(
            timeline_id=4, workspace_id="1", title="T"
        )
        body = {
            "storyboard_id": 10,
            "workspace_id": "999",
            "user_id": "999",
            "project_id": 999,
            "title": "T",
        }

        response = api_client.put("/api/workbench/timelines/4", json=body)

        assert response.status_code == status.HTTP_200_OK
        updated = mock_workbench_service.update_timeline.await_args.args[1]
        assert updated.project_id == 7
        assert updated.user_id == "1"
        assert updated.workspace_id == "1"
        # Same storyboard as before: no re-link check needed.
        mock_project_service.authorize_storyboard.assert_not_called()

    def test_update_refuses_a_storyboard_of_another_project(
        self, api_client, mock_workbench_service, mock_project_service
    ):
        mock_project_service.authorize_storyboard.return_value = _project(8)
        body = {"storyboard_id": 11, "workspace_id": "1", "title": "T"}

        response = api_client.put("/api/workbench/timelines/4", json=body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_workbench_service.update_timeline.assert_not_called()

    def test_update_of_a_legacy_timeline_claims_the_storyboard_project(
        self,
        admin_client,
        mock_workbench_service,
        mock_project_service,
        mock_timeline_auth,
    ):
        mock_timeline_auth.authorize.return_value = TimelineAccess(
            timeline_id=4,
            project_id=None,
            storyboard_id=None,
            user_id=None,
            workspace_id=None,
        )
        mock_project_service.authorize_storyboard.return_value = _project(8)
        mock_workbench_service.update_timeline.return_value = TimelineResponse(
            timeline_id=4, workspace_id="1", title="T"
        )
        body = {"storyboard_id": 11, "workspace_id": "3", "title": "T"}

        response = admin_client.put("/api/workbench/timelines/4", json=body)

        assert response.status_code == status.HTTP_200_OK
        updated = mock_workbench_service.update_timeline.await_args.args[1]
        assert updated.project_id == 8
        # No project workspace to impose: the payload's value is kept.
        assert updated.workspace_id == "3"
