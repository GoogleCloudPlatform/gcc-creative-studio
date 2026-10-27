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

"""AgentService and the chat -> project registry (``agent_sessions``)."""

# White-box tests: they drive the private registry helpers and stub the
# private agent transport (``_sessions_*``).
# pylint: disable=protected-access

import asyncio
import datetime
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors

from src.agents import agent_service as module
from src.agents.agent_dtos import SessionResponseDto
from src.agents.agent_service import AgentService
from src.agents.agent_session_repository import AgentSessionRepository
from src.projects.dto.project_dto import ProjectResponse
from src.projects.project_service import ProjectService
from src.users.user_model import UserModel

USER = UserModel(id=7, email="owner@example.com", name="Owner", roles=["user"])


def _project(project_id=5, workspace_id=10, is_default=False):
    return ProjectResponse(
        id=project_id,
        workspace_id=workspace_id,
        owner_id=USER.id,
        name="Default project" if is_default else "Launch",
        is_default=is_default,
    )


def _row(
    session_id,
    project_id=5,
    user_id=USER.id,
    title=None,
    summary=None,
    last_used_at=None,
    app_name="ads_x",
    restored_at=None,
):
    return SimpleNamespace(
        session_id=session_id,
        project_id=project_id,
        user_id=user_id,
        workspace_id=10,
        app_name=app_name,
        title=title,
        summary=summary,
        last_used_at=last_used_at,
        restored_at=restored_at,
    )


def _dto(session_id, last_update=None):
    return SessionResponseDto(
        id=session_id,
        appName="ads_x",
        userId=str(USER.id),
        lastUpdateTime=last_update,
    )


def _at(seconds):
    """The UTC datetime of an Agent Engine ``lastUpdateTime``."""
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)


def _request():
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer token"}
    return request


def _session(user_id="7", events=None, **state):
    """An agent-backend session as ``_sessions_get`` returns it."""
    return {
        "id": "s1",
        "user_id": user_id,
        "session_state": {"workspace_id": 10, **state},
        "events": events or [],
    }


@pytest.fixture(name="registry")
def fixture_registry():
    repo = AsyncMock(spec=AgentSessionRepository)
    repo.get.return_value = None
    repo.map_for_user_workspace.return_value = {}
    return repo


@pytest.fixture(name="project_service")
def fixture_project_service():
    return AsyncMock(spec=ProjectService)


@pytest.fixture(name="service")
def fixture_service(registry, project_service):
    with patch("vertexai.Client"):
        service = AgentService(
            agent_repo=MagicMock(),
            workspace_service=MagicMock(),
            storyboard_repo=AsyncMock(),
            workspace_auth=AsyncMock(),
            project_service=project_service,
            agent_session_repo=registry,
        )
    service._get_validated_agent_name = MagicMock(return_value="agent")
    return service


class TestApplySessionRegistry:
    """Adoption into the default project and the project filter."""

    @pytest.mark.anyio
    async def test_orphans_are_adopted_into_the_default_project(
        self, service, registry, project_service
    ):
        registry.map_for_user_workspace.side_effect = [
            {"s1": _row("s1", title="Launch")},
            {
                "s1": _row("s1", title="Launch"),
                "s2": _row("s2", project_id=1),
            },
        ]
        project_service.resolve_project_for_write.return_value = _project(
            1, is_default=True
        )

        result = await service._apply_session_registry(
            USER, 10, [_dto("s1"), _dto("s2")]
        )

        project_service.resolve_project_for_write.assert_awaited_once_with(
            USER, 10
        )
        registry.adopt.assert_awaited_once_with(
            ["s2"], 1, USER.id, 10, last_used={}
        )
        assert [(d.id, d.projectId, d.title) for d in result] == [
            ("s1", 5, "Launch"),
            ("s2", 1, None),
        ]

    @pytest.mark.anyio
    async def test_registered_chats_are_not_adopted_again(
        self, service, registry, project_service
    ):
        registry.map_for_user_workspace.return_value = {"s1": _row("s1")}

        result = await service._apply_session_registry(USER, 10, [_dto("s1")])

        registry.adopt.assert_not_called()
        project_service.resolve_project_for_write.assert_not_called()
        assert result[0].projectId == 5

    @pytest.mark.anyio
    async def test_project_filter_keeps_only_that_projects_chats(
        self, service, registry
    ):
        registry.map_for_user_workspace.return_value = {
            "s1": _row("s1", project_id=5),
            "s2": _row("s2", project_id=6),
        }

        result = await service._apply_session_registry(
            USER, 10, [_dto("s1"), _dto("s2")], project_id=6
        )

        assert [d.id for d in result] == ["s2"]

    @pytest.mark.anyio
    async def test_chat_registered_elsewhere_only_in_unfiltered_lists(
        self, service, project_service
    ):
        # Adoption skips a chat registered under another workspace, so it
        # stays missing from this workspace's map.
        project_service.resolve_project_for_write.return_value = _project(
            1, is_default=True
        )

        unfiltered = await service._apply_session_registry(
            USER, 10, [_dto("s9")]
        )
        filtered = await service._apply_session_registry(
            USER, 10, [_dto("s9")], project_id=1
        )

        assert [(d.id, d.projectId) for d in unfiltered] == [("s9", None)]
        assert filtered == []

    @pytest.mark.anyio
    async def test_chats_without_activity_take_the_listed_time(
        self, service, registry
    ):
        # s1: backfilled by the migration (no activity). s2: recorded by
        # chat(). s3: registered but missing from the listing (a deleted
        # chat): it keeps NULL and sorts last.
        registry.map_for_user_workspace.return_value = {
            "s1": _row("s1"),
            "s2": _row("s2", last_used_at=_at(1_780_000_000)),
            "s3": _row("s3"),
        }

        await service._apply_session_registry(
            USER,
            10,
            [_dto("s1", 1_780_100_000), _dto("s2", 1_780_200_000)],
        )

        registry.seed_last_used.assert_awaited_once_with(
            USER.id, {"s1": _at(1_780_100_000)}
        )

    @pytest.mark.anyio
    async def test_adopted_chats_keep_their_listed_time(
        self, service, registry, project_service
    ):
        registry.map_for_user_workspace.side_effect = [
            {},
            {"s1": _row("s1", project_id=1, last_used_at=_at(1_780_000_000))},
        ]
        project_service.resolve_project_for_write.return_value = _project(
            1, is_default=True
        )

        await service._apply_session_registry(
            USER, 10, [_dto("s1", 1_780_000_000)]
        )

        registry.adopt.assert_awaited_once_with(
            ["s1"], 1, USER.id, 10, last_used={"s1": _at(1_780_000_000)}
        )
        registry.seed_last_used.assert_not_called()

    @pytest.mark.anyio
    async def test_unusable_update_times_are_ignored(self, service, registry):
        registry.map_for_user_workspace.return_value = {
            sid: _row(sid) for sid in ("none", "zero", "inf", "huge")
        }

        result = await service._apply_session_registry(
            USER,
            10,
            [
                _dto("none"),
                _dto("zero", 0),
                _dto("inf", float("inf")),
                _dto("huge", 1e20),
            ],
        )

        assert len(result) == 4
        registry.seed_last_used.assert_not_called()


