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
"""Tests for Database."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.cloud.sql.connector import IPTypes

from src.config.config_service import config_service
from src.database import (
    DatabaseConnector,
    WorkerDatabase,
    cleanup_connector,
    get_conn_string,
    get_connection,
    get_db,
)


def test_get_conn_string_proxy():
    with patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", True):
        with (
            patch.object(config_service, "DB_USER", "u"),
            patch.object(
                config_service,
                "DB_PASS",
                "p",
            ),
            patch.object(config_service, "DB_HOST", "h"),
            patch.object(
                config_service,
                "DB_PORT",
                "5432",
            ),
            patch.object(
                config_service,
                "DB_NAME",
                "d",
            ),
        ):
            res = get_conn_string()
            assert "u:p@h:5432/d" in res


def test_get_conn_string_instance():
    with (
        patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", False),
        patch.object(
            config_service,
            "INSTANCE_CONNECTION_NAME",
            "inst",
        ),
    ):
        res = get_conn_string()
        assert res == "postgresql+asyncpg://"


def test_get_conn_string_fallback():
    with (
        patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", False),
        patch.object(
            config_service,
            "INSTANCE_CONNECTION_NAME",
            None,
        ),
        patch.object(config_service, "DB_USER", "u"),
        patch.object(
            config_service,
            "DB_PASS",
            "p",
        ),
        patch.object(config_service, "DB_HOST", "h"),
        patch.object(
            config_service,
            "DB_PORT",
            "5432",
        ),
        patch.object(
            config_service,
            "DB_NAME",
            "d",
        ),
    ):
        res = get_conn_string()
        assert "u:p@h:5432/d" in res


@pytest.mark.anyio
async def test_get_connection_proxy():
    with patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", True):
        with patch("asyncpg.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = "mock_conn_proxy"
            res = await get_connection()
            assert res == "mock_conn_proxy"


@pytest.mark.anyio
async def test_get_connection_local_no_instance():
    with (
        patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", False),
        patch.object(
            config_service,
            "INSTANCE_CONNECTION_NAME",
            None,
        ),
        patch("asyncpg.connect", new_callable=AsyncMock) as mock_connect,
    ):
        mock_connect.return_value = "mock_conn_local"
        res = await get_connection()
        assert res == "mock_conn_local"


@pytest.mark.anyio
async def test_get_connection_cloud_sql():
    with (
        patch.object(config_service, "USE_CLOUD_SQL_AUTH_PROXY", False),
        patch.object(
            config_service,
            "INSTANCE_CONNECTION_NAME",
            "projects/p/locations/l/instances/i",
        ),
        patch.object(config_service, "CLOUD_SQL_IP_TYPE", "PRIVATE"),
    ):
        mock_connector = AsyncMock()
        mock_connector.connect_async = AsyncMock(return_value="cloud_conn")

        # Patch DatabaseConnector singleton get_instance
        with patch.object(DatabaseConnector, "get_instance") as mock_inst:
            mock_inst_obj = MagicMock()
            mock_inst_obj.get_connector.return_value = mock_connector
            mock_inst.return_value = mock_inst_obj

            res = await get_connection()
            assert res == "cloud_conn"
            mock_connector.connect_async.assert_awaited_once_with(
                "projects/p/locations/l/instances/i",
                "asyncpg",
                user=config_service.DB_USER,
                password=config_service.DB_PASS,
                db=config_service.DB_NAME,
                ip_type=IPTypes.PRIVATE,
            )


@pytest.mark.anyio
async def test_cleanup_connector():
    with patch.object(DatabaseConnector, "get_instance") as mock_inst:
        mock_inst_obj = MagicMock()
        mock_inst_obj.cleanup = AsyncMock()
        mock_inst.return_value = mock_inst_obj

        await cleanup_connector()
        mock_inst_obj.cleanup.assert_called_once()


@pytest.mark.anyio
async def test_worker_database_local():
    with patch.object(config_service, "INSTANCE_CONNECTION_NAME", None):
        # WorkerDatabase creates Engine and sessionmaker
        async with WorkerDatabase() as sessionmaker:
            assert sessionmaker is not None


@pytest.mark.anyio
async def test_worker_database_cloud_sql():
    with (
        patch.object(config_service, "INSTANCE_CONNECTION_NAME", "inst"),
        patch.object(
            config_service,
            "USE_CLOUD_SQL_AUTH_PROXY",
            False,
        ),
    ):
        # We need to mock the Connector itself that gets initialized inside __aenter__
        # Or mock the AsyncEngine creation inside
        with (
            patch("src.database.create_async_engine") as mock_create_engine,
            patch(
                "src.database.Connector",
            ) as mock_connector_cls,
        ):
            mock_create_engine.return_value = AsyncMock()
            mock_connector_inst = MagicMock()
            mock_connector_inst.close_async = AsyncMock()
            mock_connector_cls.return_value = mock_connector_inst

            async with WorkerDatabase() as sessionmaker:
                assert sessionmaker is not None


def test_database_connector_singleton():
    inst1 = DatabaseConnector.get_instance()
    inst2 = DatabaseConnector.get_instance()
    assert inst1 is inst2


def test_get_db_yields():
    # get_db is AsyncGenerator
    gen = get_db()
    assert gen is not None
