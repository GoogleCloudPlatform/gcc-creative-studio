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
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Add src to pythonpath just in case
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/../"))

# Set environment for tests
os.environ["ENVIRONMENT"] = "local"

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
