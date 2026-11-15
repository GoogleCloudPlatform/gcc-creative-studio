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
"""Fixtures isolating admin tests from process-wide global hooks."""

import pytest

from src.auth.auth_guard import clear_post_auth_hooks
from src.workflows.queue.run_state_service import set_dispatch_hook


@pytest.fixture(autouse=True)
def fixture_reset_global_hooks():
    """Clear process-wide auth and workflow dispatch hooks around each test."""
    clear_post_auth_hooks()
    set_dispatch_hook(None)
    yield
    clear_post_auth_hooks()
    set_dispatch_hook(None)
