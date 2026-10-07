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

from src.auth.entra_graph_client import (
    EntraGraphError,
    EntraUserNotFoundError,
)
from src.config.config_service import ConfigService
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService

ADMIN_G = "aaaaaaaa-0000-0000-0000-000000000001"
CREATOR_G = "cccccccc-0000-0000-0000-000000000002"
WORKFLOWS_G = "wwwwwwww-0000-0000-0000-000000000003"
GRAPH_CREDENTIALS = {
    "ENTRA_TENANT_ID": "t",
    "ENTRA_GRAPH_CLIENT_ID": "c",
    "ENTRA_GRAPH_CLIENT_SECRET": "s",
}
OID_1 = "11111111-2222-3333-4444-555555555555"
OID_2 = "22222222-3333-4444-5555-666666666666"
NOW = datetime.datetime.now(datetime.UTC)
STALE = NOW - datetime.timedelta(seconds=601)


@pytest.fixture(name="config")
def fixture_config():
    cfg = SimpleNamespace(
        ENTRA_ROLE_SYNC_ENABLED=True,
        ENTRA_ROLE_SYNC_TTL_SECONDS=600,
        ENTRA_GROUP_ROLES={
            ADMIN_G: frozenset({"admin"}),
            WORKFLOWS_G: frozenset({"workflows"}),
        },
        ADMIN_USER_EMAIL="system",
        ADMIN_USER_ENTRA_OID="",
        ALLOWED_ORGS=set(),
    )
    with patch("src.users.user_service.config_service", cfg):
        yield cfg


@pytest.fixture(name="graph")
def fixture_graph():
    client = MagicMock()
    client.member_group_ids = AsyncMock(return_value=set())
    client.get_user_emails = AsyncMock(return_value={"alice@corp.com"})
    client.get_user_profile = AsyncMock(
        return_value=("alice@corp.com", "Alice Graph", {"alice@corp.com"})
    )
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
        graph.member_group_ids.return_value = {WORKFLOWS_G}

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["roles"] == ["user", "workflows"]

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
class TestDeployerAdmin:
    """The break-glass admin is matched by Entra object ID, never by email."""

    @pytest.mark.anyio
    async def test_new_user_with_admin_entra_oid_gets_admin(
        self, repo, graph, config
    ):
        config.ADMIN_USER_ENTRA_OID = OID_1.upper()
        repo.get_by_email.return_value = None

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["roles"] == ["user", "admin"]

    @pytest.mark.anyio
    async def test_new_admin_needs_no_graph_email_check(
        self, repo, graph, config
    ):
        config.ADMIN_USER_ENTRA_OID = OID_1
        repo.get_by_email.return_value = None

        await _call(repo, entra_oid=OID_1)

        graph.get_user_emails.assert_not_called()

    @pytest.mark.anyio
    async def test_new_user_with_admin_email_but_other_oid_gets_no_admin(
        self, repo, graph, config
    ):
        config.ADMIN_USER_EMAIL = "alice@corp.com"
        config.ADMIN_USER_ENTRA_OID = OID_2
        repo.get_by_email.return_value = None

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["roles"] == ["user"]

    @pytest.mark.anyio
    async def test_no_break_glass_admin_when_admin_oid_is_unset(
        self, repo, graph, config
    ):
        config.ADMIN_USER_EMAIL = "alice@corp.com"
        repo.get_by_email.return_value = None

        await _call(repo, entra_oid=OID_1)

        created = repo.create_or_get_existing.call_args.args[0]
        assert created["roles"] == ["user"]

    @pytest.mark.anyio
    async def test_deployer_admin_is_never_demoted_when_removed_from_group(
        self, repo, graph, config
    ):
        config.ADMIN_USER_ENTRA_OID = OID_1
        repo.get_by_entra_oid.return_value = _user(
            [UserRoleEnum.USER, UserRoleEnum.ADMIN],
            entra_oid=OID_1,
            roles_checked_at=STALE,
        )

        await _call(repo, entra_oid=OID_1)

        _, data = repo.update.call_args.args
        assert "roles" not in data

    @pytest.mark.anyio
    async def test_deployer_keeps_admin_when_graph_sync_fails(
        self, repo, graph, config
    ):
        config.ADMIN_USER_ENTRA_OID = OID_1
        repo.get_by_entra_oid.return_value = _user(
            [
                UserRoleEnum.USER,
                UserRoleEnum.CREATOR,
                UserRoleEnum.ADMIN,
                UserRoleEnum.WORKFLOWS,
            ],
            entra_oid=OID_1,
            roles_checked_at=STALE,
        )
        graph.member_group_ids.side_effect = EntraGraphError("down")

        await _call(repo, entra_oid=OID_1)

        _, data = repo.update.call_args.args
        assert data["roles"] == ["user", "admin"]

    @pytest.mark.anyio
    async def test_admin_email_alone_does_not_keep_admin_when_graph_fails(
        self, repo, graph, config
    ):
        config.ADMIN_USER_EMAIL = "alice@corp.com"
        config.ADMIN_USER_ENTRA_OID = OID_2
        repo.get_by_entra_oid.return_value = _user(
            [UserRoleEnum.USER, UserRoleEnum.ADMIN],
            entra_oid=OID_1,
            roles_checked_at=STALE,
        )
        graph.member_group_ids.side_effect = EntraGraphError("down")

        await _call(repo, entra_oid=OID_1)

        _, data = repo.update.call_args.args
        assert data["roles"] == ["user"]

    @pytest.mark.anyio
    async def test_non_deployer_sole_admin_is_demoted_on_entra_path(
        self, repo, graph, config
    ):
        config.ADMIN_USER_ENTRA_OID = OID_2
        repo.get_by_entra_oid.return_value = _user(
            [UserRoleEnum.USER, UserRoleEnum.ADMIN],
            entra_oid=OID_1,
            roles_checked_at=STALE,
        )

        await _call(repo, entra_oid=OID_1)

        _, data = repo.update.call_args.args
        assert data["roles"] == ["user"]


