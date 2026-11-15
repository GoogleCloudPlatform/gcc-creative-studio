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
"""Module for Conftest."""


import os
import socket
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# Add src to pythonpath just in case
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/../"))

# Set environment for tests
os.environ["ENVIRONMENT"] = "local"
os.environ["AGENT_ENGINE_RESOURCE_NAME"] = (
    "projects/mock/locations/mock/reasoningEngines/mock"
)
# ENVIRONMENT=local would route AgentService to the local Izumi container;
# keep the suite on the Vertex path (local-mode tests patch this explicitly).
os.environ["USE_LOCAL_IZUMI_AGENT"] = "false"

import google.auth

mock_creds = MagicMock()
mock_creds.universe_domain = "googleapis.com"
google.auth.default = MagicMock(return_value=(mock_creds, "dummy-project-id"))

# Mock ProjectsClient to prevent live API calls during startup validation check
from google.cloud import resourcemanager_v3

resourcemanager_v3.ProjectsClient = MagicMock()


# 1. Patch database migrations BEFORE importing app to avoid lifespan triggering them
@pytest.fixture(name="mock_migrations", scope="session", autouse=True)
def fixture_mock_migrations():
    """Bypasses database migrations during startup."""
    with patch(
        "src.database_migrations.run_pending_migrations", AsyncMock()
    ) as mock:
        yield mock


# Share one NullPool async engine across all test suites so event-loop switches
# never reuse stale pooled asyncpg connections when e2e and unit tests run together.
import src.database

if not isinstance(src.database.engine.pool, NullPool):
    _test_engine = create_async_engine(
        src.database.get_conn_string(),
        poolclass=NullPool,
        echo=src.database.config_service.LOG_LEVEL == "DEBUG",
    )
    src.database.engine = _test_engine
    src.database.async_session_local.configure(bind=_test_engine)


@pytest.fixture(autouse=True)
def fixture_reset_global_hooks():
    """Clear process-wide auth and workflow dispatch hooks around each test."""
    from src.auth.auth_guard import clear_post_auth_hooks
    from src.workflows.queue.run_state_service import set_dispatch_hook
    from src.workflows.queue.workflow_dispatcher import (
        reset_dispatch_tick_throttle,
    )

    clear_post_auth_hooks()
    set_dispatch_hook(None)
    reset_dispatch_tick_throttle()
    yield
    clear_post_auth_hooks()
    set_dispatch_hook(None)
    reset_dispatch_tick_throttle()


@pytest.fixture(autouse=True)
def _block_external_network_in_unit_tests(request, monkeypatch):
    """Block unintended outbound network connections in non-e2e unit tests."""
    fspath = str(request.node.fspath).replace("\\", "/")
    if "tests/e2e" in fspath:
        return
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo
    resolved_db_ips: set[str] = set()

    def _allowed_hosts() -> set[str]:
        hosts = {"127.0.0.1", "::1", "localhost"}
        db_host = os.environ.get("DB_HOST", "").strip()
        if db_host:
            hosts.add(db_host)
        return hosts

    def _check_target(address):
        if isinstance(address, (str, bytes)):
            return
        if (
            isinstance(address, tuple)
            and address
            and (
                address[0] in _allowed_hosts() or address[0] in resolved_db_ips
            )
        ):
            return
        raise RuntimeError(
            f"Hermetic unit test blocked outbound connection to {address!r}; "
            "mock the external client."
        )

    def _guarded_connect(self, address):
        _check_target(address)
        return orig_connect(self, address)

    def _guarded_connect_ex(self, address):
        _check_target(address)
        return orig_connect_ex(self, address)

    def _guarded_getaddrinfo(host, port, *args, **kwargs):
        host_val = host.decode() if isinstance(host, bytes) else host
        allowed = _allowed_hosts()
        if host_val not in (None, "", *allowed):
            raise RuntimeError(
                f"Hermetic unit test blocked DNS lookup for {host!r}; "
                "mock the external client."
            )
        results = orig_getaddrinfo(host, port, *args, **kwargs)
        db_host = os.environ.get("DB_HOST", "").strip()
        if db_host and host_val == db_host:
            for entry in results:
                sockaddr = entry[4]
                if isinstance(sockaddr, tuple) and sockaddr:
                    resolved_db_ips.add(str(sockaddr[0]))
        return results

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)


from main import app
from src.auth.auth_guard import get_current_user
from src.database import get_db
from src.users.user_model import UserModel, UserRoleEnum

# --- User Model Fixtures ---


@pytest.fixture(name="mock_user")
def fixture_mock_user():
    """Provides a mock regular user."""
    return UserModel(
        id=1,
        email="user@example.com",
        roles=[UserRoleEnum.USER],
        name="Regular User",
        picture="http://example.com/user.jpg",
    )


@pytest.fixture(name="mock_admin")
def fixture_mock_admin():
    """Provides a mock admin user."""
    return UserModel(
        id=2,
        email="admin@example.com",
        roles=[UserRoleEnum.ADMIN],
        name="Admin User",
        picture="http://example.com/admin.jpg",
    )


@pytest.fixture(name="mock_creator")
def fixture_mock_creator():
    """Provides a mock creator user."""
    return UserModel(
        id=3,
        email="creator@example.com",
        roles=[UserRoleEnum.CREATOR],
        name="Creator User",
        picture="http://example.com/creator.jpg",
    )


# --- Database Fixtures ---


@pytest.fixture(name="db_session_mock")
def fixture_db_session_mock():
    """Provides a mock AsyncSession."""
    return AsyncMock()


# --- API Client Fixtures ---


def _create_api_client(user_model, db_mock):
    """Helper to create a TestClient with overridden dependencies."""

    def override_get_current_user():
        return user_model

    async def override_get_db():
        yield db_mock

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    # We use a context manager to trigger lifespan events
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(name="api_client")
def fixture_api_client(mock_user, db_session_mock):
    """Provides a TestClient authenticated as a regular USER."""
    yield from _create_api_client(mock_user, db_session_mock)


@pytest.fixture(name="admin_client")
def fixture_admin_client(mock_admin, db_session_mock):
    """Provides a TestClient authenticated as an ADMIN."""
    yield from _create_api_client(mock_admin, db_session_mock)


@pytest.fixture(name="creator_client")
def fixture_creator_client(mock_creator, db_session_mock):
    """Provides a TestClient authenticated as a CREATOR."""
    yield from _create_api_client(mock_creator, db_session_mock)
