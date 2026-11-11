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

"""ProjectService: projects, session-scoped reuse and scene identity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.agents.agent_session_model import AgentSession
from src.projects.dto.project_dto import (
    ProjectCreate,
    ProjectResponse,
    SceneDTO,
    StoryboardCreate,
    StoryboardCreateResponse,
    StoryboardResponse,
    StoryboardUpdate,
)
from src.projects.project_service import ProjectService
from src.users.user_model import UserModel, UserRoleEnum

USER = UserModel(
    id=1, email="u1@example.com", roles=[UserRoleEnum.USER], name="User"
)


def _project(project_id=50, workspace_id=10, owner_id=1, **extra):
    return ProjectResponse(
        id=project_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        name="Default project",
        is_default=True,
        **extra,
    )


def _registry_row(session_id="s1", project_id=60, user_id=1, workspace_id=10):
    return AgentSession(
        session_id=session_id,
        project_id=project_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )


@pytest.fixture(name="repo")
def fixture_repo():
    return AsyncMock()


@pytest.fixture(name="project_repo")
def fixture_project_repo():
    project_repo = AsyncMock()
    project_repo.ensure_default.return_value = _project(50)
    project_repo.get_summary.side_effect = lambda project_id: _project(
        project_id, session_count=2, latest_session_id="s9"
    )
    return project_repo


@pytest.fixture(name="project_auth")
def fixture_project_auth():
    project_auth = AsyncMock()
    project_auth.authorize.side_effect = lambda project_id, user: _project(
        project_id
    )
    return project_auth


@pytest.fixture(name="workspace_auth")
def fixture_workspace_auth():
    return AsyncMock()


@pytest.fixture(name="registry")
def fixture_registry():
    registry = AsyncMock()
    registry.get.return_value = None
    return registry


@pytest.fixture(name="service")
def fixture_service(repo, project_repo, project_auth, workspace_auth, registry):
    media_repo = AsyncMock()
    media_repo.get_by_id.return_value = None
    return ProjectService(
        storyboard_repo=repo,
        media_repo=media_repo,
        iam_signer_credentials=MagicMock(),
        project_repo=project_repo,
        project_auth=project_auth,
        workspace_auth=workspace_auth,
        agent_session_repo=registry,
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
    async def test_plain_create(self, service, repo, registry):
        repo.create.return_value = _existing(1)
        res = await service.create_storyboard(_create(), user=USER)
        assert res.id == 1
        repo.find_latest_by_session.assert_not_called()
        data = repo.create.await_args.args[0]
        assert data["user_id"] == 1
        assert data["session_id"] == "s1"
        # Unknown chat: default project. The client-sent id is NOT adopted:
        # it proves no ownership (the user-scoped listing adopts it).
        assert data["project_id"] == 50
        registry.adopt.assert_not_called()

    @pytest.mark.anyio
    async def test_create_for_a_registered_chat_uses_its_project(
        self, service, repo, registry, project_repo
    ):
        registry.get.return_value = _registry_row(project_id=60)
        repo.create.return_value = _existing(2)

        await service.create_storyboard(_create(), user=USER)

        assert repo.create.await_args.args[0]["project_id"] == 60
        project_repo.ensure_default.assert_not_called()
        registry.adopt.assert_not_called()

    @pytest.mark.anyio
    async def test_reuse_returns_existing_session_record(self, service, repo):
        repo.find_latest_by_session.return_value = _existing(14)
        res = await service.create_storyboard(
            _create(bg_music_description="warm pads"),
            user=USER,
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
            user=USER,
            reuse_session_record=True,
        )
        assert res.id == 14
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_reuse_creates_when_session_has_none(self, service, repo):
        repo.find_latest_by_session.return_value = None
        repo.create.return_value = _existing(15)
        res = await service.create_storyboard(
            _create(), user=USER, reuse_session_record=True
        )
        assert res.id == 15
        repo.create.assert_awaited_once()

    @pytest.mark.anyio
    async def test_reuse_requires_session_id(self, service, repo):
        repo.create.return_value = _existing(16)
        await service.create_storyboard(
            _create(session_id=None), user=USER, reuse_session_record=True
        )
        repo.find_latest_by_session.assert_not_called()
        repo.create.assert_awaited_once()


class TestProjects:
    """Project CRUD: authorization first, then the repository."""

    @pytest.mark.anyio
    async def test_list_projects_authorizes_the_workspace(
        self, service, project_repo, workspace_auth
    ):
        project_repo.list_for_owner.return_value = [_project(1)]

        projects = await service.list_projects(USER, 10)

        assert [p.id for p in projects] == [1]
        workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=USER
        )
        project_repo.list_for_owner.assert_awaited_once_with(10, 1)

    @pytest.mark.anyio
    async def test_ensure_default_returns_the_summary(
        self, service, project_repo
    ):
        project = await service.ensure_default_project(USER, 10)

        project_repo.ensure_default.assert_awaited_once_with(10, 1)
        assert project.id == 50
        assert project.latest_session_id == "s9"

    @pytest.mark.anyio
    async def test_create_project(self, service, project_repo, workspace_auth):
        project_repo.create_project.return_value = _project(7)

        project = await service.create_project(
            USER, ProjectCreate(workspace_id=10, name="  Spring  ")
        )

        assert project.id == 7
        workspace_auth.authorize.assert_awaited_once()
        project_repo.create_project.assert_awaited_once_with(10, 1, "Spring")

    @pytest.mark.anyio
    async def test_get_project_authorizes_then_summarizes(
        self, service, project_auth
    ):
        project = await service.get_project(USER, 7)

        project_auth.authorize.assert_awaited_once_with(7, USER)
        assert project.session_count == 2

    @pytest.mark.anyio
    async def test_get_project_vanished_after_authorization(
        self, service, project_repo
    ):
        project_repo.get_summary.side_effect = None
        project_repo.get_summary.return_value = None

        with pytest.raises(HTTPException) as exc:
            await service.get_project(USER, 7)
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_rename_project(self, service, project_auth, project_repo):
        await service.rename_project(USER, 7, "Renamed")

        project_auth.authorize.assert_awaited_with(7, USER)
        project_repo.update.assert_awaited_once_with(7, {"name": "Renamed"})

    @pytest.mark.anyio
    async def test_prepare_delete_authorizes_and_lists_the_chats(
        self, service, project_auth, registry
    ):
        project_auth.authorize.side_effect = None
        project_auth.authorize.return_value = _project(7).model_copy(
            update={"name": "Launch", "is_default": False}
        )
        registry.app_names_for_project.return_value = {"s1": "ads_x"}

        assert await service.prepare_project_delete(USER, 7) == {"s1": "ads_x"}
        project_auth.authorize.assert_awaited_once_with(7, USER)
        registry.app_names_for_project.assert_awaited_once_with(7)

    @pytest.mark.anyio
    async def test_delete_authorizes_again_then_deletes(
        self, service, project_auth, project_repo
    ):
        project_auth.authorize.side_effect = None
        project_auth.authorize.return_value = _project(7).model_copy(
            update={"name": "Launch", "is_default": False}
        )

        await service.delete_project(USER, 7)

        project_auth.authorize.assert_awaited_once_with(7, USER)
        project_repo.delete.assert_awaited_once_with(7)

    @pytest.mark.anyio
    async def test_the_default_project_is_never_deleted(
        self, service, project_repo, registry
    ):
        # The fixture's ``ProjectAuth`` answers with a default project.
        with pytest.raises(HTTPException) as prepare:
            await service.prepare_project_delete(USER, 50)
        with pytest.raises(HTTPException) as delete:
            await service.delete_project(USER, 50)

        assert prepare.value.status_code == delete.value.status_code == 409
        assert prepare.value.detail == "The default project cannot be deleted."
        registry.app_names_for_project.assert_not_called()
        project_repo.delete.assert_not_called()

    @pytest.mark.anyio
    async def test_a_foreign_project_is_refused_by_project_auth(
        self, service, project_auth, project_repo, registry
    ):
        project_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="Not your project"
        )

        for step in (service.prepare_project_delete, service.delete_project):
            with pytest.raises(HTTPException) as exc:
                await step(USER, 7)
            assert exc.value.status_code == 403
        registry.app_names_for_project.assert_not_called()
        project_repo.delete.assert_not_called()


class TestResolveProjectFromChild:
    """Deep links: the project of a chat, storyboard or timeline."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"session_id": "s1", "storyboard_id": 3}, {"session_id": ""}],
    )
    async def test_exactly_one_id_is_required(self, service, kwargs):
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_from_child(USER, **kwargs)
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_session(self, service, registry):
        registry.get.return_value = _registry_row(project_id=60)
        project = await service.resolve_project_from_child(
            USER, session_id="s1"
        )
        assert project.id == 60

    @pytest.mark.anyio
    async def test_unknown_session_is_404(self, service):
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_from_child(USER, session_id="nope")
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_foreign_session_is_403(self, service, registry):
        registry.get.return_value = _registry_row(user_id=2)
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_from_child(USER, session_id="s1")
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_storyboard(self, service, repo):
        repo.get_owner_and_project.return_value = (1, 61)
        project = await service.resolve_project_from_child(
            USER, storyboard_id=3
        )
        assert project.id == 61

    @pytest.mark.anyio
    @pytest.mark.parametrize("owner, status", [(None, 404), ((2, 61), 403)])
    async def test_storyboard_refusals(self, service, repo, owner, status):
        repo.get_owner_and_project.return_value = owner
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_from_child(USER, storyboard_id=3)
        assert exc.value.status_code == status

    @pytest.mark.anyio
    async def test_timeline(self, service, project_repo):
        project_repo.get_timeline_project.return_value = (True, 62)
        project = await service.resolve_project_from_child(USER, timeline_id=4)
        assert project.id == 62

    @pytest.mark.anyio
    @pytest.mark.parametrize("found", [(False, None), (True, None)])
    async def test_unresolvable_timeline_is_404(
        self, service, project_repo, found
    ):
        project_repo.get_timeline_project.return_value = found
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_from_child(USER, timeline_id=4)
        assert exc.value.status_code == 404


