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

"""Tests for the folder ownership / permission policy.

Covers the service-level policy (``is_workspace_manager``,
``ensure_can_manage_folder``, ``ensure_can_move_items``), the repository
ownership probes, and the controller wiring that turns a policy violation
into a 403.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status

from main import app
from src.auth.auth_guard import get_current_user
from src.folders.dto.folder_dto import MoveItemsDto
from src.folders.folder_service import (
    FOLDER_NOT_OWNED_DETAIL,
    FOLDER_SUBTREE_NOT_OWNED_DETAIL,
    ITEMS_NOT_OWNED_DETAIL,
    FolderService,
)
from src.folders.repository.folder_repository import FolderRepository
from src.folders.schema.folder_model import Folder
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceScopeEnum,
)
from src.workspaces.workspace_auth_guard import WorkspaceAuth

OWNER_ID = 1
MEMBER_ID = 2
OTHER_ID = 3
ADMIN_ID = 4


def _user(user_id: int, *roles: UserRoleEnum) -> UserModel:
    return UserModel(
        id=user_id,
        email=f"user{user_id}@example.com",
        roles=list(roles) or [UserRoleEnum.USER],
        name=f"User {user_id}",
    )


def _workspace(scope: WorkspaceScopeEnum, owner_id: int = OWNER_ID):
    return WorkspaceModel(
        id=1, name="WS", owner_id=owner_id, scope=scope, members=[]
    )


def _folder(folder_id: int, user_id: int | None, parent_id=None) -> Folder:
    return Folder(
        id=folder_id,
        workspace_id=1,
        user_id=user_id,
        user_email="x@y.z",
        name=f"F{folder_id}",
        parent_id=parent_id,
    )


@pytest.fixture(name="mock_folder_repo")
def fixture_mock_folder_repo():
    repo = AsyncMock()
    repo.subtree_has_foreign_content.return_value = False
    repo.has_foreign_items.return_value = False
    repo.get_folders_by_ids.return_value = []
    return repo


@pytest.fixture(name="service")
def fixture_service(mock_folder_repo):
    return FolderService(folder_repo=mock_folder_repo)


# ---------------------------------------------------------------------------
# is_workspace_manager
# ---------------------------------------------------------------------------
class TestIsWorkspaceManager:
    def test_admin_manages_public_workspace(self):
        assert FolderService.is_workspace_manager(
            _user(ADMIN_ID, UserRoleEnum.ADMIN),
            _workspace(WorkspaceScopeEnum.PUBLIC),
        )

    def test_admin_manages_private_workspace(self):
        assert FolderService.is_workspace_manager(
            _user(ADMIN_ID, UserRoleEnum.ADMIN),
            _workspace(WorkspaceScopeEnum.PRIVATE),
        )

    def test_private_owner_is_manager(self):
        assert FolderService.is_workspace_manager(
            _user(OWNER_ID), _workspace(WorkspaceScopeEnum.PRIVATE)
        )

    def test_public_owner_is_not_manager(self):
        """On public workspaces only admins get blanket rights."""
        assert not FolderService.is_workspace_manager(
            _user(OWNER_ID), _workspace(WorkspaceScopeEnum.PUBLIC)
        )

    def test_private_member_is_not_manager(self):
        assert not FolderService.is_workspace_manager(
            _user(MEMBER_ID), _workspace(WorkspaceScopeEnum.PRIVATE)
        )

    def test_user_without_roles_is_not_manager(self):
        user = _user(MEMBER_ID)
        user.roles = []
        assert not FolderService.is_workspace_manager(
            user, _workspace(WorkspaceScopeEnum.PUBLIC)
        )


# ---------------------------------------------------------------------------
# ensure_can_manage_folder
# ---------------------------------------------------------------------------
class TestAssertCanManageFolder:
    @pytest.mark.anyio
    async def test_admin_skips_all_checks(self, service, mock_folder_repo):
        await service.ensure_can_manage_folder(
            _folder(1, OTHER_ID),
            _user(ADMIN_ID, UserRoleEnum.ADMIN),
            _workspace(WorkspaceScopeEnum.PUBLIC),
            check_subtree=True,
        )
        mock_folder_repo.subtree_has_foreign_content.assert_not_awaited()

    @pytest.mark.anyio
    async def test_private_owner_skips_all_checks(
        self, service, mock_folder_repo
    ):
        await service.ensure_can_manage_folder(
            _folder(1, OTHER_ID),
            _user(OWNER_ID),
            _workspace(WorkspaceScopeEnum.PRIVATE),
            check_subtree=True,
        )
        mock_folder_repo.subtree_has_foreign_content.assert_not_awaited()

    @pytest.mark.anyio
    async def test_creator_allowed_when_subtree_is_theirs(
        self, service, mock_folder_repo
    ):
        await service.ensure_can_manage_folder(
            _folder(1, MEMBER_ID),
            _user(MEMBER_ID),
            _workspace(WorkspaceScopeEnum.PUBLIC),
            check_subtree=True,
        )
        mock_folder_repo.subtree_has_foreign_content.assert_awaited_once_with(
            1, MEMBER_ID
        )

    @pytest.mark.anyio
    async def test_creator_rename_skips_subtree_check(
        self, service, mock_folder_repo
    ):
        mock_folder_repo.subtree_has_foreign_content.return_value = True
        await service.ensure_can_manage_folder(
            _folder(1, MEMBER_ID),
            _user(MEMBER_ID),
            _workspace(WorkspaceScopeEnum.PUBLIC),
            check_subtree=False,
        )
        mock_folder_repo.subtree_has_foreign_content.assert_not_awaited()

    @pytest.mark.anyio
    async def test_non_creator_forbidden(self, service, mock_folder_repo):
        with pytest.raises(HTTPException) as exc:
            await service.ensure_can_manage_folder(
                _folder(1, OTHER_ID),
                _user(MEMBER_ID),
                _workspace(WorkspaceScopeEnum.PUBLIC),
                check_subtree=False,
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc.value.detail == FOLDER_NOT_OWNED_DETAIL
        mock_folder_repo.subtree_has_foreign_content.assert_not_awaited()

    @pytest.mark.anyio
    async def test_public_workspace_owner_cannot_touch_others_folders(
        self, service
    ):
        with pytest.raises(HTTPException) as exc:
            await service.ensure_can_manage_folder(
                _folder(1, OTHER_ID),
                _user(OWNER_ID),
                _workspace(WorkspaceScopeEnum.PUBLIC),
                check_subtree=True,
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.anyio
    async def test_creator_forbidden_when_subtree_has_foreign_content(
        self, service, mock_folder_repo
    ):
        mock_folder_repo.subtree_has_foreign_content.return_value = True
        with pytest.raises(HTTPException) as exc:
            await service.ensure_can_manage_folder(
                _folder(1, MEMBER_ID),
                _user(MEMBER_ID),
                _workspace(WorkspaceScopeEnum.PRIVATE),
                check_subtree=True,
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc.value.detail == FOLDER_SUBTREE_NOT_OWNED_DETAIL

    @pytest.mark.anyio
    async def test_folder_without_owner_is_foreign(self, service):
        with pytest.raises(HTTPException):
            await service.ensure_can_manage_folder(
                _folder(1, None),
                _user(MEMBER_ID),
                _workspace(WorkspaceScopeEnum.PUBLIC),
                check_subtree=False,
            )


# ---------------------------------------------------------------------------
# ensure_can_move_items
# ---------------------------------------------------------------------------
class TestAssertCanMoveItems:
    @pytest.mark.anyio
    async def test_manager_skips_checks(self, service, mock_folder_repo):
        dto = MoveItemsDto(workspace_id=1, media_item_ids=[1], folder_ids=[2])
        await service.ensure_can_move_items(
            dto,
            _user(ADMIN_ID, UserRoleEnum.ADMIN),
            _workspace(WorkspaceScopeEnum.PUBLIC),
        )
        mock_folder_repo.get_folders_by_ids.assert_not_awaited()
        mock_folder_repo.has_foreign_items.assert_not_awaited()

    @pytest.mark.anyio
    async def test_owned_folders_and_items_allowed(
        self, service, mock_folder_repo
    ):
        mock_folder_repo.get_folders_by_ids.return_value = [
            _folder(2, MEMBER_ID),
            _folder(3, MEMBER_ID),
        ]
        dto = MoveItemsDto(
            workspace_id=1,
            media_item_ids=[1],
            source_asset_ids=[9],
            folder_ids=[2, 3, 2],
        )
        await service.ensure_can_move_items(
            dto, _user(MEMBER_ID), _workspace(WorkspaceScopeEnum.PUBLIC)
        )
        mock_folder_repo.get_folders_by_ids.assert_awaited_once_with(
            folder_ids=[2, 3], workspace_id=1
        )
        assert mock_folder_repo.subtree_has_foreign_content.await_count == 2
        mock_folder_repo.has_foreign_items.assert_awaited_once_with(
            media_item_ids=[1],
            source_asset_ids=[9],
            workspace_id=1,
            user_id=MEMBER_ID,
        )

    @pytest.mark.anyio
    async def test_foreign_folder_forbidden(self, service, mock_folder_repo):
        mock_folder_repo.get_folders_by_ids.return_value = [
            _folder(2, MEMBER_ID),
            _folder(3, OTHER_ID),
        ]
        dto = MoveItemsDto(workspace_id=1, folder_ids=[2, 3])
        with pytest.raises(HTTPException) as exc:
            await service.ensure_can_move_items(
                dto, _user(MEMBER_ID), _workspace(WorkspaceScopeEnum.PUBLIC)
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc.value.detail == FOLDER_NOT_OWNED_DETAIL
        mock_folder_repo.has_foreign_items.assert_not_awaited()

    @pytest.mark.anyio
    async def test_foreign_items_forbidden(self, service, mock_folder_repo):
        mock_folder_repo.has_foreign_items.return_value = True
        dto = MoveItemsDto(workspace_id=1, media_item_ids=[1, 2])
        with pytest.raises(HTTPException) as exc:
            await service.ensure_can_move_items(
                dto, _user(MEMBER_ID), _workspace(WorkspaceScopeEnum.PRIVATE)
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc.value.detail == ITEMS_NOT_OWNED_DETAIL
        mock_folder_repo.get_folders_by_ids.assert_not_awaited()

    @pytest.mark.anyio
    async def test_empty_payload_passes(self, service, mock_folder_repo):
        dto = MoveItemsDto(workspace_id=1)
        await service.ensure_can_move_items(
            dto, _user(MEMBER_ID), _workspace(WorkspaceScopeEnum.PUBLIC)
        )
        mock_folder_repo.get_folders_by_ids.assert_not_awaited()
        mock_folder_repo.has_foreign_items.assert_not_awaited()


# ---------------------------------------------------------------------------
# Repository ownership probes
# ---------------------------------------------------------------------------
def _count_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _descendants(*ids: int) -> MagicMock:
    result = MagicMock()
    result.fetchall.return_value = [MagicMock(id=i) for i in ids]
    return result


class TestRepositoryOwnershipProbes:
    @pytest.fixture(name="mock_db")
    def fixture_mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.fixture(name="repo")
    def fixture_repo(self, mock_db):
        return FolderRepository(db=mock_db)

    @pytest.mark.anyio
    async def test_subtree_clean(self, repo, mock_db):
        mock_db.execute.side_effect = [
            _descendants(1, 2),
            _count_result(0),  # folders
            _count_result(0),  # media
            _count_result(0),  # assets
        ]
        assert await repo.subtree_has_foreign_content(1, MEMBER_ID) is False
        assert mock_db.execute.await_count == 4

    @pytest.mark.anyio
    async def test_subtree_foreign_subfolder_short_circuits(
        self, repo, mock_db
    ):
        mock_db.execute.side_effect = [_descendants(1, 2), _count_result(1)]
        assert await repo.subtree_has_foreign_content(1, MEMBER_ID) is True
        assert mock_db.execute.await_count == 2

    @pytest.mark.anyio
    async def test_subtree_foreign_media(self, repo, mock_db):
        mock_db.execute.side_effect = [
            _descendants(1),
            _count_result(0),
            _count_result(3),
        ]
        assert await repo.subtree_has_foreign_content(1, MEMBER_ID) is True

    @pytest.mark.anyio
    async def test_subtree_foreign_asset(self, repo, mock_db):
        mock_db.execute.side_effect = [
            _descendants(1),
            _count_result(0),
            _count_result(0),
            _count_result(1),
        ]
        assert await repo.subtree_has_foreign_content(1, MEMBER_ID) is True

    @pytest.mark.anyio
    async def test_subtree_missing_folder_is_clean(self, repo, mock_db):
        mock_db.execute.side_effect = [_descendants()]
        assert await repo.subtree_has_foreign_content(1, MEMBER_ID) is False
        assert mock_db.execute.await_count == 1

    @pytest.mark.anyio
    async def test_has_foreign_items_nothing_to_check(self, repo, mock_db):
        assert await repo.has_foreign_items([], [], 1, MEMBER_ID) is False
        mock_db.execute.assert_not_awaited()

    @pytest.mark.anyio
    async def test_has_foreign_items_all_owned(self, repo, mock_db):
        mock_db.execute.side_effect = [_count_result(0), _count_result(0)]
        assert await repo.has_foreign_items([1], [2], 1, MEMBER_ID) is False
        assert mock_db.execute.await_count == 2

    @pytest.mark.anyio
    async def test_has_foreign_items_media_foreign(self, repo, mock_db):
        mock_db.execute.side_effect = [_count_result(2)]
        assert await repo.has_foreign_items([1], [2], 1, MEMBER_ID) is True
        assert mock_db.execute.await_count == 1

    @pytest.mark.anyio
    async def test_has_foreign_items_asset_only(self, repo, mock_db):
        mock_db.execute.side_effect = [_count_result(1)]
        assert await repo.has_foreign_items([], [5], 1, MEMBER_ID) is True


# ---------------------------------------------------------------------------
# Controller wiring
# ---------------------------------------------------------------------------
@pytest.fixture(name="mock_folder_service")
def fixture_mock_folder_service():
    return AsyncMock()


@pytest.fixture(name="mock_workspace_auth")
def fixture_mock_workspace_auth():
    mock = AsyncMock()
    mock.authorize.return_value = _workspace(WorkspaceScopeEnum.PUBLIC)
    return mock


@pytest.fixture(name="override_dependencies")
def fixture_override_dependencies(
    mock_folder_service, mock_workspace_auth, mock_user
):
    app.dependency_overrides[FolderService] = lambda: mock_folder_service
    app.dependency_overrides[WorkspaceAuth] = lambda: mock_workspace_auth
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
    for dep in (FolderService, WorkspaceAuth, get_current_user):
        app.dependency_overrides.pop(dep, None)


FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail=FOLDER_NOT_OWNED_DETAIL
)


@pytest.mark.usefixtures("override_dependencies")
class TestControllerEnforcement:
    def test_delete_forbidden(
        self, api_client, mock_folder_service, mock_workspace_auth
    ):
        mock_folder_service.get_raw_folder.return_value = _folder(1, OTHER_ID)
        mock_folder_service.ensure_can_manage_folder.side_effect = FORBIDDEN

        response = api_client.delete("/api/folders/1")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == FOLDER_NOT_OWNED_DETAIL
        mock_folder_service.delete_folder.assert_not_called()
        kwargs = mock_folder_service.ensure_can_manage_folder.call_args.kwargs
        assert kwargs == {"check_subtree": True}
        args = mock_folder_service.ensure_can_manage_folder.call_args.args
        assert args[2] is mock_workspace_auth.authorize.return_value

    def test_rename_does_not_check_subtree(
        self, api_client, mock_folder_service
    ):
        mock_folder_service.get_raw_folder.return_value = _folder(
            1, OTHER_ID, parent_id=5
        )
        mock_folder_service.update_folder.return_value = {
            "id": 1,
            "workspace_id": 1,
            "user_email": "x@y.z",
            "name": "New",
            "parent_id": 5,
            "item_count": 0,
            "subfolder_count": 0,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }

        response = api_client.patch("/api/folders/1", json={"name": "New"})

        assert response.status_code == status.HTTP_200_OK
        kwargs = mock_folder_service.ensure_can_manage_folder.call_args.kwargs
        assert kwargs == {"check_subtree": False}

    def test_reparent_checks_subtree(self, api_client, mock_folder_service):
        mock_folder_service.get_raw_folder.return_value = _folder(
            1, OTHER_ID, parent_id=5
        )
        mock_folder_service.ensure_can_manage_folder.side_effect = FORBIDDEN

        response = api_client.patch("/api/folders/1", json={"parentId": 9})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        kwargs = mock_folder_service.ensure_can_manage_folder.call_args.kwargs
        assert kwargs == {"check_subtree": True}
        mock_folder_service.update_folder.assert_not_called()

    def test_reparent_to_same_parent_is_not_a_move(
        self, api_client, mock_folder_service
    ):
        mock_folder_service.get_raw_folder.return_value = _folder(
            1, OTHER_ID, parent_id=5
        )
        mock_folder_service.ensure_can_manage_folder.side_effect = FORBIDDEN

        api_client.patch("/api/folders/1", json={"parentId": 5, "name": "N"})

        kwargs = mock_folder_service.ensure_can_manage_folder.call_args.kwargs
        assert kwargs == {"check_subtree": False}

    def test_move_items_forbidden(self, api_client, mock_folder_service):
        mock_folder_service.ensure_can_move_items.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=ITEMS_NOT_OWNED_DETAIL
        )

        response = api_client.post(
            "/api/folders/move-items",
            json={
                "workspaceId": 1,
                "mediaItemIds": [1],
                "destinationFolderId": 3,
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == ITEMS_NOT_OWNED_DETAIL
        mock_folder_service.move_items.assert_not_called()
