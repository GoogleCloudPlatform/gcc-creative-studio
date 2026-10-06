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

"""Storyboard controller: agent/human routing of create and update."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status

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


class TestUpdateStoryboard:
    def test_human_update_is_mirrored_to_agent(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.get_storyboard.return_value = _storyboard()
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

    def test_agent_update_is_not_mirrored_back(
        self, api_client, mock_project_service, mock_agent_service, as_agent
    ):
        mock_project_service.get_storyboard.return_value = _storyboard()
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
        mock_project_service.get_storyboard.return_value = legacy
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
        mock_project_service.get_storyboard.return_value = _storyboard()
        mock_project_service.update_storyboard.return_value = _storyboard()
        mock_agent_service.sync_storyboard_to_session.return_value = sync

        res = api_client.put("/api/storyboards/14", json={"scenes": []})

        assert res.status_code == status.HTTP_200_OK
        mock_project_service.assign_scene_ids.assert_not_called()

    def test_failed_id_write_does_not_fail_the_edit(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.get_storyboard.return_value = _storyboard()
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
        mock_project_service.get_storyboard.return_value = None
        res = api_client.put("/api/storyboards/99", json={})
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_update_forbidden_for_other_user(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.get_storyboard.return_value = _storyboard(
            user_id=2
        )
        res = api_client.put("/api/storyboards/14", json={})
        assert res.status_code == status.HTTP_403_FORBIDDEN
        mock_agent_service.sync_storyboard_to_session.assert_not_called()

    def test_update_returning_nothing_is_404(
        self, api_client, mock_project_service, mock_agent_service
    ):
        mock_project_service.get_storyboard.return_value = _storyboard()
        mock_project_service.update_storyboard.return_value = None
        res = api_client.put("/api/storyboards/14", json={})
        assert res.status_code == status.HTTP_404_NOT_FOUND
        mock_agent_service.sync_storyboard_to_session.assert_not_called()
