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
"""Tests for the Entra role sync settings."""

import pytest

from src.config.config_service import ConfigService

ADMIN_G = "aaaaaaaa-0000-0000-0000-000000000001"
CREATOR_G = "cccccccc-0000-0000-0000-000000000002"
GRAPH_CREDENTIALS = {
    "ENTRA_TENANT_ID": "t",
    "ENTRA_GRAPH_CLIENT_ID": "c",
    "ENTRA_GRAPH_CLIENT_SECRET": "s",
}


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