class TestExpiredSessions:
    """Registered chats the agent backend no longer has (``expired``)."""

    @pytest.mark.anyio
    async def test_expired_chats_are_listed_only_on_request(
        self, service, registry
    ):
        registry.map_for_user_workspace.return_value = {
            "s1": _row("s1", last_used_at=_at(1_780_000_000)),
            "gone": _row(
                "gone",
                title="Spring",
                summary="Teaser",
                last_used_at=_at(1_780_100_000),
            ),
        }

        default = await service._apply_session_registry(USER, 10, [_dto("s1")])
        listed = await service._apply_session_registry(
            USER, 10, [_dto("s1")], include_expired=True
        )

        assert [(d.id, d.expired) for d in default] == [("s1", False)]
        assert [(d.id, d.expired) for d in listed] == [
            ("s1", False),
            ("gone", True),
        ]
        gone = listed[1]
        assert (gone.projectId, gone.title, gone.summary) == (
            5,
            "Spring",
            "Teaser",
        )
        assert (gone.appName, gone.userId) == ("ads_x", str(USER.id))
        assert gone.lastUpdateTime == 1_780_100_000

    @pytest.mark.anyio
    async def test_expired_chats_come_newest_first_after_the_live_ones(
        self, service, registry
    ):
        registry.map_for_user_workspace.return_value = {
            "live": _row("live", last_used_at=_at(1_770_000_000)),
            "old": _row("old", last_used_at=_at(1_780_000_000)),
            "new": _row("new", last_used_at=_at(1_780_200_000)),
        }

        result = await service._apply_session_registry(
            USER, 10, [_dto("live")], include_expired=True
        )

        assert [d.id for d in result] == ["live", "new", "old"]

    @pytest.mark.anyio
    async def test_chats_never_seen_alive_are_not_listed(
        self, service, registry
    ):
        # The projects backfill registered the chats old storyboards named,
        # including those deleted before projects existed: no activity.
        registry.map_for_user_workspace.return_value = {
            "deleted-before-projects": _row("deleted-before-projects"),
        }

        result = await service._apply_session_registry(
            USER, 10, [], include_expired=True
        )

        assert result == []

    @pytest.mark.anyio
    async def test_expired_chats_follow_the_project_and_the_agent(
        self, service, registry
    ):
        seen = _at(1_780_000_000)
        registry.map_for_user_workspace.return_value = {
            "p5": _row("p5", project_id=5, last_used_at=seen),
            "p6": _row("p6", project_id=6, last_used_at=seen),
            "brand": _row(
                "brand", project_id=6, last_used_at=seen, app_name="brand_x"
            ),
            "no-app": _row(
                "no-app", project_id=6, last_used_at=seen, app_name=None
            ),
        }

        filtered = await service._apply_session_registry(
            USER, 10, [], project_id=6, include_expired=True
        )
        other_agent = await service._apply_session_registry(
            USER, 10, [], include_expired=True, app_name="brand_x"
        )

        assert [d.id for d in filtered] == ["p6", "no-app"]
        assert filtered[1].appName == "ads_x"  # No app name: the default.
        assert [d.id for d in other_agent] == ["brand"]

    @pytest.mark.anyio
    async def test_only_expired_chats_with_a_storyboard_are_restorable(
        self, service, registry
    ):
        seen = _at(1_780_000_000)
        registry.map_for_user_workspace.return_value = {
            "live": _row("live", last_used_at=seen),
            "with-storyboard": _row("with-storyboard", last_used_at=seen),
            "empty": _row("empty", last_used_at=seen),
        }
        lookup = service.storyboard_repo.session_ids_with_storyboards
        lookup.return_value = {"with-storyboard"}

        result = await service._apply_session_registry(
            USER, 10, [_dto("live")], include_expired=True
        )

        assert [(d.id, d.expired, d.restorable) for d in result] == [
            ("live", False, False),
            ("with-storyboard", True, True),
            ("empty", True, False),
        ]
        # One lookup for every expired chat, scoped to the caller.
        lookup.assert_awaited_once_with(USER.id, ["with-storyboard", "empty"])

    @pytest.mark.anyio
    async def test_no_storyboard_lookup_without_expired_chats(
        self, service, registry
    ):
        registry.map_for_user_workspace.return_value = {
            "live": _row("live", last_used_at=_at(1_780_000_000)),
        }

        await service._apply_session_registry(
            USER, 10, [_dto("live")], include_expired=True
        )

        service.storyboard_repo.session_ids_with_storyboards.assert_not_called()


