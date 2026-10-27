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

"""Projects router: owner-only CRUD, ensure-default, resolve and delete."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from main import app
from src.agents.agent_service import AgentService
from src.projects.dto.project_dto import ProjectResponse
from src.projects.project_service import (
    DEFAULT_PROJECT_DELETE_DETAIL,
    ProjectService,
)

BUSY_DETAIL = (
    "A chat in this project is still running. Wait for Izumi to finish "
    "before deleting the project."
)


def _project(project_id=7, workspace_id=10, is_default=False, **extra):
    return ProjectResponse(
        id=project_id,
        workspace_id=workspace_id,
        owner_id=1,
        name="Default project" if is_default else "Launch",
        is_default=is_default,
        **extra,
    )


@pytest.fixture(name="mock_project_service")
def fixture_mock_project_service():
    return AsyncMock(spec=ProjectService)


@pytest.fixture(name="mock_agent_service")
def fixture_mock_agent_service():
    return AsyncMock(spec=AgentService)


@pytest.fixture(autouse=True)
def _override_services(mock_project_service, mock_agent_service):
    app.dependency_overrides[ProjectService] = lambda: mock_project_service
    app.dependency_overrides[AgentService] = lambda: mock_agent_service
    yield
    app.dependency_overrides.pop(ProjectService, None)
    app.dependency_overrides.pop(AgentService, None)


class TestListProjects:
    """GET /api/projects."""

    def test_lists_the_callers_projects(self, api_client, mock_project_service):
        mock_project_service.list_projects.return_value = [
            _project(1, is_default=True),
            _project(7, session_count=2, latest_session_id="s9"),
        ]

        res = api_client.get("/api/projects", params={"workspace_id": 10})

        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        assert [p["id"] for p in body] == [1, 7]
        assert body[0]["is_default"] is True
        assert body[1]["latest_session_id"] == "s9"
        user, workspace_id = mock_project_service.list_projects.await_args.args
        assert (user.id, workspace_id) == (1, 10)

    def test_workspace_id_is_required(self, api_client, mock_project_service):
        res = api_client.get("/api/projects")

        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_project_service.list_projects.assert_not_called()


class TestCreateProject:
    """POST /api/projects."""

    def test_creates_a_project_with_a_trimmed_name(
        self, api_client, mock_project_service
    ):
        mock_project_service.create_project.return_value = _project()

        res = api_client.post(
            "/api/projects", json={"workspace_id": 10, "name": "  Launch  "}
        )

        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["name"] == "Launch"
        user, dto = mock_project_service.create_project.await_args.args
        assert user.id == 1
        assert (dto.workspace_id, dto.name) == (10, "Launch")

    @pytest.mark.parametrize("name", ["", "   ", "x" * 121])
    def test_rejects_an_invalid_name(
        self, api_client, mock_project_service, name
    ):
        res = api_client.post(
            "/api/projects", json={"workspace_id": 10, "name": name}
        )

        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_project_service.create_project.assert_not_called()


class TestLiteralRoutes:
    """The literal ``/default`` and ``/resolve`` routes beat ``/{id}``."""

    def test_ensure_default(self, api_client, mock_project_service):
        mock_project_service.ensure_default_project.return_value = _project(
            1, is_default=True
        )

        res = api_client.post(
            "/api/projects/default", params={"workspace_id": 10}, json={}
        )

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["is_default"] is True
        user, workspace_id = (
            mock_project_service.ensure_default_project.await_args.args
        )
        assert (user.id, workspace_id) == (1, 10)
        mock_project_service.get_project.assert_not_called()

    @pytest.mark.parametrize(
        "params, expected",
        [
            (
                {"session_id": "s1"},
                {
                    "session_id": "s1",
                    "storyboard_id": None,
                    "timeline_id": None,
                },
            ),
            (
                {"storyboard_id": 14},
                {"session_id": None, "storyboard_id": 14, "timeline_id": None},
            ),
            (
                {"timeline_id": 3},
                {"session_id": None, "storyboard_id": None, "timeline_id": 3},
            ),
        ],
    )
    def test_resolve_forwards_the_child_id(
        self, api_client, mock_project_service, params, expected
    ):
        mock_project_service.resolve_project_from_child.return_value = (
            _project()
        )

        res = api_client.get("/api/projects/resolve", params=params)

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["id"] == 7
        call = mock_project_service.resolve_project_from_child.await_args
        assert call.args[0].id == 1
        assert call.kwargs == expected
        mock_project_service.get_project.assert_not_called()

    def test_resolve_propagates_not_found(
        self, api_client, mock_project_service
    ):
        mock_project_service.resolve_project_from_child.side_effect = (
            HTTPException(status_code=404, detail="Timeline not found")
        )

        res = api_client.get("/api/projects/resolve", params={"timeline_id": 3})

        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.json()["detail"] == "Timeline not found"


class TestGetAndRenameProject:
    """GET and PATCH /api/projects/{id}."""

    def test_get_returns_fresh_pointers(self, api_client, mock_project_service):
        mock_project_service.get_project.return_value = _project(
            latest_session_id=None, latest_timeline_id=42
        )

        res = api_client.get("/api/projects/7")

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["latest_timeline_id"] == 42
        user, project_id = mock_project_service.get_project.await_args.args
        assert (user.id, project_id) == (1, 7)

    def test_get_forbidden_for_another_owner(
        self, api_client, mock_project_service
    ):
        mock_project_service.get_project.side_effect = HTTPException(
            status_code=403, detail="Not your project"
        )

        res = api_client.get("/api/projects/7")

        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_rename(self, api_client, mock_project_service):
        mock_project_service.rename_project.return_value = _project()

        res = api_client.patch("/api/projects/7", json={"name": " Spring "})

        assert res.status_code == status.HTTP_200_OK
        user, project_id, name = (
            mock_project_service.rename_project.await_args.args
        )
        assert (user.id, project_id, name) == (1, 7, "Spring")

    def test_rename_rejects_a_blank_name(
        self, api_client, mock_project_service
    ):
        res = api_client.patch("/api/projects/7", json={"name": "  "})

        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_project_service.rename_project.assert_not_called()


class TestDeleteProject:
    """DELETE /api/projects/{id}."""

    def test_deletes_sessions_then_the_project(
        self, api_client, mock_project_service, mock_agent_service
    ):
        calls = []
        sessions = {"s1": "ads_x", "s2": "brand_x"}
        mock_project_service.prepare_project_delete.side_effect = (
            lambda user, project_id: calls.append(
                ("prepare", user.id, project_id)
            )
            or sessions
        )
        mock_agent_service.ensure_sessions_idle.side_effect = (
            lambda ids: calls.append(("idle", ids))
        )
        mock_agent_service.delete_sessions_best_effort.side_effect = (
            lambda user, chats: calls.append(("sessions", user.id, chats)) or []
        )
        mock_project_service.delete_project.side_effect = (
            lambda user, project_id: calls.append(
                ("project", user.id, project_id)
            )
        )

        res = api_client.delete("/api/projects/7")

        assert res.status_code == status.HTTP_204_NO_CONTENT
        assert calls == [
            ("prepare", 1, 7),
            ("idle", ["s1", "s2"]),
            ("sessions", 1, sessions),
            ("project", 1, 7),
        ]
        # Authorization lives in the service steps: no summary query.
        mock_project_service.get_project.assert_not_called()

    def test_the_default_project_is_refused_and_left_intact(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.prepare_project_delete.side_effect = HTTPException(
            status_code=409, detail=DEFAULT_PROJECT_DELETE_DETAIL
        )

        res = api_client.delete("/api/projects/1")

        assert res.status_code == status.HTTP_409_CONFLICT
        assert res.json()["detail"] == DEFAULT_PROJECT_DELETE_DETAIL
        mock_agent_service.ensure_sessions_idle.assert_not_called()
        mock_agent_service.delete_sessions_best_effort.assert_not_called()
        mock_project_service.delete_project.assert_not_called()

    def test_busy_project_is_refused_and_left_intact(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.prepare_project_delete.return_value = {
            "s1": "ads_x"
        }
        mock_agent_service.ensure_sessions_idle.side_effect = HTTPException(
            status_code=409, detail=BUSY_DETAIL
        )

        res = api_client.delete("/api/projects/7")

        assert res.status_code == status.HTTP_409_CONFLICT
        assert res.json()["detail"] == BUSY_DETAIL
        mock_agent_service.delete_sessions_best_effort.assert_not_called()
        mock_project_service.delete_project.assert_not_called()

    def test_unauthorized_delete_touches_nothing(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.prepare_project_delete.side_effect = HTTPException(
            status_code=403, detail="Not your project"
        )

        res = api_client.delete("/api/projects/7")

        assert res.status_code == status.HTTP_403_FORBIDDEN
        mock_agent_service.ensure_sessions_idle.assert_not_called()
        mock_agent_service.delete_sessions_best_effort.assert_not_called()
        mock_project_service.delete_project.assert_not_called()

    def test_undeletable_sessions_do_not_block_the_delete(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.prepare_project_delete.return_value = {
            "s1": "ads_x"
        }
        mock_agent_service.delete_sessions_best_effort.return_value = ["s1"]

        res = api_client.delete("/api/projects/7")

        assert res.status_code == status.HTTP_204_NO_CONTENT
        user, project_id = mock_project_service.delete_project.await_args.args
        assert (user.id, project_id) == (1, 7)