@pytest.mark.usefixtures("config")
class TestRoleRecheck:
    @pytest.mark.anyio
    async def test_fresh_roles_skip_graph_and_writes(self, repo, graph):
        user = _user([UserRoleEnum.USER], roles_checked_at=NOW)
        repo.get_by_email.return_value = user

        assert await _call(repo) is user
        graph.member_group_ids.assert_not_called()
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_stale_promotion_updates_roles_once(self, repo, graph):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], roles_checked_at=STALE
        )
        graph.member_group_ids.return_value = {ADMIN_G}

        await _call(repo)

        repo.update.assert_called_once()
        uid, data = repo.update.call_args.args
        assert uid == 7
        assert data["roles"] == ["user", "admin"]

    @pytest.mark.anyio
    async def test_stale_check_records_new_check_time(self, repo, graph):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], roles_checked_at=STALE
        )
        before = datetime.datetime.now(datetime.UTC)

        await _call(repo)

        _, data = repo.update.call_args.args
        after = datetime.datetime.now(datetime.UTC)
        assert before <= data["roles_checked_at"] <= after

    @pytest.mark.anyio
    async def test_stale_unchanged_only_bumps_marker(self, repo, graph):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.ADMIN, UserRoleEnum.USER], roles_checked_at=STALE
        )
        graph.member_group_ids.return_value = {ADMIN_G}

        await _call(repo)

        _, data = repo.update.call_args.args
        assert set(data) == {"roles_checked_at"}

    @pytest.mark.anyio
    async def test_demotion_when_removed_from_group(self, repo, graph):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER, UserRoleEnum.CREATOR], roles_checked_at=None
        )

        await _call(repo)

        _, data = repo.update.call_args.args
        assert data["roles"] == ["user"]

    @pytest.mark.anyio
    async def test_graph_failure_removes_all_privileged_roles(
        self, repo, graph
    ):
        repo.get_by_email.return_value = _user(
            [
                UserRoleEnum.USER,
                UserRoleEnum.CREATOR,
                UserRoleEnum.ADMIN,
                UserRoleEnum.WORKFLOWS,
            ],
            roles_checked_at=STALE,
        )
        graph.member_group_ids.side_effect = EntraGraphError("down")

        await _call(repo)

        _, data = repo.update.call_args.args
        assert data["roles"] == ["user"]

    @pytest.mark.anyio
    async def test_graph_failure_still_records_check_time(self, repo, graph):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], roles_checked_at=STALE
        )
        graph.member_group_ids.side_effect = EntraGraphError("down")

        await _call(repo)

        _, data = repo.update.call_args.args
        assert data["roles_checked_at"] > STALE

    @pytest.mark.anyio
    async def test_sync_disabled_returns_existing_user(
        self, repo, graph, config
    ):
        config.ENTRA_ROLE_SYNC_ENABLED = False
        user = _user([UserRoleEnum.USER], roles_checked_at=None)
        repo.get_by_email.return_value = user

        assert await _call(repo) is user
        graph.member_group_ids.assert_not_called()
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_stale_unlinked_row_saves_link_and_roles_together(
        self, repo, graph
    ):
        repo.get_by_email.return_value = _user(
            [UserRoleEnum.USER], entra_oid=None, roles_checked_at=STALE
        )
        graph.member_group_ids.return_value = {ADMIN_G}

        await _call(repo, email="alice@corp.com", entra_oid=OID_1)

        assert graph.member_group_ids.call_args.args[0] == OID_1
        _, data = repo.update.call_args.args
        assert (data["entra_oid"], data["roles"]) == (OID_1, ["user", "admin"])