class TestListAndCreateSessions:
    """``list_sessions`` and ``create_session`` with a project."""

    @pytest.mark.anyio
    async def test_list_by_project_uses_the_projects_workspace(
        self, service, registry, project_service
    ):
        project_service.get_project.return_value = _project(5, workspace_id=10)
        service._sessions_list = AsyncMock(
            return_value=[
                {"id": "s1", "session_state": {"workspace_id": 10}},
                {"id": "s2", "session_state": {"workspace_id": 11}},
            ]
        )
        registry.map_for_user_workspace.return_value = {"s1": _row("s1")}

        result = await service.list_sessions(
            USER, "7", _request(), project_id=5
        )

        assert [(d.id, d.projectId) for d in result] == [("s1", 5)]
        service.workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=USER
        )

    @pytest.mark.anyio
    async def test_list_can_include_expired_chats(
        self, service, registry, project_service
    ):
        project_service.get_project.return_value = _project(5, workspace_id=10)
        service._sessions_list = AsyncMock(
            return_value=[{"id": "s1", "session_state": {"workspace_id": 10}}]
        )
        registry.map_for_user_workspace.return_value = {
            "s1": _row("s1", last_used_at=_at(1_780_000_000)),
            "gone": _row("gone", last_used_at=_at(1_780_100_000)),
        }

        result = await service.list_sessions(
            USER, "7", _request(), project_id=5, include_expired=True
        )

        assert [(d.id, d.expired) for d in result] == [
            ("s1", False),
            ("gone", True),
        ]

    @pytest.mark.anyio
    async def test_list_rejects_a_project_of_another_workspace(
        self, service, project_service
    ):
        project_service.get_project.return_value = _project(5, workspace_id=11)
        service._sessions_list = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await service.list_sessions(
                USER, "7", _request(), workspace_id=10, project_id=5
            )

        assert exc.value.status_code == 400
        service._sessions_list.assert_not_called()

    @pytest.mark.anyio
    async def test_create_in_a_project_without_workspace_id(
        self, service, registry, project_service
    ):
        project_service.get_project.return_value = _project(5, workspace_id=10)
        service._sessions_create = AsyncMock(
            return_value={"id": "s-new", "session_state": {"workspace_id": 10}}
        )
        registry.register.return_value = _row("s-new", title=None)

        dto = await service.create_session(USER, "7", _request(), project_id=5)

        assert service._sessions_create.await_args.args[3]["workspace_id"] == 10
        registry.register.assert_awaited_once_with(
            "s-new", 5, USER.id, 10, "ads_x"
        )
        project_service.resolve_project_for_write.assert_not_called()
        assert dto.projectId == 5

    @pytest.mark.anyio
    async def test_refused_project_creates_no_agent_session(
        self, service, project_service
    ):
        project_service.resolve_project_for_write.side_effect = HTTPException(
            status_code=403, detail="Not your project"
        )
        service._sessions_create = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await service.create_session(
                USER, "7", _request(), workspace_id=10, project_id=99
            )

        assert exc.value.status_code == 403
        service._sessions_create.assert_not_called()


