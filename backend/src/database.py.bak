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
"""Database configuration and session management."""


from collections.abc import AsyncGenerator
import asyncio
import asyncpg

from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config.config_service import config_service


# Define the base class for all SQLAlchemy models
class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get a database session."""
    async with async_session_local() as session:
        yield session


# --- Database Connection Logic ---


def get_conn_string() -> str:
    """Constructs the database connection string based on the environment."""
    # If running locally with a direct connection (e.g. docker-compose
    # postgres),
    # you might have a different URL.
    # For this setup, we assume we are either connecting to Cloud SQL via
    # the connector (Production/Dev) or a local Postgres instance.

    # Check if we are using the Cloud SQL Connector
    if config_service.USE_CLOUD_SQL_AUTH_PROXY:
        return (
            f"postgresql+asyncpg://{config_service.DB_USER}:"
            f"{config_service.DB_PASS}@"
            f"{config_service.DB_HOST}:{config_service.DB_PORT}"
            f"/{config_service.DB_NAME}"
        )

    # Default to using the Python Connector if INSTANCE_CONNECTION_NAME is set
    if config_service.INSTANCE_CONNECTION_NAME:
        return "postgresql+asyncpg://"

    # Fallback for local development without Cloud SQL
    return (
        f"postgresql+asyncpg://{config_service.DB_USER}:"
        f"{config_service.DB_PASS}@"
        f"{config_service.DB_HOST}:{config_service.DB_PORT}"
        f"/{config_service.DB_NAME}"
    )


class DatabaseConnector:
    """Singleton class to manage the Google Cloud SQL Connector."""

    _instance = None
    _connector: Connector | None = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_connector(self) -> Connector:
        if self._connector is None:
            # Explicitly use the running loop to avoid ConnectorLoopError
            # during asyncio.run()
            self._connector = Connector(loop=asyncio.get_running_loop())
        return self._connector

    async def cleanup(self):
        if self._connector:
            await self._connector.close_async()
            self._connector = None


async def get_connection():
    """Helper function to get a connection object for the AsyncEngine."""
    if config_service.USE_CLOUD_SQL_AUTH_PROXY:
        conn = await asyncpg.connect(
            user=config_service.DB_USER,
            password=config_service.DB_PASS,
            database=config_service.DB_NAME,
            host=config_service.DB_HOST,
            port=config_service.DB_PORT,
        )
        return conn

    # If no instance connection name is provided, assume we are connecting
    # directly to a local DB (or a DB specified by host/port) without the
    # Cloud SQL Connector.
    if not config_service.INSTANCE_CONNECTION_NAME:
        conn = await asyncpg.connect(
            user=config_service.DB_USER,
            password=config_service.DB_PASS,
            database=config_service.DB_NAME,
            host=config_service.DB_HOST,
            port=config_service.DB_PORT,
        )
        return conn

    connector = DatabaseConnector.get_instance().get_connector()

    conn = await connector.connect_async(
        config_service.INSTANCE_CONNECTION_NAME,
        "asyncpg",
        user=config_service.DB_USER,
        password=config_service.DB_PASS,
        db=config_service.DB_NAME,
        ip_type=IPTypes.PUBLIC,  # Adjust if using Private IP
    )

    return conn


async def cleanup_connector():
    """Closes the Connector to release resources."""
    await DatabaseConnector.get_instance().cleanup()


# Create the Async Engine
if (
    config_service.INSTANCE_CONNECTION_NAME
    and not config_service.USE_CLOUD_SQL_AUTH_PROXY
):
    # Use the Cloud SQL Python Connector
    engine = create_async_engine(
        "postgresql+asyncpg://",
        async_creator=get_connection,
        echo=config_service.LOG_LEVEL == "DEBUG",
    )
else:
    # Use standard connection string (Local)
    engine = create_async_engine(
        get_conn_string(),
        echo=config_service.LOG_LEVEL == "DEBUG",
    )

# Create the Session Factory
async_session_local = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class WorkerDatabase:
    """Context manager to provide a database session factory for worker
    threads. Ensures that a fresh Connector and Engine are created for the
    worker's event loop.
    """

    def __init__(self):
        self.connector: Connector | None = None
        self.engine = None
        self.sessionmaker = None

    async def __aenter__(self) -> async_sessionmaker[AsyncSession]:
        # Check if we need to use the Cloud SQL Connector
        if (
            config_service.INSTANCE_CONNECTION_NAME
            and not config_service.USE_CLOUD_SQL_AUTH_PROXY
        ):
            # Create a fresh Connector for the current (worker) loop
            self.connector = Connector(loop=asyncio.get_running_loop())

            async def get_conn():
                return await self.connector.connect_async(
                    config_service.INSTANCE_CONNECTION_NAME,
                    "asyncpg",
                    user=config_service.DB_USER,
                    password=config_service.DB_PASS,
                    db=config_service.DB_NAME,
                    ip_type=IPTypes.PUBLIC,
                )

            self.engine = create_async_engine(
                "postgresql+asyncpg://",
                async_creator=get_conn,
                echo=config_service.LOG_LEVEL == "DEBUG",
            )
        else:
            # Use standard connection string
            self.engine = create_async_engine(
                get_conn_string(),
                echo=config_service.LOG_LEVEL == "DEBUG",
            )

        self.sessionmaker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        return self.sessionmaker

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.engine:
            await self.engine.dispose()
        if self.connector:
            await self.connector.close_async()
