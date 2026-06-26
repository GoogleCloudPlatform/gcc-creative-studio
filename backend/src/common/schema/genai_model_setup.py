# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may
# obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import importlib.metadata
import logging

from google.genai import Client

from src.config.config_service import config_service

logger = logging.getLogger(__name__)


try:
    VERSION = importlib.metadata.version("creative-studio")
except importlib.metadata.PackageNotFoundError:
    VERSION = "0.1.0"


class GenAIModelSetup:
    """A base class to handle the initialization of a shared Google GenAI client.
    This uses a singleton pattern to ensure the client is only created once.
    """

    _client: Client | None = None

    @classmethod
    def get_client(cls) -> Client:
        """Initializes and returns a shared GenAI client instance for Vertex AI."""
        if cls._client is None:
            try:
                config = config_service
                project_id = config.PROJECT_ID
                location = config.LOCATION
                if None in [project_id, location]:
                    raise ValueError("All parameters must be set.")

                logger.info(
                    f"Initializing shared GenAI client for project '{project_id}' in location '{location}'",
                )

                cls._client = Client(
                    project=project_id,
                    location=location,
                    vertexai=config.INIT_VERTEX,
                    http_options={
                        "headers": {
                            "user-agent": f"creative-studio/{VERSION} (+https://github.com/GoogleCloudPlatform/gcc-creative-studio)"
                        }
                    },
                )
            except Exception as e:
                logger.error("Failed to initialize GenAI client: %s", e)
                raise
        return cls._client

    _omni_client: Client | None = None

    @classmethod
    def get_omni_client(cls) -> Client:
        """Initializes and returns a shared Omni GenAI client instance for Vertex AI."""
        if cls._omni_client is None:
            try:
                config = config_service
                project_id = config.PROJECT_ID
                if project_id is None:
                    raise ValueError("Project ID must be set.")

                logger.info(
                    f"Initializing shared Gemini Omni GenAI client for project '{project_id}' in location 'global'",
                )

                cls._omni_client = Client(
                    vertexai=True,
                    project=project_id,
                    location="global",
                    http_options={
                        "base_url": "https://aiplatform.googleapis.com",
                        "headers": {
                            "user-agent": f"creative-studio/{VERSION} (+https://github.com/GoogleCloudPlatform/gcc-creative-studio)"
                        },
                    },
                )
            except Exception as e:
                logger.error(
                    "Failed to initialize Gemini Omni GenAI client: %s", e
                )
                raise
        return cls._omni_client

    @staticmethod
    def init() -> Client:
        """Returns the shared client instance."""
        return GenAIModelSetup.get_client()