class TestDeleteSession:
    """Owner check and registry clean-up when a chat is deleted."""

    @pytest.mark.anyio
    async def test_another_users_chat_is_refused(self, service, registry):
        registry.get.return_value = _row("s1", user_id=99)
        service._sessions_delete = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await service.delete_session(USER, "s1", "7", _request())

        assert exc.value.status_code == 403
        service._sessions_delete.assert_not_called()
        registry.delete.assert_not_called()

    @pytest.mark.anyio
    async def test_own_chat_also_removes_its_registry_row(
        self, service, registry
    ):
        registry.get.return_value = _row("s1")
        service._sessions_get = AsyncMock(return_value=_session())
        service._sessions_delete = AsyncMock()

        result = await service.delete_session(USER, "s1", "7", _request())

        assert result == {"status": "success"}
        service.workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=USER
        )
        service._sessions_delete.assert_awaited_once_with(
            "agent", "ads_x", "7", "s1"
        )
        registry.delete.assert_awaited_once_with("s1")

    @pytest.mark.anyio
    async def test_a_chat_gone_from_the_agent_only_loses_its_row(
        self, service, registry
    ):
        registry.get.return_value = _row("s1")
        service._sessions_get = AsyncMock(return_value=None)
        service._sessions_delete = AsyncMock()

        result = await service.delete_session(USER, "s1", "7", _request())

        assert result == {"status": "success"}
        service._sessions_delete.assert_not_called()
        registry.delete.assert_awaited_once_with("s1")

    @pytest.mark.anyio
    async def test_an_unregistered_chat_of_another_user_is_refused(
        self, service, registry
    ):
        # Agent Engine reads sessions by id alone: only the session's own
        # owner can tell that it is not the caller's.
        service._sessions_get = AsyncMock(return_value=_session(user_id="99"))
        service._sessions_delete = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await service.delete_session(USER, "s1", "7", _request())

        assert exc.value.status_code == 403
        service._sessions_delete.assert_not_called()
        registry.delete.assert_not_called()

    @pytest.mark.anyio
    async def test_an_unreadable_chat_is_never_deleted(self, service):
        service._sessions_get = AsyncMock(side_effect=RuntimeError("boom"))
        service._sessions_delete = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await service.delete_session(USER, "s1", "7", _request())

        assert exc.value.status_code == 502
        service._sessions_delete.assert_not_called()

    @pytest.mark.anyio
    async def test_a_refused_workspace_stops_the_delete(self, service):
        service._sessions_get = AsyncMock(return_value=_session())
        service._sessions_delete = AsyncMock()
        service.workspace_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="Not a member"
        )

        with pytest.raises(HTTPException) as exc:
            await service.delete_session(USER, "s1", "7", _request())

        assert exc.value.status_code == 403
        service._sessions_delete.assert_not_called()

    @pytest.mark.anyio
    async def test_an_unknown_chat_is_404(self, service):
        service._sessions_get = AsyncMock(
            side_effect=ValueError("Session not found")
        )
        service._sessions_delete = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await service.delete_session(USER, "s1", "7", _request())

        assert exc.value.status_code == 404
        service._sessions_delete.assert_not_called()


class TestOwnerOnlySessions:
    """Another user's session is refused even when Agent Engine returns it."""

    @pytest.mark.anyio
    async def test_messages_of_another_users_session(self, service):
        service._sessions_get = AsyncMock(return_value=_session(user_id="99"))
        service._events_list = AsyncMock(return_value=[])

        with pytest.raises(HTTPException) as exc:
            await service.get_session_messages(USER, "s1", "7", _request())

        assert exc.value.status_code == 403
        service._events_list.assert_not_called()

    @pytest.mark.anyio
    async def test_detail_of_another_users_session(
        self, service, project_service
    ):
        # The detail path swallows most errors to stay best effort; this
        # refusal must still reach the caller.
        project_service.list_storyboards.return_value = []
        service._sessions_get = AsyncMock(return_value=_session(user_id="99"))
        service._events_list = AsyncMock(return_value=[])

        with pytest.raises(HTTPException) as exc:
            await service.get_session_detail(
                USER, 10, _request(), session_id="s1"
            )

        assert exc.value.status_code == 403
        service._events_list.assert_not_called()

    @pytest.mark.anyio
    async def test_state_of_another_users_session_is_not_loaded(self, service):
        # Characters and the storyboard sync rewrite what this returns.
        service._sessions_get = AsyncMock(return_value=_session(user_id="99"))

        with pytest.raises(HTTPException) as exc:
            await service._load_session_state(USER, "agent", "ads_x", "7", "s1")

        assert exc.value.status_code == 403
        service.workspace_auth.authorize.assert_not_called()

    @pytest.mark.anyio
    async def test_another_users_session_is_never_synced(self, service):
        service._sessions_get = AsyncMock(return_value=_session(user_id="99"))
        service._append_state_delta = AsyncMock()

        result = await service.sync_storyboard_to_session(
            USER,
            SimpleNamespace(id=14, session_id="s-foreign", workspace_id=10),
        )

        assert result["status"] == "failed"
        service._append_state_delta.assert_not_called()

    @pytest.mark.anyio
    async def test_the_owner_reads_their_session(self, service):
        service._sessions_get = AsyncMock(return_value=_session(user_id="7"))
        service._events_list = AsyncMock(return_value=[])

        dto = await service.get_session_messages(USER, "s1", "7", _request())

        assert dto.id == "s1"
        assert dto.state == {"workspace_id": 10}


