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
"""Tests for shared NullPool DB binding, hook cleanup, and socket guard."""

import socket

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import NullPool

from main import app
import src.database
from src.auth.auth_guard import get_post_auth_hooks, register_post_auth_hook
from src.workflows.queue import workflow_dispatcher
from src.workflows.queue.run_state_service import (
    get_dispatch_hook,
    set_dispatch_hook,
)


def test_conftest_configures_shared_nullpool_engine() -> None:
    """Suite binds async_session_local to one shared NullPool engine."""
    assert isinstance(src.database.engine.pool, NullPool)
    assert src.database.async_session_local.kw["bind"] is src.database.engine


def test_lifespan_teardown_clears_global_hooks() -> None:
    """Exiting TestClient(app) leaves zero dangling global hooks."""
    assert get_post_auth_hooks() == ()
    assert get_dispatch_hook() is None

    with TestClient(app):
        assert len(get_post_auth_hooks()) >= 1
        assert get_dispatch_hook() is not None

    assert get_post_auth_hooks() == ()
    assert get_dispatch_hook() is None


def test_fixture_resets_leaked_hooks_first_test() -> None:
    """Deliberately register hooks without cleanup to verify isolation."""
    register_post_auth_hook(lambda _u, _t, _e: None)
    set_dispatch_hook(lambda _rid, _sid=None: None)
    assert len(get_post_auth_hooks()) == 1
    assert get_dispatch_hook() is not None


def test_fixture_resets_leaked_hooks_second_test() -> None:
    """Prior test hooks must not leak into subsequent tests."""
    assert get_post_auth_hooks() == ()
    assert get_dispatch_hook() is None


def test_api_client_teardown_and_dispatcher_session_binding(api_client) -> None:
    """api_client fixture clears hooks on exit and binds dispatcher engine."""
    assert api_client is not None
    assert len(get_post_auth_hooks()) >= 1
    assert get_dispatch_hook() is not None
    assert (
        workflow_dispatcher.async_session_local.kw["bind"]
        is src.database.engine
    )


def test_hermetic_socket_guard_blocks_external_and_allows_loopback(
    tmp_path,
) -> None:
    """Socket guard blocks external IPs/DNS and allows loopback & AF_UNIX."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match="blocked outbound connection"):
            sock.connect(("8.8.8.8", 443))
        with pytest.raises(RuntimeError, match="blocked outbound connection"):
            sock.connect_ex(("8.8.8.8", 443))
        with pytest.raises(RuntimeError, match="blocked outbound connection"):
            sock.connect(("example.com", 443))

    with pytest.raises(RuntimeError, match="blocked DNS lookup"):
        socket.getaddrinfo("www.googleapis.com", 443)
    assert socket.getaddrinfo("localhost", 5432, socket.AF_INET)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cli:
            cli.connect(("127.0.0.1", port))

    sock_path = str(tmp_path / "hermetic.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as unix_srv:
        unix_srv.bind(sock_path)
        unix_srv.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as unix_cli:
            unix_cli.connect(sock_path)


def test_hermetic_socket_guard_allows_configured_db_host(monkeypatch) -> None:
    """Configured DB_HOST (Docker postgres) is permitted while external hosts stay blocked."""
    monkeypatch.setenv("DB_HOST", "postgres")
    try:
        socket.getaddrinfo("postgres", 5432, socket.AF_INET)
    except OSError as exc:
        assert not isinstance(exc, RuntimeError)
    with pytest.raises(RuntimeError, match="blocked DNS lookup"):
        socket.getaddrinfo("example.com", 443)
