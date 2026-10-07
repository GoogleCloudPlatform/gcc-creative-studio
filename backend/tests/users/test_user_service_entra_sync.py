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
"""Tests for Entra sign-in in UserService and the settings it relies on."""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.auth.entra_graph_client import EntraGraphError
from src.config.config_service import ConfigService
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService

ADMIN_G = "aaaaaaaa-0000-0000-0000-000000000001"
CREATOR_G = "cccccccc-0000-0000-0000-000000000002"
GRAPH_CREDENTIALS = {
    "ENTRA_TENANT_ID": "t",
    "ENTRA_GRAPH_CLIENT_ID": "c",
    "ENTRA_GRAPH_CLIENT_SECRET": "s",
}
OID_1 = "11111111-2222-3333-4444-555555555555"
OID_2 = "22222222-3333-4444-5555-666666666666"
NOW = datetime.datetime.now(datetime.UTC)


@pytest.fixture(name="config")
def fixture_config():
    cfg = SimpleNamespace(
        ENTRA_ROLE_SYNC_ENABLED=True,
        ENTRA_GROUP_ROLES={
            ADMIN_G: frozenset({"admin"}),
            CREATOR_G: frozenset({"creator"}),
        },
    )
    with patch("src.users.user_service.config_service", cfg):
        yield cfg


@pytest.fixture(name="graph")
def fixture_graph():
    client = MagicMock()
    client.member_group_ids = AsyncMock(return_value=set())
    client.get_user_emails = AsyncMock(return_value={"alice@corp.com"})
    with patch(
        "src.users.user_service.get_entra_graph_client", return_value=client
    ):
        yield client


@pytest.fixture(name="repo")
def fixture_repo():
    repo = AsyncMock()
    repo.update.side_effect = lambda uid, data: SimpleNamespace(id=uid, **data)
    repo.get_by_entra_oid.return_value = None
    return repo


def _user(roles, **overrides) -> UserModel:
    fields = {
        "id": 7,
        "email": "alice@corp.com",
        "name": "Alice",
        "roles": roles,
    }
    fields.update(overrides)
    return UserModel(**fields)


async def _call(repo, email="alice@corp.com", entra_oid=None, name="Alice"):
    return await UserService(user_repo=repo).create_user_if_not_exists(
        email=email, name=name, picture="", entra_oid=entra_oid
    )


@pytest.mark.usefixtures("config")
class TestNewUserRoles:
    @pytest.mark.anyio
    async def test_new_user_gets_roles_from_entra_groups(self, repo, graph):
        repo.get_by_email.return_value = None
        graph.member_group_ids.return_value = {CREATOR_G}

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["roles"] == ["user", "creator"]

    @pytest.mark.anyio
    async def test_new_user_groups_are_looked_up_by_entra_oid(
        self, repo, graph
    ):
        repo.get_by_email.return_value = None

        await _call(repo, entra_oid=OID_1)

        assert graph.member_group_ids.call_args.args[0] == OID_1

    @pytest.mark.anyio
    async def test_new_user_records_when_roles_were_checked(self, repo, graph):
        repo.get_by_email.return_value = None
        before = datetime.datetime.now(datetime.UTC)

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        after = datetime.datetime.now(datetime.UTC)
        assert before <= created["roles_checked_at"] <= after

    @pytest.mark.anyio
    async def test_new_user_defaults_to_user_when_graph_fails(
        self, repo, graph
    ):
        repo.get_by_email.return_value = None
        graph.member_group_ids.side_effect = EntraGraphError("down")

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["roles"] == ["user"]

    @pytest.mark.anyio
    async def test_email_is_lowercased_before_lookup_and_graph(
        self, repo, graph
    ):
        repo.get_by_email.return_value = None

        await _call(repo, email="  Alice@Corp.COM ")

        repo.get_by_email.assert_called_once_with(
            "alice@corp.com", include_deleted=True
        )
        assert graph.member_group_ids.call_args.args[0] == "alice@corp.com"