class TestBearerTokenRedaction:
    """The token stored for the agent never travels back to a browser."""

    def test_state_and_event_deltas_drop_the_token(self, service):
        events = [
            {
                "author": "system",
                "actions": {
                    "state_delta": {"user_auth_token": "Bearer s", "x": 1}
                },
            },
            {
                "author": "user",
                "actions": {"stateDelta": {"user_auth_token": "t"}},
            },
            "raw event",
        ]
        session = _session(user_auth_token="Bearer s")

        dto = service._map_session_to_dto(session, "ads_x", "7", events=events)

        assert dto.state == {"workspace_id": 10}
        assert dto.events[0]["actions"]["state_delta"] == {"x": 1}
        assert dto.events[1]["actions"]["stateDelta"] == {}
        assert dto.events[2] == "raw event"
        assert "Bearer s" not in dto.model_dump_json()

    def test_object_sessions_drop_the_token_too(self, service):
        session = SimpleNamespace(
            name="agents/a/sessions/s1",
            user_id="7",
            session_state={"workspace_id": 10, "user_auth_token": "Bearer s"},
            update_time=None,
            events=[],
        )

        dto = service._map_session_to_dto(session, "ads_x", "7")

        assert dto.id == "s1"
        assert dto.state == {"workspace_id": 10}


class TestSessionDetailRegistry:
    """Registry metadata and recovery on the session-detail path."""

    @pytest.mark.anyio
    async def test_attaches_the_owners_metadata(self, service, registry):
        registry.get.return_value = _row("s1", title="Launch", summary="Cut")
        dto = _dto("s1")

        await service._attach_session_registry(USER, dto)

        assert (dto.projectId, dto.title, dto.summary) == (5, "Launch", "Cut")
        assert dto.restored is False

    @pytest.mark.anyio
    async def test_attaches_the_restored_flag(self, service, registry):
        registry.get.return_value = _row("s1", restored_at=_at(1_780_000_000))
        dto = _dto("s1")

        await service._attach_session_registry(USER, dto)

        assert dto.restored is True

    @pytest.mark.anyio
    async def test_ignores_other_users_rows_and_errors(self, service, registry):
        registry.get.return_value = _row("s1", user_id=99, title="Theirs")
        dto = _dto("s1")
        await service._attach_session_registry(USER, dto)
        assert dto.title is None

        registry.get.side_effect = RuntimeError("db down")
        await service._attach_session_registry(USER, dto)
        assert dto.projectId is None

    @pytest.mark.anyio
    async def test_recreated_session_keeps_its_registry_row(
        self, service, registry
    ):
        registry.replace_session_id.return_value = True

        await service._register_recreated_session(
            USER, 10, "old", "new", None, "ads_x"
        )

        # No storyboard came back: nothing to protect, Izumi may go on.
        registry.replace_session_id.assert_awaited_once_with(
            "old", "new", USER.id, restored=False
        )
        registry.register.assert_not_called()

    @pytest.mark.anyio
    async def test_recreated_chat_with_a_storyboard_is_marked_restored(
        self, service, registry
    ):
        registry.replace_session_id.return_value = True

        await service._register_recreated_session(
            USER, 10, "old", "new", SimpleNamespace(project_id=6), "ads_x"
        )

        registry.replace_session_id.assert_awaited_once_with(
            "old", "new", USER.id, restored=True
        )
        registry.register.assert_not_called()

    @pytest.mark.anyio
    async def test_recreated_session_joins_its_storyboards_project(
        self, service, registry, project_service
    ):
        registry.replace_session_id.return_value = False

        await service._register_recreated_session(
            USER, 10, "old", "new", SimpleNamespace(project_id=6), "ads_x"
        )

        registry.register.assert_awaited_once_with(
            "new", 6, USER.id, 10, "ads_x", restored=True
        )
        project_service.resolve_project_for_write.assert_not_called()

    @pytest.mark.anyio
    async def test_recreated_session_falls_back_to_the_default_project(
        self, service, registry, project_service
    ):
        project_service.resolve_project_for_write.return_value = _project(
            1, is_default=True
        )

        await service._register_recreated_session(
            USER, 10, None, "new", None, "ads_x"
        )

        registry.replace_session_id.assert_not_called()
        registry.register.assert_awaited_once_with(
            "new", 1, USER.id, 10, "ads_x", restored=False
        )

    @pytest.mark.anyio
    async def test_recreated_session_failures_are_swallowed(
        self, service, registry
    ):
        registry.replace_session_id.side_effect = RuntimeError("db down")

        await service._register_recreated_session(
            USER, 10, "old", "new", None, "ads_x"
        )

        registry.register.assert_not_called()


