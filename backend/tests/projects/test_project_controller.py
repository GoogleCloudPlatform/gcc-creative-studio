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

"""Storyboard controller: by-id authorization, agent/human create and update."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from main import app
from src.agents.agent_service import AgentService
from src.common.request_context import is_agent_request
from src.projects.dto.project_dto import (
    SceneDTO,
    StoryboardCreateResponse,
    StoryboardResponse,
)
from src.projects.project_service import ProjectService


def _storyboard(storyboard_id=14, user_id=1, session_id="s1"):
    return StoryboardResponse(
        id=storyboard_id,
        user_id=user_id,
        workspace_id=10,
        session_id=session_id,
        scenes=[SceneDTO(id=1, scene_id="a", order=0, topic="Hook")],
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


@pytest.fixture(name="as_agent")
def fixture_as_agent():
    """Marks the request as coming from the Izumi agent (auth guard does this)."""
    token = is_agent_request.set(True)
    yield
    is_agent_request.reset(token)


class TestListStoryboards:
    """GET /api/storyboards is scoped to the caller."""

    def test_lists_only_the_callers_storyboards(
        self, api_client, mock_project_service
    ):
        mock_project_service.list_storyboards_for_user.return_value = [
            _storyboard()
        ]

        res = api_client.get(
            "/api/storyboards", params={"workspace_id": 10, "session_id": "s1"}
        )

        assert res.status_code == status.HTTP_200_OK
        assert [s["id"] for s in res.json()] == [14]
        user, workspace_id, session_id = (
            mock_project_service.list_storyboards_for_user.await_args.args
        )
        assert (user.id, workspace_id, session_id) == (1, 10, "s1")


class TestCreateStoryboard:
    def test_human_create_never_reuses(self, api_client, mock_project_service):
        mock_project_service.create_storyboard.return_value = (
            StoryboardCreateResponse(id=1, user_id=1, workspace_id=10)
        )
        res = api_client.post(
            "/api/storyboards/", json={"workspace_id": 10, "session_id": "s1"}
        )
        assert res.status_code == status.HTTP_201_CREATED
        kwargs = mock_project_service.create_storyboard.await_args.kwargs
        assert kwargs["reuse_session_record"] is False

    def test_agent_create_reuses_session_record(
        self, api_client, mock_project_service, as_agent
    ):
        mock_project_service.create_storyboard.return_value = (
            StoryboardCreateResponse(id=1, user_id=1, workspace_id=10)
        )
        res = api_client.post(
            "/api/storyboards/", json={"workspace_id": 10, "session_id": "s1"}
        )
        assert res.status_code == status.HTTP_201_CREATED
        kwargs = mock_project_service.create_storyboard.await_args.kwargs
        assert kwargs["reuse_session_record"] is True


class TestStoryboardById:
    """GET and DELETE /api/storyboards/{id} authorize before anything else."""

    def test_get_authorizes_before_loading(
        self, api_client, mock_project_service
    ):
        calls = []
        mock_project_service.authorize_storyboard.side_effect = (
            lambda user, storyboard_id: calls.append(
                ("authorize", user.id, storyboard_id)
            )
        )
        mock_project_service.get_storyboard.side_effect = (
            lambda storyboard_id: calls.append(("load", storyboard_id))
            or _storyboard()
        )

        res = api_client.get("/api/storyboards/14")

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["id"] == 14
        assert calls == [("authorize", 1, 14), ("load", 14)]

    @pytest.mark.parametrize("code", [403, 404])
    def test_a_refused_get_presigns_nothing(
        self, api_client, mock_project_service, code
    ):
        mock_project_service.authorize_storyboard.side_effect = HTTPException(
            status_code=code, detail="Refused"
        )

        res = api_client.get("/api/storyboards/14")

        assert res.status_code == code
        mock_project_service.get_storyboard.assert_not_called()

    def test_get_of_a_storyboard_gone_since_authorization_is_404(
        self, api_client, mock_project_service
    ):
        mock_project_service.get_storyboard.return_value = None

        res = api_client.get("/api/storyboards/14")

        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_authorizes_then_deletes(
        self, api_client, mock_project_service
    ):
        res = api_client.delete("/api/storyboards/14")

        assert res.status_code == status.HTTP_204_NO_CONTENT
        user, storyboard_id = (
            mock_project_service.authorize_storyboard.await_args.args
        )
        assert (user.id, storyboard_id) == (1, 14)
        mock_project_service.delete_storyboard.assert_awaited_once_with(14)
        mock_project_service.get_storyboard.assert_not_called()

    def test_a_refused_delete_deletes_nothing(
        self, api_client, mock_project_service
    ):
        mock_project_service.authorize_storyboard.side_effect = HTTPException(
            status_code=403, detail="Not authorized to use this storyboard"
        )

        res = api_client.delete("/api/storyboards/14")

        assert res.status_code == status.HTTP_403_FORBIDDEN
        mock_project_service.delete_storyboard.assert_not_called()


class TestUpdateStoryboard:
    def test_human_update_is_mirrored_to_agent(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.update_storyboard.return_value = _storyboard()
        mock_agent_service.sync_storyboard_to_session.return_value = {
            "status": "synced",
            "matched": 1,
            "frames_replaced": ["a"],
        }

        res = api_client.put(
            "/api/storyboards/14", json={"scenes": [{"scene_id": "a"}]}
        )

        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        assert body["id"] == 14
        assert body["scenes"][0]["scene_id"] == "a"
        assert body["scenes"][0]["order"] == 0
        assert body["agent_sync"]["status"] == "synced"
        mock_agent_service.sync_storyboard_to_session.assert_awaited_once()
        user, sent = (
            mock_agent_service.sync_storyboard_to_session.await_args.args
        )
        assert user.id == 1
        assert sent.id == 14
        user, storyboard_id = (
            mock_project_service.authorize_storyboard.await_args.args
        )
        assert (user.id, storyboard_id) == (1, 14)
        # Authorized without loading (and presigning) the storyboard first.
        mock_project_service.get_storyboard.assert_not_called()

    def test_agent_update_is_not_mirrored_back(
        self, api_client, mock_project_service, mock_agent_service, as_agent
    ):
        mock_project_service.update_storyboard.return_value = _storyboard()

        res = api_client.put("/api/storyboards/14", json={"scenes": []})

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["agent_sync"] is None
        mock_agent_service.sync_storyboard_to_session.assert_not_called()
        mock_project_service.assign_scene_ids.assert_not_called()

    def test_synced_scene_ids_are_persisted_and_returned(
        self, api_client, mock_project_service, mock_agent_service
    ):
        legacy = _storyboard()
        legacy.scenes = [SceneDTO(id=140, scene_id=None, order=0, topic="Hook")]
        mock_project_service.update_storyboard.return_value = legacy
        mock_agent_service.sync_storyboard_to_session.return_value = {
            "status": "synced",
            "matched": 1,
            "scene_ids": ["scene-01-hook"],
        }

        async def _assign(storyboard_id, scenes, scene_ids):
            for scene, scene_id in zip(scenes, scene_ids):
                scene.scene_id = scene_id
            return {140: "scene-01-hook"}

        mock_project_service.assign_scene_ids.side_effect = _assign

        res = api_client.put(
            "/api/storyboards/14", json={"scenes": [{"topic": "Hook"}]}
        )

        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        assert body["scenes"][0]["scene_id"] == "scene-01-hook"
        assert body["agent_sync"]["scene_ids"] == ["scene-01-hook"]
        args = mock_project_service.assign_scene_ids.await_args.args
        assert args[0] == 14
        assert [s.id for s in args[1]] == [140]
        assert args[2] == ["scene-01-hook"]

    @pytest.mark.parametrize(
        "sync",
        [
            {"status": "busy", "scene_ids": ["a"]},
            {"status": "skipped", "detail": "Session not found."},
            {"status": "synced", "scene_ids": []},
            {"status": "synced"},
        ],
    )
    def test_ids_are_only_persisted_after_a_real_sync(
        self, api_client, mock_project_service, mock_agent_service, sync
    ):
        mock_project_service.update_storyboard.return_value = _storyboard()
        mock_agent_service.sync_storyboard_to_session.return_value = sync

        res = api_client.put("/api/storyboards/14", json={"scenes": []})

        assert res.status_code == status.HTTP_200_OK
        mock_project_service.assign_scene_ids.assert_not_called()

    def test_failed_id_write_does_not_fail_the_edit(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.update_storyboard.return_value = _storyboard()
        mock_agent_service.sync_storyboard_to_session.return_value = {
            "status": "synced",
            "scene_ids": ["a"],
        }
        mock_project_service.assign_scene_ids.side_effect = RuntimeError(
            "db down"
        )

        res = api_client.put("/api/storyboards/14", json={"scenes": []})

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["agent_sync"]["status"] == "synced"
        mock_project_service.assign_scene_ids.assert_awaited_once()

    def test_update_not_found(self, api_client, mock_project_service):
        mock_project_service.authorize_storyboard.side_effect = HTTPException(
            status_code=404, detail="Storyboard not found"
        )
        res = api_client.put("/api/storyboards/99", json={})
        assert res.status_code == status.HTTP_404_NOT_FOUND
        mock_project_service.update_storyboard.assert_not_called()

    def test_update_forbidden_for_other_user(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.authorize_storyboard.side_effect = HTTPException(
            status_code=403, detail="Not authorized to use this storyboard"
        )
        res = api_client.put("/api/storyboards/14", json={})
        assert res.status_code == status.HTTP_403_FORBIDDEN
        mock_project_service.update_storyboard.assert_not_called()
        mock_agent_service.sync_storyboard_to_session.assert_not_called()

    def test_update_returning_nothing_is_404(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.update_storyboard.return_value = None
        res = api_client.put("/api/storyboards/14", json={})
        assert res.status_code == status.HTTP_404_NOT_FOUND
        mock_agent_service.sync_storyboard_to_session.assert_not_called()
