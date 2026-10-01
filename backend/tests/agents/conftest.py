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
"""Shared fixtures for the agent tests."""

from unittest.mock import patch

import pytest

from src.config.config_service import config_service


@pytest.fixture(autouse=True)
def default_agent_backend():
    """Runs every agent test against Agent Engine unless it opts into "local".

    A developer's backend/.env may set AGENT_BACKEND=local to use a local Izumi
    container; without this pin, the Agent Engine tests would silently switch
    to the local client and fail.
    """
    with patch.object(config_service, "AGENT_BACKEND", "agent_engine"):
        yield