class TestUpdateSessionMetadata:
    """The chat's server-side title and summary."""

    @pytest.mark.anyio
    async def test_unknown_chat_is_404(self, service):
        with pytest.raises(HTTPException) as exc:
            await service.update_session_metadata(USER, "s1", title="x")

        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_another_users_chat_is_403(self, service, registry):
        registry.get.return_value = _row("s1", user_id=99)

        with pytest.raises(HTTPException) as exc:
            await service.update_session_metadata(USER, "s1", title="x")

        assert exc.value.status_code == 403
        registry.update_metadata.assert_not_called()

    @pytest.mark.anyio
    async def test_values_are_trimmed_and_the_updated_row_returned(
        self, service, registry
    ):
        registry.get.return_value = _row("s1")
        registry.update_metadata.return_value = _row(
            "s1", title="Launch", summary="Cut"
        )

        dto = await service.update_session_metadata(
            USER, "s1", title="  Launch ", summary=" Cut "
        )

        registry.update_metadata.assert_awaited_once_with(
            "s1", title="Launch", summary="Cut"
        )
        assert (dto.id, dto.userId, dto.projectId, dto.title, dto.summary) == (
            "s1",
            "7",
            5,
            "Launch",
            "Cut",
        )

    @pytest.mark.anyio
    async def test_blank_values_leave_the_fields_unchanged(
        self, service, registry
    ):
        registry.get.return_value = _row("s1", title="Kept")
        registry.update_metadata.return_value = None

        dto = await service.update_session_metadata(USER, "s1", title="   ")

        registry.update_metadata.assert_awaited_once_with(
            "s1", title=None, summary=None
        )
        assert dto.title == "Kept"

    @pytest.mark.anyio
    async def test_a_renamed_restored_chat_stays_restored(
        self, service, registry
    ):
        registry.get.return_value = _row("s1", restored_at=_at(1_780_000_000))
        registry.update_metadata.return_value = None

        dto = await service.update_session_metadata(USER, "s1", title="New")

        assert dto.restored is True


class TestRestoreSession:
    """``restore_session``: an expired chat on a new agent session."""

    @staticmethod
    def _expired_chat(service, registry):
        """``gone``: a registered chat the agent no longer has, which owns a
        storyboard. The second registry read is the moved row."""
        registry.get.side_effect = [
            _row("gone", title="Spring", last_used_at=_at(1_780_000_000)),
            _row("s-new", title="Spring", restored_at=_at(1_780_100_000)),
        ]
        registry.replace_session_id.return_value = True
        service._sessions_get = AsyncMock(
            side_effect=RuntimeError("Session not found")
        )
        service._sessions_create = AsyncMock(
            return_value={
                "id": "s-new",
                "user_id": "7",
                "session_state": {"workspace_id": 10},
            }
        )
        service._sessions_delete = AsyncMock()
        service.storyboard_repo.session_ids_with_storyboards.return_value = {
            "gone"
        }

    @staticmethod
    async def _refused(service, workspace_id=None):
        """The error ``restore_session`` raised; nothing was created."""
        with pytest.raises(HTTPException) as exc:
            await service.restore_session(
                USER, "7", "gone", _request(), workspace_id=workspace_id
            )
        service._sessions_create.assert_not_called()
        service.storyboard_repo.reassign_session.assert_not_called()
        return exc.value

    @pytest.mark.anyio
    async def test_the_same_chat_comes_back_on_a_new_session(
        self, service, registry
    ):
        self._expired_chat(service, registry)

        dto = await service.restore_session(
            USER, "7", "gone", _request(), workspace_id=10
        )

        assert (dto.id, dto.projectId, dto.title) == ("s-new", 5, "Spring")
        assert (dto.restored, dto.expired) == (True, False)
        service.workspace_auth.authorize.assert_awaited_once_with(
            workspace_id=10, user=USER
        )
        agent, app, user, state = service._sessions_create.await_args.args
        assert (agent, app, user) == ("agent", "ads_x", "7")
        assert state["workspace_id"] == 10
        assert "Bearer token" in state.values()
        registry.replace_session_id.assert_awaited_once_with(
            "gone", "s-new", USER.id, restored=True
        )
        service.storyboard_repo.reassign_session.assert_awaited_once_with(
            "gone", "s-new", USER.id
        )
        service._sessions_delete.assert_not_called()

    @pytest.mark.anyio
    async def test_an_unknown_chat_is_404(self, service, registry):
        self._expired_chat(service, registry)
        registry.get.side_effect = None
        registry.get.return_value = None

        assert (await self._refused(service)).status_code == 404

    @pytest.mark.anyio
    async def test_another_users_chat_is_403(self, service, registry):
        self._expired_chat(service, registry)
        registry.get.side_effect = None
        registry.get.return_value = _row("gone", user_id=99)

        assert (await self._refused(service)).status_code == 403
        service._sessions_get.assert_not_called()

    @pytest.mark.anyio
    async def test_a_chat_of_another_workspace_is_400(self, service, registry):
        self._expired_chat(service, registry)

        error = await self._refused(service, workspace_id=11)

        assert error.status_code == 400
        service.workspace_auth.authorize.assert_not_called()

    @pytest.mark.anyio
    async def test_a_refused_workspace_stops_the_restore(
        self, service, registry
    ):
        self._expired_chat(service, registry)
        service.workspace_auth.authorize.side_effect = HTTPException(
            status_code=403, detail="Not a member"
        )

        assert (await self._refused(service)).status_code == 403

    @pytest.mark.anyio
    async def test_a_live_chat_is_not_restored(self, service, registry):
        self._expired_chat(service, registry)
        service._sessions_get = AsyncMock(return_value=_session())

        error = await self._refused(service)

        assert (error.status_code, error.detail) == (
            409,
            "This chat has not expired.",
        )

    @pytest.mark.anyio
    async def test_a_chat_without_storyboard_is_not_restored(
        self, service, registry
    ):
        self._expired_chat(service, registry)
        service.storyboard_repo.session_ids_with_storyboards.return_value = (
            set()
        )

        error = await self._refused(service)

        assert (error.status_code, error.detail) == (
            409,
            "This chat has no storyboard to restore.",
        )
        registry.replace_session_id.assert_not_called()

    @pytest.mark.anyio
    async def test_a_concurrent_restore_drops_its_session(
        self, service, registry
    ):
        # A double click: the first request already moved the registry row.
        self._expired_chat(service, registry)
        registry.replace_session_id.return_value = False

        with pytest.raises(HTTPException) as exc:
            await service.restore_session(USER, "7", "gone", _request())

        assert (exc.value.status_code, exc.value.detail) == (
            409,
            "This chat was already restored.",
        )
        service._sessions_delete.assert_awaited_once_with(
            "agent", "ads_x", "7", "s-new"
        )
        service.storyboard_repo.reassign_session.assert_not_called()


