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
"""Tests for Veo Service."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.base_dto import GenerationModelEnum
from src.common.schema.media_item_model import (
    MediaItemModel,
    MimeTypeEnum,
)
from src.users.user_model import UserModel
from src.videos.dto.concatenate_videos_dto import (
    ConcatenateVideosDto,
    ConcatenationInput,
)
from src.videos.dto.create_veo_dto import CreateVeoDto
from src.videos.veo_service import (
    VeoService,
    _process_video_concatenation_in_background,
    _process_video_in_background,
)


@pytest.fixture(name="mock_media_repo")
def fixture_mock_media_repo():
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.update = AsyncMock()
    return repo


@pytest.fixture(name="mock_source_asset_repo")
def fixture_mock_source_asset_repo():
    repo = AsyncMock()
    repo.get_by_id = AsyncMock()
    return repo


@pytest.fixture(name="mock_gemini_service")
def fixture_mock_gemini_service():
    service = AsyncMock()
    service.enhance_prompt_from_dto = AsyncMock(return_value="Enhanced Prompt")
    return service


@pytest.fixture(name="mock_gcs_service")
def fixture_mock_gcs_service():
    service = AsyncMock()
    service.download_from_gcs = AsyncMock(return_value="/tmp/local_video.mp4")
    service.upload_file_to_gcs = AsyncMock(
        return_value="gs://bucket/uploaded.mp4"
    )
    return service


@pytest.fixture(name="veo_service")
def fixture_veo_service(
    mock_media_repo,
    mock_source_asset_repo,
    mock_gemini_service,
    mock_gcs_service,
):
    return VeoService(
        media_repo=mock_media_repo,
        source_asset_repo=mock_source_asset_repo,
        gemini_service=mock_gemini_service,
        gcs_service=mock_gcs_service,
        iam_signer_credentials=MagicMock(),
    )


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.fixture(name="sample_create_veo_dto")
def fixture_sample_create_veo_dto():
    return CreateVeoDto(
        workspace_id=1,
        prompt="A cute cat running",
        generation_model=GenerationModelEnum.VEO_3_QUALITY,
        aspect_ratio="16:9",
        duration_seconds=5,
        enhance_prompt=True,
    )


class TestVeoServiceMethods:
    """Tests for VeoService wrapper methods."""

    @pytest.mark.anyio
    async def test_start_video_generation_job_success(
        self,
        veo_service,
        mock_media_repo,
        sample_create_veo_dto,
        sample_user,
    ):
        # Setup
        placeholder = MediaItemModel(
            id=123,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.VIDEO_MP4,
            model=GenerationModelEnum.VEO_3_QUALITY,
            aspect_ratio="16:9",
            gcs_uris=[],
            thumbnail_uris=[],
        )

        mock_media_repo.create.return_value = placeholder

        mock_executor = MagicMock()

        response = await veo_service.start_video_generation_job(
            request_dto=sample_create_veo_dto,
            user=sample_user,
            executor=mock_executor,
        )

        assert response is not None
        assert response.id == 123
        mock_media_repo.create.assert_called_once()
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_start_video_concatenation_job_success(
        self,
        veo_service,
        mock_media_repo,
        sample_user,
    ):
        request_dto = ConcatenateVideosDto(
            workspace_id=1,
            name="Concat Video",
            inputs=[
                ConcatenationInput(type="media_item", id=1),
                ConcatenationInput(type="media_item", id=2),
            ],
        )
        # Setup
        placeholder = MediaItemModel(
            id=456,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.VIDEO_MP4,
            model=GenerationModelEnum.VEO_3_QUALITY,
            aspect_ratio="16:9",
            gcs_uris=[],
            thumbnail_uris=[],
        )
        mock_item = MediaItemModel(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.VIDEO_MP4,
            model=GenerationModelEnum.VEO_3_QUALITY,
            aspect_ratio="16:9",
            gcs_uris=["gs://b/1.mp4"],
            thumbnail_uris=[],
        )
        mock_media_repo.get_by_id.side_effect = [mock_item, mock_item]
        mock_media_repo.create.return_value = placeholder
        mock_executor = MagicMock()
        response = await veo_service.start_video_concatenation_job(
            request_dto=request_dto,
            user=sample_user,
            executor=mock_executor,
        )
        assert response is not None
        assert response.id == 456
        mock_media_repo.create.assert_called_once()
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_start_video_concatenation_job_invalid_mime_type(
        self,
        veo_service,
        mock_media_repo,
        sample_user,
    ):
        request_dto = ConcatenateVideosDto(
            workspace_id=1,
            name="Concat Video",
            inputs=[
                ConcatenationInput(type="media_item", id=1),
                ConcatenationInput(type="media_item", id=2),
            ],
        )
        # Setup
        mock_image_item = MediaItemModel(
            id=1,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.IMAGEN_3_001,
            aspect_ratio="16:9",
            gcs_uris=["gs://b/1.png"],
            thumbnail_uris=[],
        )
        mock_media_repo.get_by_id.return_value = mock_image_item
        mock_executor = MagicMock()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await veo_service.start_video_concatenation_job(
                request_dto=request_dto,
                user=sample_user,
                executor=mock_executor,
            )
        assert exc_info.value.status_code == 400
        assert "not a video" in exc_info.value.detail


class TestBackgroundWorkers:
    """Tests for long-running worker functions (called synchronously for testing)."""

    @pytest.mark.anyio
    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    @patch("src.videos.veo_service.generate_thumbnail")
    @patch(
        "src.common.storage_service.GcsService",
    )  # Need to patch the class inside the worker
    async def test_process_video_in_background_success(
        self,
        mock_gcs_class,
        mock_thumb,
        mock_genai_init,
        mock_worker_db_class,
        sample_create_veo_dto,
    ):
        # Mock WorkerDatabase Context
        mock_db_context = AsyncMock()
        mock_db_factory = AsyncMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        # Mock GenAI SDK setup
        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client

        # Mock Operations
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = None
        from src.config.config_service import config_service as cfg

        mock_generated_video = MagicMock()
        mock_generated_video.video.uri = (
            f"gs://{cfg.GENMEDIA_BUCKET}/output_0.mp4"
        )
        mock_operation.response.generated_videos = [mock_generated_video]

        # Async mock calls inside thread wrapper
        # We need to mock asyncio.to_thread behavior if needed, or just the called functions
        # client.models.generate_videos is called via asyncio.to_thread
        # So we mock it to return the operation immediately
        mock_client.models.generate_videos.return_value = mock_operation

        # Mock GcsService inside the worker
        mock_gcs_instance = MagicMock()
        mock_gcs_class.return_value = mock_gcs_instance
        mock_gcs_instance.download_from_gcs.return_value = "/tmp/local.mp4"
        mock_gcs_instance.upload_file_to_gcs.return_value = (
            "gs://bucket/thumb.png"
        )
        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        # Mock Repos inside the context
        # We need to patch MediaRepository which is instantiated inside
        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.SourceAssetRepository",
            ) as mock_source_asset_repo_class,
            patch(
                "src.videos.veo_service.GeminiService",
            ) as mock_gemini_service_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_gemini_service = AsyncMock()
            mock_gemini_service_class.return_value = mock_gemini_service
            mock_gemini_service.enhance_prompt_from_dto.return_value = (
                "Enhanced Prompt"
            )

            # Execute directly (Sync call is okay if patching runs or if it creates full isolated loop)
            # Since _process_video_in_background runs loop.run_until_complete inside,
            # we should run it from a synchronous test or mock that block.
            # Wait, running it from an async test (via anyio) might crash if line 110 runs.
            # Let's test calling it synchronously in a def test instead of async!

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_sync(
        self,
        mock_thumb,
        mock_genai_init,
        mock_worker_db_class,
    ):
        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test",
            generation_model=GenerationModelEnum.VEO_3_QUALITY,
            aspect_ratio="16:9",
            duration_seconds=5,
            enhance_prompt=True,
        )

        # Mock WorkerDatabase Context
        mock_db_context = AsyncMock()
        # Use MagicMock so calling it returns the context manager directly, not a coroutine
        mock_db_factory = MagicMock(return_value=mock_db_context)
        # Mock WorkerDatabase()() call -> mock_db_factory is return of WorkerDatabase(), which is called as AsyncContextManager

        # line 114: async with WorkerDatabase() as db_factory:
        # WorkerDatabase() returns instance. __aenter__ returns result.
        # So mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        # Mock GenAI SDK client
        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client

        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = None
        from src.config.config_service import config_service as cfg

        mock_generated_video = MagicMock()
        mock_generated_video.video.uri = (
            f"gs://{cfg.GENMEDIA_BUCKET}/output_0.mp4"
        )
        mock_operation.response.generated_videos = [mock_generated_video]

        mock_client.models.generate_videos.return_value = mock_operation
        mock_client.operations.get.return_value = (
            mock_operation  # For operation loop fallback
        )

        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        # Patch Repos inside _async_worker execution
        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.SourceAssetRepository",
            ) as mock_source_asset_repo_class,
            patch(
                "src.videos.veo_service.GeminiService",
            ) as mock_gemini_service_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_gemini_service = AsyncMock()
            mock_gemini_service_class.return_value = mock_gemini_service
            mock_gemini_service.enhance_prompt_from_dto.return_value = (
                "Enhanced Prompt"
            )

            mock_gcs_service = MagicMock()
            mock_gcs_class.return_value = mock_gcs_service
            mock_gcs_service.download_from_gcs.return_value = "/tmp/local.mp4"
            mock_gcs_service.upload_file_to_gcs.return_value = (
                "gs://bucket/uploaded.png"
            )

            # Execute the outer worker function
            # Since it creates a new isolated loop, calling it in a sync test is safe.
            _process_video_in_background(
                media_item_id=123,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            # Assertions
            mock_gemini_service.enhance_prompt_from_dto.assert_called_once()
            mock_client.models.generate_videos.assert_called_once()
            mock_media_repo.update.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.concatenate_videos")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_concatenation_in_background_sync(
        self,
        mock_thumb,
        mock_concat,
        mock_worker_db_class,
    ):
        from src.videos.dto.concatenate_videos_dto import (
            ConcatenateVideosDto,
            ConcatenationInput,
        )

        request_dto = ConcatenateVideosDto(
            workspace_id=1,
            name="Concat Video",
            inputs=[
                ConcatenationInput(type="media_item", id=1),
                ConcatenationInput(type="media_item", id=2),
            ],
        )

        # Mock WorkerDatabase Context
        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        mock_concat.return_value = "/tmp/concat.mp4"

        # Patch Repos inside execution
        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            # Setup mock assets to return for downloading
            mock_item1 = MediaItemModel(
                id=1,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.VIDEO_MP4,
                model=GenerationModelEnum.VEO_3_QUALITY,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/1.mp4"],
                thumbnail_uris=[],
            )
            mock_item2 = MediaItemModel(
                id=2,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.VIDEO_MP4,
                model=GenerationModelEnum.VEO_3_QUALITY,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/2.mp4"],
                thumbnail_uris=[],
            )

            # get_by_id side_effect to return items
            mock_media_repo.get_by_id.side_effect = [mock_item1, mock_item2]

            mock_gcs_service = MagicMock()
            mock_gcs_class.return_value = mock_gcs_service
            mock_gcs_service.download_from_gcs.return_value = "/tmp/local.mp4"
            mock_gcs_service.upload_file_to_gcs.return_value = (
                "gs://bucket/uploaded.mp4"
            )

            # Execute the outer worker function
            _process_video_concatenation_in_background(
                media_item_id=456,
                request_dto=request_dto,
            )

            # Assertions
            mock_concat.assert_called_once()
            mock_media_repo.update.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_with_references(
        self,
        mock_thumb,
        mock_genai_init,
        mock_worker_db_class,
    ):
        from src.common.base_dto import ReferenceImageTypeEnum
        from src.videos.dto.create_veo_dto import ReferenceImageDto

        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test",
            generation_model=GenerationModelEnum.VEO_3_1_PREVIEW,
            aspect_ratio="16:9",
            duration_seconds=5,
            reference_images=[
                ReferenceImageDto(
                    asset_id=1,
                    reference_type=ReferenceImageTypeEnum.ASSET,
                ),
            ],
            enhance_prompt=True,
        )

        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = None
        from src.config.config_service import config_service as cfg

        mock_generated_video = MagicMock()
        mock_generated_video.video.uri = (
            f"gs://{cfg.GENMEDIA_BUCKET}/output_0.mp4"
        )
        mock_operation.response.generated_videos = [mock_generated_video]

        mock_client.models.generate_videos.return_value = mock_operation
        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.SourceAssetRepository",
            ) as mock_source_asset_repo_class,
            patch(
                "src.videos.veo_service.GeminiService",
            ) as mock_gemini_service_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_source_repo = AsyncMock()
            mock_source_asset_repo_class.return_value = mock_source_repo

            mock_asset = MagicMock()
            mock_asset.gcs_uri = "gs://b/ref.jpg"
            mock_asset.mime_type = "image/jpeg"
            mock_source_repo.get_by_id.return_value = mock_asset

            mock_gemini_service = AsyncMock()
            mock_gemini_service_class.return_value = mock_gemini_service
            mock_gemini_service.enhance_prompt_from_dto.return_value = (
                "Enhanced Prompt"
            )

            mock_gcs_service = MagicMock()
            mock_gcs_class.return_value = mock_gcs_service
            mock_gcs_service.download_from_gcs.return_value = "/tmp/local.mp4"
            mock_gcs_service.upload_file_to_gcs.return_value = (
                "gs://bucket/uploaded.png"
            )

            _process_video_in_background(
                media_item_id=123,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_source_repo.get_by_id.assert_called_once_with(1)
            mock_client.models.generate_videos.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    def test_process_video_in_background_error(
        self,
        mock_genai_init,
        mock_worker_db_class,
    ):
        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test",
            generation_model=GenerationModelEnum.VEO_3_QUALITY,
        )

        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client

        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = "Test Generation Error"
        mock_client.models.generate_videos.return_value = mock_operation

        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            _process_video_in_background(
                media_item_id=123,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_with_source_media_items(
        self,
        mock_thumb,
        mock_genai_init,
        mock_worker_db_class,
    ):
        from src.common.schema.media_item_model import (
            AssetRoleEnum,
            MediaItemModel,
            MimeTypeEnum,
            SourceMediaItemLink,
        )

        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test",
            generation_model=GenerationModelEnum.VEO_3_1_PREVIEW,
            aspect_ratio="16:9",
            duration_seconds=5,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=1,
                    media_index=0,
                    role=AssetRoleEnum.START_FRAME,
                ),
                SourceMediaItemLink(
                    media_item_id=2,
                    media_index=0,
                    role=AssetRoleEnum.END_FRAME,
                ),
            ],
        )

        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = None
        from src.config.config_service import config_service as cfg

        mock_generated_video = MagicMock()
        mock_generated_video.video.uri = (
            f"gs://{cfg.GENMEDIA_BUCKET}/output_0.mp4"
        )
        mock_operation.response.generated_videos = [mock_generated_video]

        mock_client.models.generate_videos.return_value = mock_operation
        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_item1 = MediaItemModel(
                id=1,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.IMAGE_PNG,
                model=GenerationModelEnum.IMAGEN_3_001,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/1.png"],
                thumbnail_uris=[],
            )
            # Async mock get_by_id to return items
            mock_media_repo.get_by_id.side_effect = [mock_item1, mock_item1]

            _process_video_in_background(
                media_item_id=123,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_with_source_media_items_extensions(
        self,
        mock_thumb,
        mock_genai_init,
        mock_worker_db_class,
    ):
        from src.common.schema.media_item_model import (
            AssetRoleEnum,
            MediaItemModel,
            MimeTypeEnum,
            SourceMediaItemLink,
        )

        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test",
            generation_model=GenerationModelEnum.VEO_3_1_PREVIEW,
            aspect_ratio="16:9",
            duration_seconds=5,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=3,
                    media_index=0,
                    role=AssetRoleEnum.VIDEO_EXTENSION_SOURCE,
                ),
            ],
        )

        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = None
        from src.config.config_service import config_service as cfg

        mock_generated_video = MagicMock()
        mock_generated_video.video.uri = (
            f"gs://{cfg.GENMEDIA_BUCKET}/output_0.mp4"
        )
        mock_operation.response.generated_videos = [mock_generated_video]

        mock_client.models.generate_videos.return_value = mock_operation
        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_item1 = MediaItemModel(
                id=1,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.VIDEO_MP4,
                model=GenerationModelEnum.VEO_3_QUALITY,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/1.mp4"],
                thumbnail_uris=[],
            )
            # Async mock get_by_id to return items
            mock_media_repo.get_by_id.side_effect = [mock_item1]

            _process_video_in_background(
                media_item_id=124,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.init")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_with_source_media_items_references(
        self,
        mock_thumb,
        mock_genai_init,
        mock_worker_db_class,
    ):
        from src.common.schema.media_item_model import (
            AssetRoleEnum,
            MediaItemModel,
            MimeTypeEnum,
            SourceMediaItemLink,
        )

        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test",
            generation_model=GenerationModelEnum.VEO_3_1_PREVIEW,
            aspect_ratio="16:9",
            duration_seconds=5,
            source_media_items=[
                SourceMediaItemLink(
                    media_item_id=4,
                    media_index=0,
                    role=AssetRoleEnum.IMAGE_REFERENCE_ASSET,
                ),
                SourceMediaItemLink(
                    media_item_id=5,
                    media_index=0,
                    role=AssetRoleEnum.IMAGE_REFERENCE_STYLE,
                ),
            ],
        )

        mock_db_context = AsyncMock()
        mock_db_factory = MagicMock(return_value=mock_db_context)
        mock_worker_db_class.return_value.__aenter__.return_value = (
            mock_db_factory
        )

        mock_client = MagicMock()
        mock_genai_init.return_value = mock_client
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.error = None
        from src.config.config_service import config_service as cfg

        mock_generated_video = MagicMock()
        mock_generated_video.video.uri = (
            f"gs://{cfg.GENMEDIA_BUCKET}/output_0.mp4"
        )
        mock_operation.response.generated_videos = [mock_generated_video]

        mock_client.models.generate_videos.return_value = mock_operation
        mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

        with (
            patch(
                "src.videos.veo_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.videos.veo_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_item1 = MediaItemModel(
                id=1,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.IMAGE_PNG,
                model=GenerationModelEnum.IMAGEN_3_001,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/1.png"],
                thumbnail_uris=[],
            )
            # Async mock get_by_id to return items
            mock_media_repo.get_by_id.side_effect = [mock_item1, mock_item1]

            _process_video_in_background(
                media_item_id=125,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.get_omni_client")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_omni_turn1(
        self,
        mock_thumb,
        mock_omni_client_init,
        mock_worker_db_class,
    ):
        from src.common.schema.media_item_model import (
            AssetRoleEnum,
            MediaItemModel,
            MimeTypeEnum,
            SourceMediaItemLink,
        )

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
            mock_gcs_service.upload_file_to_gcs.return_value = (
                "gs://bucket/uploaded.mp4"
            )

            _process_video_in_background(
                media_item_id=1234,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()
            mock_vertex_client.interactions.create.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.get_omni_client")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_omni_turn2(
        self,
        mock_thumb,
        mock_omni_client_init,
        mock_worker_db_class,
    ):
        from src.common.schema.media_item_model import (
            MediaItemModel,
            MimeTypeEnum,
        )

        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test Omni Turn 2",
            generation_model=GenerationModelEnum.GEMINI_OMNI,
            parent_media_item_id=99,
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
        mock_content.data = "ZmFrZS1vbW5pLXZpZGVvLWJ5dGVz"
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
            patch(
                "os.path.exists",
            ) as mock_exists,
            patch(
                "os.makedirs",
            ),
            patch(
                "builtins.open",
            ),
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_settings_repo = AsyncMock()
            mock_settings_repo_class.return_value = mock_settings_repo
            mock_settings_repo.get_by_id.return_value = None

            mock_parent_item = MediaItemModel(
                id=99,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.VIDEO_MP4,
                model=GenerationModelEnum.GEMINI_OMNI,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/99.mp4"],
                thumbnail_uris=[],
                raw_data={
                    "interaction_id": "interaction-xyz",
                    "signature": "sig-123",
                },
            )
            mock_media_repo.get_by_id.side_effect = [mock_parent_item]

            mock_gcs_service = MagicMock()
            mock_gcs_class.return_value = mock_gcs_service
            mock_gcs_service.download_from_gcs.return_value = None
            mock_gcs_service.upload_file_to_gcs.return_value = (
                "gs://bucket/uploaded.mp4"
            )

            mock_exists.return_value = False

            _process_video_in_background(
                media_item_id=1234,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()
            mock_vertex_client.interactions.create.assert_called_once()

    @patch("src.database.WorkerDatabase")
    @patch("src.videos.veo_service.GenAIModelSetup.get_omni_client")
    @patch("src.videos.veo_service.generate_thumbnail")
    def test_process_video_in_background_omni_turn2_fallback(
        self,
        mock_thumb,
        mock_omni_client_init,
        mock_worker_db_class,
    ):
        from src.common.schema.media_item_model import (
            MediaItemModel,
            MimeTypeEnum,
        )

        sample_dto = CreateVeoDto(
            workspace_id=1,
            prompt="Test Omni Turn 2 Fallback",
            generation_model=GenerationModelEnum.GEMINI_OMNI,
            parent_media_item_id=99,
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
        mock_content.data = "ZmFrZS1vbW5pLXZpZGVvLWJ5dGVz"
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

            # Parent has NO interaction context in raw_data (triggers fallback)
            mock_parent_item = MediaItemModel(
                id=99,
                workspace_id=1,
                user_id=1,
                user_email="t@t.com",
                mime_type=MimeTypeEnum.VIDEO_MP4,
                model=GenerationModelEnum.GEMINI_OMNI,
                aspect_ratio="16:9",
                gcs_uris=["gs://b/99.mp4"],
                thumbnail_uris=[],
                raw_data={},
            )
            mock_media_repo.get_by_id.side_effect = [mock_parent_item]

            mock_gcs_service = MagicMock()
            mock_gcs_class.return_value = mock_gcs_service
            mock_gcs_service.download_from_gcs.return_value = "/tmp/local.mp4"
            mock_gcs_service.upload_file_to_gcs.return_value = (
                "gs://bucket/uploaded.mp4"
            )

            _process_video_in_background(
                media_item_id=1234,
                request_dto=sample_dto,
                user_email="test@user.com",
            )

            mock_media_repo.update.assert_called_once()
            mock_vertex_client.interactions.create.assert_called_once()
