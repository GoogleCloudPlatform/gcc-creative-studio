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
"""Adversarial tests for Database Migrations Runner."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.database_migrations import run_pending_migrations, MIGRATION_LOCK_ID


@pytest.mark.anyio
async def test_migration_runner_lock_acquisition_and_release():
    """Verifies that the runner acquires the pg advisory lock, runs migrations,
    and releases the lock on success.
    """
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"Running upgrade 0a1b2c...", b"")

    with (
        patch(
            "src.database_migrations.get_connection",
            AsyncMock(return_value=mock_conn),
        ),
        patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_process),
        ),
    ):
        await run_pending_migrations()

        # Check advisory lock was acquired
        mock_conn.execute.assert_any_call(
            "SELECT pg_advisory_lock($1)", MIGRATION_LOCK_ID
        )
        # Check advisory lock was released
        mock_conn.execute.assert_any_call(
            "SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_ID
        )
        # Check connection was closed
        mock_conn.close.assert_called_once()


@pytest.mark.anyio
async def test_migration_runner_release_lock_on_failure():
    """Verifies that the runner releases the advisory lock and closes the connection
    even if the migrations subprocess fails.
    """
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.returncode = 1  # Subprocess fails
    mock_process.communicate.return_value = (b"", b"Alembic error occurred")

    with (
        patch(
            "src.database_migrations.get_connection",
            AsyncMock(return_value=mock_conn),
        ),
        patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_process),
        ),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            await run_pending_migrations()

        assert "Database migrations failed." in str(exc_info.value)

        # Advisory lock must still be released in finally block
        mock_conn.execute.assert_any_call(
            "SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_ID
        )
        mock_conn.close.assert_called_once()


@pytest.mark.anyio
async def test_migration_runner_exception_in_lock_acquisition():
    """Verifies behavior when database connection fails during advisory lock acquisition."""
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = Exception("Database is unreachable")

    with (
        patch(
            "src.database_migrations.get_connection",
            AsyncMock(return_value=mock_conn),
        ),
        patch("asyncio.create_subprocess_exec") as mock_exec,
    ):
        with pytest.raises(Exception) as exc_info:
            await run_pending_migrations()

        assert "Database is unreachable" in str(exc_info.value)

        # Subprocess should not have been called since lock acquisition failed
        mock_exec.assert_not_called()

        # Lock should be unlocked and connection closed
        mock_conn.execute.assert_any_call(
            "SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_ID
        )
        mock_conn.close.assert_called_once()


@pytest.mark.anyio
async def test_migration_runner_exception_in_lock_release():
    """Verifies that the connection is closed even if advisory lock release raises an exception."""
    mock_conn = AsyncMock()

    # We want lock acquisition to succeed, but lock release to fail.
    async def mock_execute(query, *args):
        if "pg_advisory_unlock" in query:
            raise Exception("Unlock failed")
        return None

    mock_conn.execute.side_effect = mock_execute

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"Running upgrade 0a1b2c...", b"")

    with (
        patch(
            "src.database_migrations.get_connection",
            AsyncMock(return_value=mock_conn),
        ),
        patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_process),
        ),
    ):
        await run_pending_migrations()

        # Check lock unlock was attempted
        mock_conn.execute.assert_any_call(
            "SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_ID
        )
        # Connection must still be closed
        mock_conn.close.assert_called_once()