class TestProjectDeleteHelpers:
    """What the project delete route relies on."""

    def test_a_running_chat_blocks_the_delete(self, service):
        module._mark_run_started("s-busy")
        try:
            with pytest.raises(HTTPException) as exc:
                service.ensure_sessions_idle(["s-idle", "s-busy"])
        finally:
            module._mark_run_finished("s-busy")

        assert exc.value.status_code == 409
        assert "still running" in exc.value.detail

    def test_idle_chats_pass(self, service):
        service.ensure_sessions_idle([])
        service.ensure_sessions_idle(["s-idle"])

    @pytest.mark.anyio
    async def test_nothing_to_delete(self, service):
        service._sessions_delete = AsyncMock()

        assert await service.delete_sessions_best_effort(USER, {}) == []
        service._sessions_delete.assert_not_called()

    @pytest.mark.anyio
    async def test_unavailable_agent_keeps_every_session(self, service):
        service._get_validated_agent_name = MagicMock(
            side_effect=HTTPException(status_code=503, detail="Agent down")
        )
        service._sessions_delete = AsyncMock()

        failed = await service.delete_sessions_best_effort(
            USER, {"s1": "ads_x", "s2": "ads_x"}
        )

        assert failed == ["s1", "s2"]
        service._sessions_delete.assert_not_called()

    @pytest.mark.anyio
    async def test_only_real_failures_are_reported(self, service):
        async def delete(_agent, _app, _user, session_id):
            if session_id == "s2":
                raise RuntimeError("Session not found")
            if session_id == "s3":
                raise RuntimeError("boom")

        service._sessions_delete = AsyncMock(side_effect=delete)

        failed = await service.delete_sessions_best_effort(
            USER, {"s1": "ads_x", "s2": "ads_x", "s3": "ads_x"}
        )

        assert failed == ["s3"]
        calls = sorted(c.args for c in service._sessions_delete.await_args_list)
        assert calls == [
            ("agent", "ads_x", "7", "s1"),
            ("agent", "ads_x", "7", "s2"),
            ("agent", "ads_x", "7", "s3"),
        ]

    @pytest.mark.anyio
    async def test_each_chat_is_deleted_from_its_own_agent(self, service):
        service._get_validated_agent_name = MagicMock(
            side_effect=lambda app: f"agent-{app}"
        )
        service._sessions_delete = AsyncMock()

        failed = await service.delete_sessions_best_effort(
            USER, {"s1": "ads_x", "s2": "brand_x", "s3": ""}
        )

        assert failed == []
        calls = sorted(c.args for c in service._sessions_delete.await_args_list)
        assert calls == [
            ("agent-ads_x", "ads_x", "7", "s1"),
            ("agent-ads_x", "ads_x", "7", "s3"),  # No app name: the default.
            ("agent-brand_x", "brand_x", "7", "s2"),
        ]

    @pytest.mark.anyio
    async def test_an_unavailable_agent_keeps_only_its_chats(self, service):
        def agent_name(app):
            if app == "brand_x":
                raise HTTPException(status_code=503, detail="Not configured")
            return "agent"

        service._get_validated_agent_name = MagicMock(side_effect=agent_name)
        service._sessions_delete = AsyncMock()

        failed = await service.delete_sessions_best_effort(
            USER, {"s1": "ads_x", "s2": "brand_x"}
        )

        assert failed == ["s2"]
        service._sessions_delete.assert_awaited_once_with(
            "agent", "ads_x", "7", "s1"
        )

    @pytest.mark.anyio
    async def test_deletes_a_few_chats_at_a_time(self, service):
        in_flight = peak = 0

        async def delete(*_args):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1

        service._sessions_delete = delete

        sessions = {f"s{i}": "ads_x" for i in range(10)}
        assert await service.delete_sessions_best_effort(USER, sessions) == []
        assert peak == module._SESSION_DELETE_CONCURRENCY

    @pytest.mark.anyio
    async def test_vertex_deletes_run_off_the_event_loop(self, service):
        service.use_local_agent = False
        threads = []
        vertex_delete = service.client.agent_engines.sessions.delete
        vertex_delete.side_effect = lambda **_: threads.append(
            threading.get_ident()
        )

        await service._sessions_delete("agent", "ads_x", "7", "s1")

        vertex_delete.assert_called_once_with(name="agent/sessions/s1")
        assert threads and threads[0] != threading.get_ident()

    @pytest.mark.parametrize(
        "error, gone",
        [
            (genai_errors.ClientError(404, {"error": {"code": 404}}), True),
            (google_exceptions.NotFound("Session gone"), True),
            # A status code wins over a misleading message.
            (genai_errors.ServerError(503, {"error": {"code": 503}}), False),
            (google_exceptions.InternalServerError("not found"), False),
            # No status code: the message decides.
            (RuntimeError("Session not found"), True),
            (RuntimeError("boom"), False),
        ],
    )
    def test_not_found_is_decided_by_the_status_code(self, error, gone):
        assert module._is_session_not_found(error) is gone