@pytest.mark.usefixtures("config")
class TestEntraObjectIdLookup:
    @pytest.mark.anyio
    async def test_lookup_by_entra_oid_takes_precedence_over_email(
        self, repo, graph
    ):
        user = _user(
            [UserRoleEnum.USER], email="original@corp.com", entra_oid=OID_1
        )
        repo.get_by_entra_oid.return_value = user

        result = await _call(repo, email="changed@corp.com", entra_oid=OID_1)

        assert result is user
        repo.get_by_entra_oid.assert_called_once_with(
            OID_1, include_deleted=True
        )
        repo.get_by_email.assert_not_called()

    @pytest.mark.anyio
    async def test_new_user_is_created_with_entra_oid(self, repo, graph):
        repo.get_by_email.return_value = None

        await _call(repo, entra_oid=OID_1.upper())

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["entra_oid"] == OID_1

    @pytest.mark.anyio
    async def test_unlinked_email_row_links_oid_after_graph_confirmation(
        self, repo, graph
    ):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], entra_oid=None
        )

        await _call(repo, email="alice@corp.com", entra_oid=OID_1)

        graph.get_user_emails.assert_called_once_with(OID_1)
        repo.update.assert_called_once_with(7, {"entra_oid": OID_1})

    @pytest.mark.anyio
    async def test_unlinked_email_row_rejected_403_when_graph_email_mismatch(
        self, repo, graph
    ):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER, UserRoleEnum.ADMIN], entra_oid=None
        )
        graph.get_user_emails.return_value = {"attacker@corp.com"}

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email="alice@corp.com", entra_oid=OID_1)

        assert exc_info.value.status_code == 403
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_unlinked_email_row_returns_503_when_graph_confirmation_fails(
        self, repo, graph
    ):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], entra_oid=None
        )
        graph.get_user_emails.side_effect = EntraGraphError("timeout")

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email="alice@corp.com", entra_oid=OID_1)

        assert exc_info.value.status_code == 503
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_email_row_already_linked_to_different_oid_is_rejected_403(
        self, repo, graph
    ):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], entra_oid=OID_2
        )

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email="alice@corp.com", entra_oid=OID_1)

        assert exc_info.value.status_code == 403
        graph.get_user_emails.assert_not_called()
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_unlinked_email_row_links_oid_when_sync_disabled(
        self, repo, graph, config
    ):
        config.ENTRA_ROLE_SYNC_ENABLED = False
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], entra_oid=None
        )

        await _call(repo, email="alice@corp.com", entra_oid=OID_1)

        graph.get_user_emails.assert_not_called()
        repo.update.assert_called_once_with(7, {"entra_oid": OID_1})

    @pytest.mark.anyio
    async def test_soft_deleted_user_is_forbidden(self, repo, graph):
        repo.get_by_entra_oid.return_value = _user(
            [UserRoleEnum.USER], entra_oid=OID_1, deleted_at=NOW
        )

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, entra_oid=OID_1)

        assert exc_info.value.status_code == 403


class TestEntraConfig:
    def _config(self, **env):
        return ConfigService(_env_file=None, PROJECT_ID="p", **env)

    def test_group_roles_are_lowercased_and_merged(self):
        cfg = self._config(
            ENTRA_ADMIN_GROUPS=f" {ADMIN_G.upper()} ,",
            ENTRA_CREATOR_GROUPS=f"{ADMIN_G},{CREATOR_G}",
        )

        assert cfg.ENTRA_GROUP_ROLES == {
            ADMIN_G: frozenset({"admin", "creator"}),
            CREATOR_G: frozenset({"creator"}),
        }

    def test_group_roles_are_parsed_once(self):
        cfg = self._config(ENTRA_ADMIN_GROUPS=ADMIN_G)
        roles = cfg.ENTRA_GROUP_ROLES

        assert cfg.ENTRA_GROUP_ROLES is roles

    def test_no_hardcoded_group_name_defaults(self):
        assert self._config().ENTRA_GROUP_ROLES == {}

    @pytest.mark.parametrize(
        "env, enabled",
        [
            pytest.param(GRAPH_CREDENTIALS, False, id="credentials-only"),
            pytest.param({"ENTRA_ADMIN_GROUPS": ADMIN_G}, False, id="groups"),
            pytest.param(
                {**GRAPH_CREDENTIALS, "ENTRA_ADMIN_GROUPS": ADMIN_G},
                True,
                id="credentials-and-groups",
            ),
        ],
    )
    def test_sync_enabled_requires_credentials_and_groups(self, env, enabled):
        assert self._config(**env).ENTRA_ROLE_SYNC_ENABLED is enabled
