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
"""Tests for Veo Service bugs."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.common.base_dto import GenerationModelEnum
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    MediaItemModel,
    MimeTypeEnum,
    SourceMediaItemLink,
    JobStatusEnum,
)
from src.videos.dto.create_veo_dto import CreateVeoDto
from src.videos.veo_service import _process_video_in_background


class TestVeoServiceOmniUploadFailure:

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.get_omni_client")
    @patch("src.videos.veo_service.generate_thumbnail")
    @pytest.mark.xfail(
        reason="Exposes Omni upload failure bug in veo_service.py"
    )
    def test_process_video_in_background_omni_upload_failure(
        self,
        mock_thumb,
        mock_omni_client_init,
        mock_worker_db_class,
    ):
        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test Omni",
            generation_model=GenerationModelEnum.GEMINI_OMNI,
            aspect_ratio="16:9",
            duration_seconds=5,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=10,
                    media_index=0,
                    role=AssetRoleEnum.START_FRAME,
                ),
            ],
        )

        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_vertex_client = MagicMock()
        mock_omni_client_init.return_value = mock_vertex_client

        # Mock Interaction response
        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-abc"
        mock_step = MagicMock()
        mock_step.type = "model_output"
        mock_content = MagicMock()
        mock_content.type = "video"
        mock_content.data = "ZmFrZS1vbW5pLXZpZGVvLWJ5dGVz"  # base64 string of b"fake-omni-video-bytes"
        mock_content.mime_type = "video/mp4"
        mock_step.content = [mock_content]
        mock_interaction.steps = [mock_step]
        mock_vertex_client.interactions.create.return_value = mock_interaction

        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
            patch(
                "src.system_settings.repository.system_settings_repository.SystemSettingsRepository",
            ) as mock_settings_repo_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_settings_repo = AsyncMock()
            mock_settings_repo_class.return_value = mock_settings_repo
            mock_settings_repo.get_by_id.return_value = None

            mock_item1 = MediaItemModel(
                id=10,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.IMAGE_PNG,
                model=GenerationModelEnum.IMAGEN_3_001,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/10.png"],
                thumbnail_uris=[],
            )
            mock_media_repo.get_by_id.side_effect = [mock_item1]

            mock_gcs_service = MagicMock()
            mock_gcs_class.return_value = mock_gcs_service
            mock_gcs_service.download_from_gcs.return_value = "/tmp/local.mp4"

            # Simulate upload failure by returning None
            mock_gcs_service.upload_file_to_gcs.return_value = None

            _process_video_in_background(
                media_item_id=1234,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            # The job should have failed because upload failed
            mock_media_repo.update.assert_called_once()
            call_args = mock_media_repo.update.call_args
            assert call_args is not None
            updated_data = call_args[0][
                1
            ]  # Get the second argument (update_data)
            assert updated_data["status"] == JobStatusEnum.FAILED
            assert "Failed to upload" in updated_data["error_message"]