class TestChatActivity:
    """``chat()`` records activity before its run guard (409 here)."""

    @staticmethod
    async def _chat_on_busy_session(service):
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": "s-touch",
            "workspaceId": 10,
        }
        module._mark_run_started("s-touch")
        try:
            with pytest.raises(HTTPException) as exc:
                await service.chat(
                    current_user=USER,
                    user_id="7",
                    payload=payload,
                    request=_request(),
                )
        finally:
            module._mark_run_finished("s-touch")
        return exc.value

    @pytest.mark.anyio
    async def test_touches_only_the_callers_chat(self, service, registry):
        error = await self._chat_on_busy_session(service)

        assert error.status_code == 409
        registry.touch.assert_awaited_once_with("s-touch", USER.id)

    @pytest.mark.anyio
    async def test_a_failed_touch_does_not_skip_the_run_guard(
        self, service, registry
    ):
        registry.touch.side_effect = RuntimeError("db down")

        error = await self._chat_on_busy_session(service)

        assert error.status_code == 409


class TestChatOwner:
    """``chat()`` refuses another user's chat before it touches it."""

    @staticmethod
    async def _chat(service, session_id, busy=False):
        """The error ``chat()`` raised. With ``busy``, the run guard's 409
        proves that the owner check let the chat through."""
        payload = MagicMock()
        payload.model_dump.return_value = {
            "sessionId": session_id,
            "workspaceId": 10,
        }
        if busy:
            module._mark_run_started(session_id)
        try:
            with pytest.raises(HTTPException) as exc:
                await service.chat(
                    current_user=USER,
                    user_id="7",
                    payload=payload,
                    request=_request(),
                )
        finally:
            module._mark_run_finished(session_id)
        return exc.value

    @pytest.mark.anyio
    async def test_a_registered_foreign_chat_is_refused_unread(
        self, service, registry
    ):
        registry.get.return_value = _row("s-theirs", user_id=99)
        service._sessions_get = AsyncMock()
        service._append_state_delta = AsyncMock()

        error = await self._chat(service, "s-theirs")

        assert error.status_code == 403
        service._sessions_get.assert_not_called()
        service._append_state_delta.assert_not_called()
        registry.touch.assert_not_called()

    @pytest.mark.anyio
    async def test_an_unregistered_foreign_chat_is_refused(self, service):
        service._sessions_get = AsyncMock(return_value=_session(user_id="99"))
        service._append_state_delta = AsyncMock()

        error = await self._chat(service, "s-theirs")

        assert error.status_code == 403
        service._append_state_delta.assert_not_called()

    @pytest.mark.anyio
    async def test_an_unreadable_unregistered_chat_is_not_run(self, service):
        service._sessions_get = AsyncMock(side_effect=RuntimeError("boom"))

        error = await self._chat(service, "s-unreadable")

        assert error.status_code == 502

    @pytest.mark.anyio
    async def test_a_registered_own_chat_costs_no_session_read(
        self, service, registry
    ):
        registry.get.return_value = _row("s-mine")
        service._sessions_get = AsyncMock()

        error = await self._chat(service, "s-mine", busy=True)

        assert error.status_code == 409
        service._sessions_get.assert_not_called()

    @pytest.mark.anyio
    async def test_an_unregistered_own_chat_goes_on(self, service):
        service._sessions_get = AsyncMock(return_value=_session(user_id="7"))

        error = await self._chat(service, "s-mine", busy=True)

        assert error.status_code == 409
        service._sessions_get.assert_awaited_once_with(
            "agent", "ads_x", "7", "s-mine"
        )

    @pytest.mark.anyio
    async def test_an_unknown_chat_is_left_to_the_run(self, service):
        service._sessions_get = AsyncMock(
            side_effect=RuntimeError("Session not found")
        )

        error = await self._chat(service, "s-unknown", busy=True)

        assert error.status_code == 409

    @pytest.mark.anyio
    async def test_a_restored_chat_is_never_run(self, service, registry):
        # Izumi does not remember it: a run would reuse its storyboard.
        registry.get.return_value = _row(
            "s-restored", restored_at=_at(1_780_000_000)
        )
        service._sessions_get = AsyncMock()
        service._append_state_delta = AsyncMock()

        error = await self._chat(service, "s-restored", busy=True)

        # Not the run guard's 409: the run never got that far.
        assert (error.status_code, error.detail) == (
            409,
            module.RESTORED_CHAT_DETAIL,
        )
        registry.touch.assert_not_called()
        service._sessions_get.assert_not_called()
        service._append_state_delta.assert_not_called()
