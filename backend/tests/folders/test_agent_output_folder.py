# Copyright 2025 Google LLC
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

"""Tests for the Izumi agent output folder resolver."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.common.request_context import is_agent_request
from src.folders.agent_output_folder import (
    AGENT_OUTPUT_FOLDER_COLOR,
    AGENT_OUTPUT_FOLDER_NAME,
    resolve_agent_output_folder_id,
)
from src.folders.schema.folder_model import Folder
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceScopeEnum,
)

MODULE = "src.folders.agent_output_folder"

ROOT_ID = 7
CHILD_ID = 8
OWNER_ID = 1
OWNER_EMAIL = "admin@example.com"


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=10,
        email="agent-user@example.com",
        roles=[UserRoleEnum.USER],
        name="Agent User",
    )


@pytest.fixture(name="workspace_owner")
def fixture_workspace_owner():
    return UserModel(
        id=OWNER_ID,
        email=OWNER_EMAIL,
        roles=[UserRoleEnum.ADMIN],
        name="Admin",
    )


@pytest.fixture(name="mock_db")
def fixture_mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture(name="agent_context")
def fixture_agent_context():
    """Marks the current context as an agent request for the test duration."""
    token = is_agent_request.set(True)
    yield
    is_agent_request.reset(token)


@pytest.fixture(name="owner_lookup")
def fixture_owner_lookup(workspace_owner):
    """Patches the workspace/user repositories so the owner resolves."""
    workspace = WorkspaceModel(
        id=3,
        name="WS",
        owner_id=OWNER_ID,
        scope=WorkspaceScopeEnum.PUBLIC,
        members=[],
    )
    with (
        patch(f"{MODULE}.WorkspaceRepository") as ws_repo_cls,
        patch(f"{MODULE}.UserRepository") as user_repo_cls,
    ):
        ws_repo_cls.return_value.get_by_id = AsyncMock(return_value=workspace)
        user_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=workspace_owner
        )
        yield ws_repo_cls, user_repo_cls


def _folder(folder_id: int, name: str, parent_id: int | None = None) -> Folder:
    return Folder(
        id=folder_id,
        workspace_id=3,
        user_email="x@y.z",
        name=name,
        parent_id=parent_id,
    )


def _sequential_refresh(*ids: int):
    """``db.refresh`` side effect assigning ids to created folders in order."""
    pending = list(ids)

    async def _refresh(obj):
        obj.id = pending.pop(0)

    return _refresh


@pytest.mark.anyio
async def test_returns_none_for_regular_user_requests(mock_db, sample_user):
    token = is_agent_request.set(False)
    try:
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)
    finally:
        is_agent_request.reset(token)

    assert result is None
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_reuses_existing_root_and_child(
    mock_db, sample_user, agent_context, owner_lookup
):
    root = _folder(ROOT_ID, AGENT_OUTPUT_FOLDER_NAME)
    child = _folder(CHILD_ID, sample_user.email, parent_id=ROOT_ID)
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[root, child]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == CHILD_ID
    lookups = repo_cls.return_value.get_folder_by_name.await_args_list
    assert lookups[0].kwargs == {
        "workspace_id": 3,
        "parent_id": None,
        "name": AGENT_OUTPUT_FOLDER_NAME,
    }
    assert lookups[1].kwargs == {
        "workspace_id": 3,
        "parent_id": ROOT_ID,
        "name": sample_user.email,
    }
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_creates_root_owned_by_workspace_owner_and_child_by_user(
    mock_db, sample_user, agent_context, owner_lookup
):
    mock_db.refresh = AsyncMock(
        side_effect=_sequential_refresh(ROOT_ID, CHILD_ID)
    )
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[None, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == CHILD_ID
    assert mock_db.add.call_count == 2
    root: Folder = mock_db.add.call_args_list[0].args[0]
    child: Folder = mock_db.add.call_args_list[1].args[0]

    assert root.workspace_id == 3
    assert root.parent_id is None
    assert root.name == AGENT_OUTPUT_FOLDER_NAME
    assert root.color == AGENT_OUTPUT_FOLDER_COLOR
    # Root belongs to the workspace owner, not to the generating user.
    assert root.user_id == OWNER_ID
    assert root.user_email == OWNER_EMAIL

    assert child.parent_id == ROOT_ID
    assert child.name == sample_user.email
    assert child.user_id == sample_user.id
    assert child.user_email == sample_user.email
    assert child.color == AGENT_OUTPUT_FOLDER_COLOR
    assert mock_db.commit.await_count == 2


@pytest.mark.anyio
async def test_creates_only_child_when_root_exists(
    mock_db, sample_user, agent_context, owner_lookup
):
    root = _folder(ROOT_ID, AGENT_OUTPUT_FOLDER_NAME)
    mock_db.refresh = AsyncMock(side_effect=_sequential_refresh(CHILD_ID))
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[root, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == CHILD_ID
    mock_db.add.assert_called_once()
    created: Folder = mock_db.add.call_args.args[0]
    assert created.parent_id == ROOT_ID
    assert created.user_id == sample_user.id


@pytest.mark.anyio
async def test_falls_back_to_requesting_user_when_workspace_missing(
    mock_db, sample_user, agent_context
):
    mock_db.refresh = AsyncMock(
        side_effect=_sequential_refresh(ROOT_ID, CHILD_ID)
    )
    with (
        patch(f"{MODULE}.WorkspaceRepository") as ws_repo_cls,
        patch(f"{MODULE}.UserRepository"),
        patch(f"{MODULE}.FolderRepository") as repo_cls,
    ):
        ws_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[None, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == CHILD_ID
    root: Folder = mock_db.add.call_args_list[0].args[0]
    assert root.user_id == sample_user.id
    assert root.user_email == sample_user.email


@pytest.mark.anyio
async def test_falls_back_to_requesting_user_when_owner_lookup_fails(
    mock_db, sample_user, agent_context
):
    mock_db.refresh = AsyncMock(
        side_effect=_sequential_refresh(ROOT_ID, CHILD_ID)
    )
    with (
        patch(f"{MODULE}.WorkspaceRepository") as ws_repo_cls,
        patch(f"{MODULE}.UserRepository"),
        patch(f"{MODULE}.FolderRepository") as repo_cls,
    ):
        ws_repo_cls.return_value.get_by_id = AsyncMock(
            side_effect=RuntimeError("db hiccup")
        )
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[None, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == CHILD_ID
    root: Folder = mock_db.add.call_args_list[0].args[0]
    assert root.user_id == sample_user.id


@pytest.mark.anyio
async def test_race_on_root_create_falls_back_to_lookup(
    mock_db, sample_user, agent_context, owner_lookup
):
    mock_db.commit = AsyncMock(
        side_effect=[IntegrityError("INSERT", {}, Exception("dup")), None]
    )
    mock_db.refresh = AsyncMock(side_effect=_sequential_refresh(CHILD_ID))
    winner = _folder(99, AGENT_OUTPUT_FOLDER_NAME)
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        # root miss -> race -> root re-lookup hits -> child miss -> create
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[None, winner, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == CHILD_ID
    mock_db.rollback.assert_awaited_once()
    child: Folder = mock_db.add.call_args_list[1].args[0]
    assert child.parent_id == 99


@pytest.mark.anyio
async def test_race_on_child_create_falls_back_to_lookup(
    mock_db, sample_user, agent_context, owner_lookup
):
    root = _folder(ROOT_ID, AGENT_OUTPUT_FOLDER_NAME)
    winner = _folder(55, sample_user.email, parent_id=ROOT_ID)
    mock_db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("dup"))
    )
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[root, None, winner]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == 55
    mock_db.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_race_then_root_lookup_miss_returns_none(
    mock_db, sample_user, agent_context, owner_lookup
):
    mock_db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("dup"))
    )
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[None, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result is None


@pytest.mark.anyio
async def test_child_race_lookup_miss_falls_back_to_root(
    mock_db, sample_user, agent_context, owner_lookup
):
    root = _folder(ROOT_ID, AGENT_OUTPUT_FOLDER_NAME)
    mock_db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("dup"))
    )
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=[root, None, None]
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result == ROOT_ID


@pytest.mark.anyio
async def test_unexpected_error_never_breaks_generation(
    mock_db, sample_user, agent_context, owner_lookup
):
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result is None
    mock_db.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_unexpected_error_with_failing_rollback_returns_none(
    mock_db, sample_user, agent_context, owner_lookup
):
    mock_db.rollback = AsyncMock(side_effect=RuntimeError("no rollback"))
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        repo_cls.return_value.get_folder_by_name = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        result = await resolve_agent_output_folder_id(mock_db, 3, sample_user)

    assert result is None
