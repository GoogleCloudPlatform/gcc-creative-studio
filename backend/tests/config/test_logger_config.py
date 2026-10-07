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
"""Tests for how the app writes its logs on and off Cloud Run."""

import json
import logging

import pytest

from src.config.logger_config import setup_logging


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Puts the root logger back as it was, so other tests are unaffected."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_on_cloud_run_logs_are_one_json_line_with_severity(monkeypatch, capsys):
    monkeypatch.setenv("K_SERVICE", "cstudio-be")
    monkeypatch.setenv("ENVIRONMENT", "development")
    setup_logging()

    logging.getLogger("demo").error(
        "Role sync failed for %s",
        "alice@example.com",
        extra={"json_fields": {"event_type": "entra_role_sync_failed"}},
    )

    entry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert entry["severity"] == "ERROR"
    assert entry["event_type"] == "entra_role_sync_failed"
    assert entry["message"] == "Role sync failed for alice@example.com"


def test_off_cloud_run_logs_stay_readable_text(monkeypatch, capsys):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    setup_logging()

    logging.getLogger("demo").error("Role sync failed")

    assert " - demo - ERROR - Role sync failed" in capsys.readouterr().err
