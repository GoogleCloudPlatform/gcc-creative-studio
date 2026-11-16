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

"""Tests for the generated-media output folder resolver."""

import datetime
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.common.request_context import is_agent_request
from src.folders.output_folder import (
    OUTPUT_FOLDER_NOT_FOUND_DETAIL,
    resolve_output_folder_id,
)
from src.folders.schema.folder_model import Folder
from src.users.user_model import UserModel, UserRoleEnum

MODULE = "src.folders.output_folder"

WORKSPACE_ID = 3
OTHER_WORKSPACE_ID = 4
FOLDER_ID = 42


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=10,
        email="user@example.com",
        roles=[UserRoleEnum.USER],
        name="User",
    )


@pytest.fixture(name="mock_db")
def fixture_mock_db():
    return AsyncMock()


@pytest.fixture(name="agent_helper")
def fixture_agent_helper():
    with patch(
        f"{MODULE}.resolve_agent_output_folder_id", new_callable=AsyncMock
    ) as helper:
        yield helper


@pytest.fixture(name="folder_lookup")
def fixture_folder_lookup():
    """Patches ``FolderRepository.get_folder_by_id``; set its return value."""
    with patch(f"{MODULE}.FolderRepository") as repo_cls:
        lookup = AsyncMock(return_value=None)
        repo_cls.return_value.get_folder_by_id = lookup
        yield lookup


def _folder(
    workspace_id: int = WORKSPACE_ID, user_id: int | None = 10
) -> Folder:
    return Folder(
        id=FOLDER_ID,
        workspace_id=workspace_id,
        user_id=user_id,
        user_email="owner@example.com",
        name="Campaign",
    )


@pytest.mark.anyio
async def test_no_requested_folder_delegates_to_agent_helper(
    mock_db, sample_user, agent_helper, folder_lookup
):
    agent_helper.return_value = 77

    result = await resolve_output_folder_id(
        mock_db, WORKSPACE_ID, sample_user, None
    )

    assert result == 77
    agent_helper.assert_awaited_once_with(mock_db, WORKSPACE_ID, sample_user)
    folder_lookup.assert_not_awaited()


@pytest.mark.anyio
async def test_no_requested_folder_returns_root_for_regular_requests(
    mock_db, sample_user
):
    token = is_agent_request.set(False)
    try:
        result = await resolve_output_folder_id(
            mock_db, WORKSPACE_ID, sample_user, None
        )
    finally:
        is_agent_request.reset(token)

    assert result is None


@pytest.mark.anyio
async def test_folder_in_same_workspace_is_returned(
    mock_db, sample_user, agent_helper, folder_lookup
):
    folder_lookup.return_value = _folder()

    result = await resolve_output_folder_id(
        mock_db, WORKSPACE_ID, sample_user, FOLDER_ID
    )

    assert result == FOLDER_ID
    folder_lookup.assert_awaited_once_with(FOLDER_ID)
    agent_helper.assert_not_awaited()


@pytest.mark.anyio
async def test_folder_owned_by_another_user_is_allowed(
    mock_db, sample_user, folder_lookup
):
    folder_lookup.return_value = _folder(user_id=999)

    result = await resolve_output_folder_id(
        mock_db, WORKSPACE_ID, sample_user, FOLDER_ID
    )

    assert result == FOLDER_ID


@pytest.mark.anyio
async def test_explicit_folder_wins_over_agent_folder(
    mock_db, sample_user, agent_helper, folder_lookup
):
    folder_lookup.return_value = _folder()
    token = is_agent_request.set(True)
    try:
        result = await resolve_output_folder_id(
            mock_db, WORKSPACE_ID, sample_user, FOLDER_ID
        )
    finally:
        is_agent_request.reset(token)

    assert result == FOLDER_ID
    agent_helper.assert_not_awaited()


def _soft_deleted_lookup() -> Callable[..., Awaitable[Folder | None]]:
    """Mimics the repository: soft-deleted folders are hidden by default."""
    deleted = _folder()
    deleted.deleted_at = datetime.datetime.now(datetime.timezone.utc)

    async def _get(folder_id: int, include_deleted: bool = False):
        return deleted if include_deleted else None

    return _get


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    ["missing", "soft_deleted", "other_workspace"],
)
async def test_invalid_folder_raises_generic_422(
    case, mock_db, sample_user, agent_helper, folder_lookup
):
    if case == "soft_deleted":
        folder_lookup.side_effect = _soft_deleted_lookup()
    elif case == "other_workspace":
        folder_lookup.return_value = _folder(workspace_id=OTHER_WORKSPACE_ID)

    with pytest.raises(HTTPException) as exc_info:
        await resolve_output_folder_id(
            mock_db, WORKSPACE_ID, sample_user, FOLDER_ID
        )

    error = exc_info.value
    assert error.status_code == 422
    assert error.detail == OUTPUT_FOLDER_NOT_FOUND_DETAIL
    agent_helper.assert_not_awaited()
