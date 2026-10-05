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

"""ProjectService: session-scoped reuse and scene identity persistence."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.projects.dto.project_dto import (
    SceneDTO,
    StoryboardCreate,
    StoryboardCreateResponse,
    StoryboardResponse,
    StoryboardUpdate,
)
from src.projects.project_service import ProjectService


@pytest.fixture(name="repo")
def fixture_repo():
    return AsyncMock()


@pytest.fixture(name="service")
def fixture_service(repo):
    media_repo = AsyncMock()
    media_repo.get_by_id.return_value = None
    return ProjectService(
        storyboard_repo=repo,
        media_repo=media_repo,
        iam_signer_credentials=MagicMock(),
    )


def _create(session_id="s1", **extra):
    return StoryboardCreate(
        workspace_id=10,
        session_id=session_id,
        template_name="Feature Spotlight",
        **extra,
    )


def _existing(storyboard_id=14):
    return StoryboardCreateResponse(
        id=storyboard_id,
        user_id=1,
        workspace_id=10,
        session_id="s1",
        template_name="Custom",
    )


class TestCreateStoryboard:
    @pytest.mark.anyio
    async def test_plain_create(self, service, repo):
        repo.create.return_value = _existing(1)
        res = await service.create_storyboard(_create(), user_id=1)
        assert res.id == 1
        repo.find_latest_by_session.assert_not_called()
        data = repo.create.await_args.args[0]
        assert data["user_id"] == 1
        assert data["session_id"] == "s1"

    @pytest.mark.anyio
    async def test_reuse_returns_existing_session_record(self, service, repo):
        repo.find_latest_by_session.return_value = _existing(14)
        res = await service.create_storyboard(
            _create(bg_music_description="warm pads"),
            user_id=1,
            reuse_session_record=True,
        )
        assert res.id == 14
        # Scalars from the new payload are refreshed on the kept record.
        repo.update.assert_awaited_once_with(
            14,
            {
                "template_name": "Feature Spotlight",
                "bg_music_description": "warm pads",
            },
        )
        assert res.template_name == "Feature Spotlight"
        assert res.bg_music_description == "warm pads"
        repo.create.assert_not_called()
        repo.find_latest_by_session.assert_awaited_once_with(10, "s1", 1)

    @pytest.mark.anyio
    async def test_reuse_without_scalars_does_not_touch_record(
        self, service, repo
    ):
        repo.find_latest_by_session.return_value = _existing(14)
        res = await service.create_storyboard(
            StoryboardCreate(workspace_id=10, session_id="s1"),
            user_id=1,
            reuse_session_record=True,
        )
        assert res.id == 14
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_reuse_creates_when_session_has_none(self, service, repo):
        repo.find_latest_by_session.return_value = None
        repo.create.return_value = _existing(15)
        res = await service.create_storyboard(
            _create(), user_id=1, reuse_session_record=True
        )
        assert res.id == 15
        repo.create.assert_awaited_once()

    @pytest.mark.anyio
    async def test_reuse_requires_session_id(self, service, repo):
        repo.create.return_value = _existing(16)
        await service.create_storyboard(
            _create(session_id=None), user_id=1, reuse_session_record=True
        )
        repo.find_latest_by_session.assert_not_called()
        repo.create.assert_awaited_once()


class TestUpdateStoryboard:
    @pytest.mark.anyio
    async def test_scene_identity_and_order_are_persisted(self, service, repo):
        repo.get_by_id_with_details.return_value = StoryboardResponse(
            id=14, user_id=1, workspace_id=10
        )
        repo.update_storyboard_data.return_value = StoryboardResponse(
            id=14,
            user_id=1,
            workspace_id=10,
            scenes=[
                SceneDTO(scene_id="b", order=0),
                SceneDTO(scene_id="a", order=1),
            ],
        )

        update = StoryboardUpdate(
            scenes=[
                {
                    "scene_id": "b",
                    "topic": "Second first",
                    "first_frame_prompt": {
                        "media_item_id": 999,
                        "description": "x",
                    },
                },
                {"scene_id": "", "topic": "No id"},
                {"topic": "Missing id"},
            ]
        )
        res = await service.update_storyboard(14, update)

        assert [s.scene_id for s in res.scenes] == ["b", "a"]
        scenes = repo.update_storyboard_data.await_args.kwargs["scenes"]
        assert [s.scene_id for s in scenes] == ["b", None, None]
        assert [s.order for s in scenes] == [0, 1, 2]
        assert scenes[0].first_frame_media_item_id == 999
        assert scenes[0].first_frame_description == "x"

    @pytest.mark.anyio
    async def test_update_without_scene_payload_returns_refreshed(
        self, service, repo
    ):
        repo.get_by_id_with_details.return_value = StoryboardResponse(
            id=14, user_id=1, workspace_id=10
        )
        res = await service.update_storyboard(
            14, StoryboardUpdate(template_name="Custom")
        )
        assert res.id == 14
        repo.update.assert_awaited_once_with(14, {"template_name": "Custom"})
        repo.update_storyboard_data.assert_not_called()

    @pytest.mark.anyio
    async def test_update_missing_storyboard(self, service, repo):
        repo.get_by_id_with_details.return_value = None
        assert await service.update_storyboard(99, StoryboardUpdate()) is None


class TestAssignSceneIds:
    @pytest.mark.anyio
    async def test_writes_only_rows_whose_identity_differs(self, service, repo):
        scenes = [
            SceneDTO(id=140, scene_id=None, order=0),
            SceneDTO(id=141, scene_id="scene-02-mist", order=1),
            SceneDTO(id=142, scene_id="stale", order=2),
        ]
        written = await service.assign_scene_ids(
            14, scenes, ["scene-01-hook", "scene-02-mist", "scene-03-sillage"]
        )
        assert written == {140: "scene-01-hook", 142: "scene-03-sillage"}
        repo.set_scene_ids.assert_awaited_once_with(14, written)
        # The DTOs the response is built from now carry the ids.
        assert [s.scene_id for s in scenes] == [
            "scene-01-hook",
            "scene-02-mist",
            "scene-03-sillage",
        ]

    @pytest.mark.anyio
    async def test_length_mismatch_writes_nothing(self, service, repo):
        scenes = [SceneDTO(id=140), SceneDTO(id=141)]
        assert await service.assign_scene_ids(14, scenes, ["a"]) == {}
        repo.set_scene_ids.assert_not_called()
        assert scenes[0].scene_id is None

    @pytest.mark.anyio
    async def test_nothing_to_do_skips_the_repository(self, service, repo):
        scenes = [
            SceneDTO(id=140, scene_id="a"),
            SceneDTO(id=None),
            SceneDTO(id=142),
        ]
        assert await service.assign_scene_ids(14, scenes, ["a", "b", ""]) == {}
        repo.set_scene_ids.assert_not_called()
        # No db id and a blank identity are both skipped, not errors.
        assert scenes[1].scene_id is None
        assert scenes[2].scene_id is None