@pytest.mark.usefixtures("config")
class TestEntraObjectIdLookup:
    @pytest.mark.anyio
    async def test_lookup_by_entra_oid_takes_precedence_over_email(
        self, repo, graph
    ):
        user = _user(
            [UserRoleEnum.USER],
            email="original@corp.com",
            entra_oid=OID_1,
            roles_checked_at=NOW,
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
            [UserRoleEnum.USER], entra_oid=None, roles_checked_at=NOW
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


@pytest.mark.usefixtures("config")
class TestMissingEmail:
    @pytest.mark.anyio
    async def test_missing_email_creates_user_from_graph_profile(
        self, repo, graph
    ):
        repo.get_by_email.return_value = None
        graph.get_user_profile.return_value = (
            "alice@corp.com",
            "Alice From Graph",
            {"alice@corp.com", "alice.upn@corp.com"},
        )

        await _call(repo, email=None, entra_oid=OID_1, name="")

        created = repo.create_or_get_existing.call_args.args[0]
        assert (created["email"], created["name"], created["entra_oid"]) == (
            "alice@corp.com",
            "Alice From Graph",
            OID_1,
        )

    @pytest.mark.anyio
    async def test_missing_email_does_not_reconfirm_email_with_graph(
        self, repo, graph
    ):
        repo.get_by_email.return_value = None

        await _call(repo, email=None, entra_oid=OID_1, name="")

        graph.get_user_profile.assert_called_once_with(OID_1)
        graph.get_user_emails.assert_not_called()

    @pytest.mark.anyio
    async def test_missing_email_links_existing_row_under_another_email(
        self, repo, graph
    ):
        unlinked = _user(
            [UserRoleEnum.USER],
            email="alice.upn@corp.com",
            entra_oid=None,
            roles_checked_at=NOW,
        )
        repo.get_by_email.side_effect = lambda addr, include_deleted=False: {
            "alice.upn@corp.com": unlinked
        }.get(addr)
        graph.get_user_profile.return_value = (
            "alice@corp.com",
            "Alice",
            {"alice@corp.com", "alice.upn@corp.com"},
        )

        await _call(repo, email=None, entra_oid=OID_1, name="")

        repo.update.assert_called_once_with(7, {"entra_oid": OID_1})
        graph.get_user_emails.assert_not_called()

    @pytest.mark.anyio
    async def test_missing_email_with_existing_oid_row_skips_graph_profile(
        self, repo, graph
    ):
        existing = _user(
            [UserRoleEnum.USER], entra_oid=OID_1, roles_checked_at=NOW
        )
        repo.get_by_entra_oid.return_value = existing

        result = await _call(repo, email=None, entra_oid=OID_1, name="")

        assert result is existing
        graph.get_user_profile.assert_not_called()

    @pytest.mark.anyio
    async def test_missing_email_existing_oid_row_outside_allowed_orgs(
        self, repo, graph, config
    ):
        config.ALLOWED_ORGS = {"corp.com"}
        repo.get_by_entra_oid.return_value = _user(
            [UserRoleEnum.USER],
            email="alice@other.com",
            entra_oid=OID_1,
            roles_checked_at=NOW,
        )

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email=None, entra_oid=OID_1, name="")

        assert exc_info.value.status_code == 401

    @pytest.mark.anyio
    async def test_missing_email_returns_503_when_graph_profile_lookup_fails(
        self, repo, graph
    ):
        graph.get_user_profile.side_effect = EntraGraphError("timeout")

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email=None, entra_oid=OID_1, name="")

        assert exc_info.value.status_code == 503
        repo.create_or_get_existing.assert_not_called()

    @pytest.mark.parametrize(
        "profile_lookup",
        [
            pytest.param(
                AsyncMock(side_effect=EntraUserNotFoundError("404")),
                id="user-not-found",
            ),
            pytest.param(
                AsyncMock(return_value=(None, "No Email", set())),
                id="no-email-in-graph",
            ),
        ],
    )
    @pytest.mark.anyio
    async def test_missing_email_returns_403_when_graph_has_no_email(
        self, repo, graph, profile_lookup
    ):
        graph.get_user_profile = profile_lookup

        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email=None, entra_oid=OID_1, name="")

        assert exc_info.value.status_code == 403
        repo.create_or_get_existing.assert_not_called()

    @pytest.mark.anyio
    async def test_missing_email_without_entra_oid_is_rejected_401(
        self, repo, graph
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call(repo, email=None, name="")

        assert exc_info.value.status_code == 401


class TestEntraConfig:
    def _config(self, **env):
        return ConfigService(_env_file=None, PROJECT_ID="p", **env)

    def test_group_roles_are_lowercased_and_merged(self):
        cfg = self._config(
            ENTRA_ADMIN_GROUPS=f" {ADMIN_G.upper()} ,",
            ENTRA_WORKFLOWS_GROUPS=f"{ADMIN_G},{WORKFLOWS_G}",
        )

        assert cfg.ENTRA_GROUP_ROLES == {
            ADMIN_G: frozenset({"admin", "workflows"}),
            WORKFLOWS_G: frozenset({"workflows"}),
        }

    def test_creator_groups_setting_grants_no_role(self):
        # No endpoint checks the creator role, so Entra groups don't grant it.
        cfg = self._config(ENTRA_CREATOR_GROUPS=CREATOR_G)

        assert cfg.ENTRA_GROUP_ROLES == {}

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