class TestResolveProjectForWrite:
    """Which project a new storyboard, timeline or chat belongs to."""

    @pytest.mark.anyio
    async def test_storyboard_wins_over_everything(
        self, service, repo, registry
    ):
        repo.get_owner_and_project.return_value = (1, 61)

        project = await service.resolve_project_for_write(
            USER, 10, project_id=99, storyboard_id=3, session_id="s1"
        )

        assert project.id == 61
        registry.get.assert_not_called()

    @pytest.mark.anyio
    @pytest.mark.parametrize("owner, status", [(None, 404), ((2, 61), 403)])
    async def test_storyboard_refusals(
        self, service, repo, project_auth, owner, status
    ):
        repo.get_owner_and_project.return_value = owner

        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_for_write(USER, 10, storyboard_id=3)

        assert exc.value.status_code == status
        project_auth.authorize.assert_not_called()

    @pytest.mark.anyio
    async def test_explicit_project(self, service):
        project = await service.resolve_project_for_write(
            USER, 10, project_id=70
        )
        assert project.id == 70

    @pytest.mark.anyio
    async def test_explicit_project_from_another_workspace_is_400(
        self, service
    ):
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_for_write(USER, 11, project_id=70)
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_explicit_project_without_workspace(self, service):
        project = await service.resolve_project_for_write(
            USER, None, project_id=70
        )
        assert project.workspace_id == 10

    @pytest.mark.anyio
    async def test_no_hint_needs_a_workspace(self, service):
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_for_write(USER, None)
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_registered_chat_of_another_user_is_403(
        self, service, registry
    ):
        registry.get.return_value = _registry_row(user_id=2)
        with pytest.raises(HTTPException) as exc:
            await service.resolve_project_for_write(USER, 10, session_id="s1")
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_chat_registered_in_another_workspace_falls_back(
        self, service, registry, project_repo
    ):
        registry.get.return_value = _registry_row(workspace_id=99)

        project = await service.resolve_project_for_write(
            USER, 10, session_id="s1"
        )

        assert project.id == 50
        project_repo.ensure_default.assert_awaited_once_with(10, 1)

    @pytest.mark.anyio
    async def test_default_without_session_adopts_nothing(
        self, service, registry, workspace_auth
    ):
        project = await service.resolve_project_for_write(USER, 10)

        assert project.id == 50
        workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=USER
        )
        registry.adopt.assert_not_called()

    @pytest.mark.anyio
    async def test_unregistered_chat_is_never_adopted(
        self, service, registry, project_repo
    ):
        # Registering a client-sent id would let any caller claim, then
        # delete, another user's chat that the registry does not know yet.
        registry.get.return_value = None

        project = await service.resolve_project_for_write(
            USER, 10, session_id="someone-elses-chat"
        )

        assert project.id == 50
        project_repo.ensure_default.assert_awaited_once_with(10, 1)
        registry.adopt.assert_not_called()


class TestListStoryboardsForUser:
    """The storyboard list is authorized and filtered by owner."""

    @pytest.mark.anyio
    async def test_authorizes_and_filters_by_owner(
        self, service, repo, workspace_auth
    ):
        repo.find_by_workspace.return_value = []

        await service.list_storyboards_for_user(USER, 10, "s1")

        workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=USER
        )
        repo.find_by_workspace.assert_awaited_once_with(10, "s1", 1)

    @pytest.mark.anyio
    async def test_foreign_workspace_is_refused(self, service, workspace_auth):
        workspace_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="no"
        )
        with pytest.raises(HTTPException):
            await service.list_storyboards_for_user(USER, 10)


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
