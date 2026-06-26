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
"""Tests for Imagen Service."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.base_dto import AspectRatioEnum, GenerationModelEnum
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    MimeTypeEnum,
)
from src.images.dto.create_imagen_dto import CreateImagenDto
from src.images.dto.upscale_imagen_dto import UpscaleImagenDto
from src.images.dto.vto_dto import VtoDto, VtoInputLink, VtoSourceMediaItemLink
from src.images.imagen_service import (
    ImagenService,
    _process_image_in_background,
    _process_upload_upscale_in_background,
    _process_vto_in_background,
    gemini_generate_image,
)
from src.users.user_model import UserModel


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
    service = MagicMock()
    service.download_bytes_from_gcs.return_value = b"fake_bytes"
    service.store_to_gcs.return_value = "gs://bucket/uploaded.png"
    service.upload_bytes_to_gcs.return_value = "gs://bucket/uploaded_bytes.png"
    service.bucket_name = "test-bucket"
    return service


@pytest.fixture(name="imagen_service")
def fixture_imagen_service(
    mock_media_repo,
    mock_source_asset_repo,
    mock_gemini_service,
    mock_gcs_service,
):
    return ImagenService(
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


@pytest.fixture(name="sample_create_imagen_dto")
def fixture_sample_create_imagen_dto():
    return CreateImagenDto(
        workspace_id=1,
        prompt="A sunset on a beach",
        generation_model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
        aspect_ratio="1:1",
    )


class TestImagenServiceMethods:
    """Tests for ImagenService wrapper methods."""

    @pytest.mark.anyio
    async def test_start_upload_upscale_job_success(
        self,
        imagen_service,
        mock_media_repo,
        mock_source_asset_repo,
        sample_user,
    ):
        _ = mock_source_asset_repo
        # Setup
        placeholder = MediaItemModel(
            id=456,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
            aspect_ratio="1:1",
            gcs_uris=[],
            original_gcs_uris=[],
        )

        mock_media_repo.create.return_value = placeholder

        mock_executor = MagicMock()

        # Call
        response = await imagen_service.start_upload_upscale_job(
            user=sample_user,
            executor=mock_executor,
            workspace_id=1,
            gcs_uri="gs://input/original.png",
            mime_type="image/png",
            file_bytes=b"fake_bytes",  # pass bytes to bypass validation GCS check
        )

        # Assert
        assert response.id == 456
        mock_media_repo.create.assert_called_once()
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_upscale_image_success(self, imagen_service):
        request_dto = UpscaleImagenDto(
            user_image="gs://bucket/input.png",
            upscale_factor="x4",
            include_rai_reason=False,
            enhance_input_image=False,
            image_preservation_factor=1.0,
        )

        with patch(
            "src.images.imagen_service.GenAIModelSetup.init"
        ) as mock_init:
            mock_client = MagicMock()
            mock_init.return_value = mock_client

            mock_response = MagicMock()
            mock_generated_image = MagicMock()
            mock_generated_image.image.image_bytes = b"fake_upscaled_bytes"
            mock_generated_image.rai_filtered_reason = ""
            mock_response.generated_images = [mock_generated_image]

            mock_client.models.upscale_image.return_value = mock_response

            # Call
            result = await imagen_service.upscale_image(request_dto)

            assert result is not None

    @pytest.mark.anyio
    async def test_upscale_image_rai_filtered(self, imagen_service):
        from src.images.dto.upscale_imagen_dto import UpscaleImagenDto

        request_dto = UpscaleImagenDto(
            user_image="gs://bucket/input.png",
            upscale_factor="x4",
        )
        with patch(
            "src.images.imagen_service.GenAIModelSetup.init"
        ) as mock_init:
            mock_client = MagicMock()
            mock_init.return_value = mock_client
            mock_response = MagicMock()
            mock_generated_image = MagicMock()
            mock_generated_image.image = None  # Crucial to trigger RAI branch!
            mock_generated_image.rai_filtered_reason = "unsafeContent"
            mock_response.generated_images = [mock_generated_image]

            mock_client.models.upscale_image.return_value = mock_response

            with pytest.raises(
                ValueError, match="Image upscaling filtered by RAI"
            ):
                await imagen_service.upscale_image(request_dto)

    @pytest.mark.anyio
    async def test_upscale_image_no_data(self, imagen_service):
        from src.images.dto.upscale_imagen_dto import UpscaleImagenDto

        request_dto = UpscaleImagenDto(
            user_image="gs://bucket/input.png",
            upscale_factor="x4",
        )
        with patch(
            "src.images.imagen_service.GenAIModelSetup.init"
        ) as mock_init:
            mock_client = MagicMock()
            mock_init.return_value = mock_client
            mock_response = MagicMock()
            mock_response.generated_images = []  # Empty
            mock_client.models.upscale_image.return_value = mock_response

            with pytest.raises(
                ValueError,
                match="Image upscaling generation failed or returned no data",
            ):
                await imagen_service.upscale_image(request_dto)

    @pytest.mark.anyio
    async def test_start_image_generation_job_success(
        self,
        imagen_service,
        mock_media_repo,
        sample_user,
    ):
        request_dto = CreateImagenDto(
            workspace_id=1,
            prompt="A beautiful sunset",
            generation_model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
            aspect_ratio="1:1",
        )

        # Mock media_repo.create return
        placeholder = MediaItemModel(
            id=789,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
            aspect_ratio="1:1",
            gcs_uris=[],
            original_gcs_uris=[],
        )
        mock_media_repo.create.return_value = placeholder

        mock_executor = MagicMock()

        # Call
        response = await imagen_service.start_image_generation_job(
            request_dto=request_dto,
            user=sample_user,
            executor=mock_executor,
        )

        assert response.id == 789
        mock_media_repo.create.assert_called_once()
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_start_upload_upscale_job_large_image(
        self,
        imagen_service,
        mock_source_asset_repo,
        mock_gcs_service,
        sample_user,
    ):
        asset = MagicMock()
        asset.id = 101
        asset.gcs_uri = "gs://bucket/large.png"
        mock_source_asset_repo.get_by_id.return_value = asset
        mock_gcs_service.download_bytes_from_gcs.return_value = (
            b"fake_image_bytes"
        )

        with patch("PIL.Image.open") as mock_pil_open:
            mock_pil = MagicMock()
            mock_pil.width = 5000
            mock_pil.height = 5000
            mock_pil_open.return_value = mock_pil

            mock_executor = MagicMock()

            # Call & Assert Exception
            with pytest.raises(HTTPException) as exc_info:
                await imagen_service.start_upload_upscale_job(
                    user=sample_user,
                    executor=mock_executor,
                    workspace_id=1,
                    source_asset_id=101,
                    upscale_factor="x4",
                    mime_type="image/png",
                    gcs_uri="",
                )

            assert exc_info.value.status_code == 400
            assert "too large" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_start_upload_upscale_job_existing_media_item(
        self,
        imagen_service,
        mock_media_repo,
        mock_gcs_service,
        sample_user,
    ):
        media = MagicMock()
        media.id = 111
        media.gcs_uris = ["gs://bucket/existing_media.png"]
        mock_media_repo.get_by_id.return_value = media

        placeholder = MediaItemModel(
            id=456,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
            aspect_ratio="1:1",
            gcs_uris=[],
            original_gcs_uris=[],
        )
        mock_media_repo.create.return_value = placeholder
        mock_executor = MagicMock()
        mock_gcs_service.download_bytes_from_gcs.return_value = (
            None  # Skip PIL open
        )

        # Call
        response = await imagen_service.start_upload_upscale_job(
            user=sample_user,
            executor=mock_executor,
            workspace_id=1,
            media_item_id_existing=111,
            upscale_factor="x4",
            mime_type="image/png",
            gcs_uri="",
        )

        assert response is not None
        mock_media_repo.get_by_id.assert_called_with(111)

    @pytest.mark.anyio
    async def test_start_vto_generation_job_success(
        self,
        imagen_service,
        mock_media_repo,
        sample_user,
    ):
        from src.images.dto.vto_dto import VtoDto

        request_dto = VtoDto(
            workspace_id=1,
            person_image={"source_asset_id": 101},
            top_image={"source_asset_id": 102},
        )

        placeholder = MediaItemModel(
            id=222,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.VTO,
            aspect_ratio=AspectRatioEnum.RATIO_9_16,
            gcs_uris=[],
            original_gcs_uris=[],
        )
        mock_media_repo.create.return_value = placeholder

        mock_executor = MagicMock()

        # Call
        response = await imagen_service.start_vto_generation_job(
            request_dto=request_dto,
            user=sample_user,
            executor=mock_executor,
        )

        assert response.id == 222
        mock_media_repo.create.assert_called_once()
        mock_executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_get_media_item_with_presigned_urls_success(
        self,
        imagen_service,
        mock_media_repo,
    ):
        media_item = MediaItemModel(
            id=111,
            workspace_id=1,
            user_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.IMAGE_PNG,
            model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
            aspect_ratio="1:1",
            gcs_uris=["gs://bucket/image.png"],
            original_gcs_uris=[],
        )
        mock_media_repo.get_by_id.return_value = media_item

        imagen_service.iam_signer_credentials = MagicMock()
        imagen_service.iam_signer_credentials.generate_presigned_url.return_value = (
            "https://signed.url/image.png"
        )

        # Call
        response = await imagen_service.get_media_item_with_presigned_urls(
            media_id=111
        )

        assert response is not None
        assert response.id == 111
        assert "https://signed.url/image.png" in response.presigned_urls


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_image_in_background_sync(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_create_imagen_dto,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)

    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    # Use MagicMock so calling it returns the context manager directly, not a coroutine
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    # Mock GenAI SDK client
    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    mock_thumb_mu.return_value = "gs://bucket/thumb_0.png"
    mock_thumb_is.return_value = "gs://bucket/thumb_0.png"

    # Patch Repos inside _async_worker execution
    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.SourceAssetRepository",
        ) as mock_source_asset_repo_class,
        patch(
            "src.images.imagen_service.GeminiService",
        ) as mock_gemini_service_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
        patch(
            "src.images.imagen_service.IamSignerCredentials",
        ) as mock_iam_class,
        patch(
            "src.images.imagen_service.gemini_generate_image",
        ) as mock_gemini_gen,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_gemini_service = AsyncMock()
        mock_gemini_service.enhance_prompt_from_dto.return_value = (
            "Enhanced Prompt"
        )
        mock_gemini_service_class.return_value = mock_gemini_service

        mock_gcs = AsyncMock()
        mock_gcs.bucket_name = "test-bucket"
        mock_gcs_class.return_value = mock_gcs

        mock_result = MagicMock()
        mock_result.image.gcs_uri = "gs://bucket/output_0.png"
        mock_result.image.mime_type = MimeTypeEnum.IMAGE_PNG
        mock_gemini_gen.return_value = (mock_result, None)

        # Call the worker function
        _process_image_in_background(
            media_item_id=123,
            request_dto=sample_create_imagen_dto,
            current_user=sample_user,
        )

        # Assertions
        mock_media_repo.update.assert_called_once()
        args, kwargs = mock_media_repo.update.call_args
        assert args[0] == 123
        update_data = args[1]
        assert update_data["status"] == JobStatusEnum.COMPLETED
        assert "gs://bucket/output_0.png" in update_data["gcs_uris"]


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_image_in_background_sync_gemini_model(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_create_imagen_dto,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)
    from src.common.base_dto import GenerationModelEnum

    sample_create_imagen_dto.generation_model = (
        GenerationModelEnum.GEMINI_3_PRO_IMAGE_PREVIEW
    )
    sample_create_imagen_dto.google_search = False
    sample_create_imagen_dto.resolution = "1024x1024"

    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    with patch(
        "src.images.imagen_service.gemini_generate_image"
    ) as mock_gemini_gen:
        mock_result = MagicMock()
        mock_result.image.gcs_uri = "gs://bucket/output_gemini.png"
        mock_gemini_gen.return_value = (mock_result, None)

        with (
            patch(
                "src.images.imagen_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.images.imagen_service.GeminiService",
            ) as mock_gemini_service_class,
            patch(
                "src.images.imagen_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            mock_gemini_service = AsyncMock()
            mock_gemini_service.enhance_prompt_from_dto.return_value = (
                "Enhanced Prompt"
            )
            mock_gemini_service_class.return_value = mock_gemini_service

            mock_gcs = AsyncMock()
            mock_gcs.bucket_name = "test-bucket"
            mock_gcs_class.return_value = mock_gcs

            _process_image_in_background(
                media_item_id=124,
                request_dto=sample_create_imagen_dto,
                current_user=sample_user,
            )

            mock_gemini_gen.assert_called_once()
            mock_media_repo.update.assert_called_once()


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_image_in_background_sync_with_upscale(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_create_imagen_dto,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)
    sample_create_imagen_dto.upscale_factor = "x4"

    # Worker database mocks
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.GeminiService",
        ) as mock_gemini_service_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
        patch(
            "src.images.imagen_service.ImagenService.upscale_image",
        ) as mock_upscale_method,
        patch(
            "src.images.imagen_service.gemini_generate_image",
        ) as mock_gemini_gen,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_gemini_service = AsyncMock()
        mock_gemini_service.enhance_prompt_from_dto.return_value = (
            "Enhanced Prompt"
        )
        mock_gemini_service_class.return_value = mock_gemini_service

        mock_gcs = AsyncMock()
        mock_gcs.bucket_name = "test-bucket"
        mock_gcs_class.return_value = mock_gcs

        mock_result = MagicMock()
        mock_result.image.gcs_uri = "gs://b/generated.png"
        mock_result.image.mime_type = MimeTypeEnum.IMAGE_PNG
        mock_gemini_gen.return_value = (mock_result, None)

        # Mock upscale result
        mock_upscale_result = MagicMock()
        mock_upscale_result.image.gcs_uri = "gs://b/upscaled.png"
        mock_upscale_method.return_value = mock_upscale_result

        _process_image_in_background(
            media_item_id=125,
            request_dto=sample_create_imagen_dto,
            current_user=sample_user,
        )

        mock_upscale_method.assert_called_once()
        mock_media_repo.update.assert_called_once()
        args, kwargs = mock_media_repo.update.call_args
        update_data = args[1]
        assert "gs://b/upscaled.png" in update_data["gcs_uris"]


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_image_in_background_sync_gemini_image_to_image(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_create_imagen_dto,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)
    from src.common.base_dto import GenerationModelEnum
    from src.common.schema.media_item_model import SourceMediaItemLink

    sample_create_imagen_dto.generation_model = (
        GenerationModelEnum.GEMINI_3_PRO_IMAGE_PREVIEW
    )
    sample_create_imagen_dto.source_media_items = [
        SourceMediaItemLink(
            media_item_id=999, media_index=0, role=AssetRoleEnum.INPUT
        ),
    ]

    # Worker database mocks
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    with patch(
        "src.images.imagen_service.gemini_generate_image"
    ) as mock_gemini_gen:
        mock_result = MagicMock()
        mock_result.image.gcs_uri = "gs://bucket/output_gemini_i2i.png"
        mock_gemini_gen.return_value = (mock_result, None)

        with (
            patch(
                "src.images.imagen_service.MediaRepository",
            ) as mock_media_repo_class,
            patch(
                "src.images.imagen_service.GcsService",
            ) as mock_gcs_class,
        ):
            mock_media_repo = AsyncMock()
            mock_media_repo_class.return_value = mock_media_repo

            # Mock source media item fetch
            source_item = MediaItemModel(
                workspace_id=99,
                user_email="admin@test.com",
                model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
                prompt="Source",
                mime_type=MimeTypeEnum.IMAGE_PNG,
                aspect_ratio=AspectRatioEnum.RATIO_1_1,
                gcs_uris=["gs://b/source.png"],
            )
            mock_media_repo.get_by_id.return_value = source_item

            mock_gcs = AsyncMock()
            mock_gcs.bucket_name = "test-bucket"
            mock_gcs_class.return_value = mock_gcs
            mock_gcs.download_bytes_from_gcs.return_value = b"fake-source-bytes"

            _process_image_in_background(
                media_item_id=126,
                request_dto=sample_create_imagen_dto,
                current_user=sample_user,
            )

            mock_gemini_gen.assert_called_once()
            mock_media_repo.update.assert_called_once()


def test_gemini_generate_image_base64_reconstruct(mock_gcs_service):

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_candidate = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data.data = "YmFzZTY0X2ltYWdl"  # base64 for 'base64_image'
    mock_part.inline_data.mime_type = "image/png"
    mock_candidate.content.parts = [mock_part]
    mock_response.candidates = [mock_candidate]
    mock_client.models.generate_content.return_value = mock_response

    mock_gcs_service.store_to_gcs.return_value = "gs://bucket/out.png"

    image_obj, grounding_metadata = gemini_generate_image(
        gcs_service=mock_gcs_service,
        vertexai_client=mock_client,
        prompt="Test",
        model=GenerationModelEnum.GEMINI_3_PRO_IMAGE_PREVIEW,
        bucket_name="bucket",
    )

    assert image_obj.image.gcs_uri == "gs://bucket/out.png"

    assert image_obj.image.mime_type == "image/png"

    mock_gcs_service.store_to_gcs.assert_called_once()


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_vto_in_background_sync(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)

    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    # Mock GenAI SDK client
    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    # response structure for recontext_image usually returns GeneratedImage
    mock_response = MagicMock()
    mock_generated_image = MagicMock()
    mock_generated_image.image.gcs_uri = "gs://bucket/output_vto.png"
    mock_response.generated_images = [mock_generated_image]
    mock_client.models.recontext_image.return_value = mock_response

    sample_vto_dto = VtoDto(
        workspace_id=1,
        person_image=VtoInputLink(source_asset_id=101),
        top_image=VtoInputLink(source_asset_id=102),
    )

    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.SourceAssetRepository",
        ) as mock_source_asset_repo_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_sa_repo = AsyncMock()
        mock_source_asset_repo_class.return_value = mock_sa_repo

        # Setup source asset mock returns for get_by_id
        person_asset = MagicMock()
        person_asset.id = 101
        person_asset.gcs_uri = "gs://bucket/person.png"

        top_asset = MagicMock()
        top_asset.id = 102
        top_asset.gcs_uri = "gs://bucket/garment.png"

        def get_by_id_side_effect(asset_id):
            if asset_id == 101:
                return person_asset
            if asset_id == 102:
                return top_asset
            return None

        mock_sa_repo.get_by_id.side_effect = get_by_id_side_effect

        mock_gcs = MagicMock()
        mock_gcs.bucket_name = "test-bucket"
        mock_gcs.download_bytes_from_gcs.return_value = b"fake_bytes"
        mock_gcs.store_to_gcs.return_value = "gs://bucket/output_vto.png"
        mock_gcs_class.return_value = mock_gcs

        # Call
        _process_vto_in_background(
            media_item_id=222,
            request_dto=sample_vto_dto,
            current_user=sample_user,
        )

        args, kwargs = mock_media_repo.update.call_args
        assert args[0] == 222
        assert args[1]["status"] == JobStatusEnum.COMPLETED


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
def test_process_upload_upscale_in_background_sync(
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)

    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.SourceAssetRepository",
        ) as mock_source_asset_repo_class,
        patch(
            "src.images.imagen_service.ImagenService",
        ) as mock_imagen_service_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
        patch(
            "src.images.imagen_service.IamSignerCredentials",
        ) as mock_iam_signer_class,
        patch(
            "src.images.imagen_service.GeminiService",
        ) as mock_gemini_service_class,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_sa_repo = AsyncMock()
        mock_source_asset_repo_class.return_value = mock_sa_repo

        # Mock upscale_image on ImagenService
        mock_imagen_service = AsyncMock()
        mock_imagen_service_class.return_value = mock_imagen_service

        mock_result = MagicMock()
        mock_result.image.gcs_uri = "gs://bucket/upscaled.png"
        mock_imagen_service.upscale_image.return_value = mock_result

        mock_gcs = AsyncMock()
        mock_gcs_class.return_value = mock_gcs

        # Mock existing asset return for Case 2
        existing_asset = MagicMock()
        existing_asset.id = 301
        existing_asset.gcs_uri = "gs://bucket/original.png"
        mock_sa_repo.get_by_id.return_value = existing_asset

        # Call the worker
        _process_upload_upscale_in_background(
            media_item_id=333,
            workspace_id=1,
            user=sample_user,
            gcs_uri="gs://bucket/original.png",
            file_bytes=None,
            filename=None,
            upscale_factor="x4",
            aspect_ratio=None,
            source_asset_id=301,
        )

        args, kwargs = mock_media_repo.update.call_args
        assert args[0] == 333
        assert args[1]["status"] == JobStatusEnum.COMPLETED


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
def test_process_upload_upscale_in_background_sync_new_file(
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)

    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.SourceAssetRepository",
        ) as mock_source_asset_repo_class,
        patch(
            "src.source_assets.source_asset_service.SourceAssetService",
        ) as mock_sa_service_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
        patch(
            "src.images.imagen_service.IamSignerCredentials",
        ) as mock_iam_signer_class,
        patch(
            "src.images.imagen_service.GeminiService",
        ) as mock_gemini_service_class,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_sa_repo = AsyncMock()
        mock_source_asset_repo_class.return_value = mock_sa_repo

        # Mock SourceAssetService.upload_asset
        mock_sa_service = AsyncMock()
        mock_sa_service_class.return_value = mock_sa_service
        mock_asset_response = MagicMock()
        mock_asset_response.id = 501
        mock_asset_response.gcs_uri = "gs://bucket/upscaled.png"
        mock_asset_response.original_gcs_uri = "gs://bucket/original.png"
        mock_sa_service.upload_asset.return_value = mock_asset_response

        mock_gcs = AsyncMock()
        mock_gcs_class.return_value = mock_gcs

        # Call the worker with file_bytes (Case 1)
        _process_upload_upscale_in_background(
            media_item_id=444,
            workspace_id=1,
            user=sample_user,
            gcs_uri="",
            file_bytes=b"fake_bytes",
            filename="test.png",
            upscale_factor="x4",
            aspect_ratio=None,
            source_asset_id=None,
        )

        args, kwargs = mock_media_repo.update.call_args
        assert args[0] == 444
        assert args[1]["status"] == JobStatusEnum.COMPLETED


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_vto_in_background_sync_media_item(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)

    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    # Mock GenAI SDK client
    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    # response structure for recontext_image usually returns GeneratedImage
    mock_response = MagicMock()
    mock_generated_image = MagicMock()
    mock_generated_image.image.gcs_uri = "gs://bucket/output_vto.png"
    mock_response.generated_images = [mock_generated_image]
    mock_client.models.recontext_image.return_value = mock_response

    sample_vto_dto = VtoDto(
        workspace_id=1,
        person_image=VtoInputLink(
            source_media_item=VtoSourceMediaItemLink(
                media_item_id=111, media_index=0
            ),
        ),
        top_image=VtoInputLink(source_asset_id=102),
    )

    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.SourceAssetRepository",
        ) as mock_source_asset_repo_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_sa_repo = AsyncMock()
        mock_source_asset_repo_class.return_value = mock_sa_repo

        # Setup media item return for person_image
        parent_item = MagicMock()
        parent_item.id = 111
        parent_item.gcs_uris = ["gs://bucket/person_gen.png"]

        # Make get_by_id return parent_item if id matches 111
        def get_by_id_media_side_effect(media_id):
            if media_id == 111:
                return parent_item
            return None

        mock_media_repo.get_by_id.side_effect = get_by_id_media_side_effect

        # Setup source asset return for top clothing
        top_asset = MagicMock()
        top_asset.id = 102
        top_asset.gcs_uri = "gs://bucket/garment.png"
        mock_sa_repo.get_by_id.return_value = top_asset

        mock_gcs = MagicMock()
        mock_gcs.bucket_name = "test-bucket"
        mock_gcs.download_bytes_from_gcs.return_value = b"fake_bytes"
        mock_gcs.store_to_gcs.return_value = "gs://bucket/output_vto.png"
        mock_gcs_class.return_value = mock_gcs

        # Call
        _process_vto_in_background(
            media_item_id=223,
            request_dto=sample_vto_dto,
            current_user=sample_user,
        )

        args, kwargs = mock_media_repo.update.call_args
        assert args[0] == 223
        assert args[1]["status"] == JobStatusEnum.COMPLETED


@patch("src.images.imagen_service.generate_image_thumbnail_from_gcs")
@patch("src.common.media_utils.generate_image_thumbnail_from_gcs")
@patch("src.database.WorkerDatabase")
@patch("src.images.imagen_service.GenAIModelSetup.init")
def test_process_image_in_background_sync_edit_image(
    mock_genai_init,
    mock_worker_db_class,
    mock_thumb_mu,
    mock_thumb_is,
    sample_user,
):
    _ = (mock_thumb_mu, mock_thumb_is)

    # Mock WorkerDatabase Context
    mock_db_context = AsyncMock()
    mock_db_factory = MagicMock(return_value=mock_db_context)
    mock_worker_db_class.return_value.__aenter__.return_value = mock_db_factory

    # Mock GenAI SDK client
    mock_client = MagicMock()
    mock_genai_init.return_value = mock_client

    # DTO with reference image
    request_dto = CreateImagenDto(
        workspace_id=1,
        prompt="Add a hat",
        generation_model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
        source_asset_ids=[101],
    )

    with (
        patch(
            "src.images.imagen_service.MediaRepository",
        ) as mock_media_repo_class,
        patch(
            "src.images.imagen_service.SourceAssetRepository",
        ) as mock_source_asset_repo_class,
        patch(
            "src.images.imagen_service.GeminiService",
        ) as mock_gemini_service_class,
        patch(
            "src.images.imagen_service.GcsService",
        ) as mock_gcs_class,
        patch(
            "src.images.imagen_service.gemini_generate_image",
        ) as mock_gemini_gen,
    ):
        mock_media_repo = AsyncMock()
        mock_media_repo_class.return_value = mock_media_repo

        mock_gemini_service = AsyncMock()
        mock_gemini_service.enhance_prompt_from_dto.return_value = (
            "Enhanced Prompt"
        )
        mock_gemini_service_class.return_value = mock_gemini_service

        mock_sa_repo = AsyncMock()
        mock_source_asset_repo_class.return_value = mock_sa_repo

        # Setup source asset return for the input
        asset = MagicMock()
        asset.id = 101
        asset.gcs_uri = "gs://bucket/input.png"
        asset.mime_type = "image/png"
        mock_sa_repo.get_by_id.return_value = asset

        mock_gcs = AsyncMock()
        mock_gcs.bucket_name = "test-bucket"
        mock_gcs_class.return_value = mock_gcs

        mock_result = MagicMock()
        mock_result.image.gcs_uri = "gs://bucket/output_edit.png"
        mock_result.image.mime_type = MimeTypeEnum.IMAGE_PNG
        mock_gemini_gen.return_value = (mock_result, None)

        # Call the worker
        _process_image_in_background(
            media_item_id=777,
            request_dto=request_dto,
            current_user=sample_user,
        )

        args, kwargs = mock_media_repo.update.call_args
        assert args[0] == 777
        assert args[1]["status"] == JobStatusEnum.COMPLETED


def test_create_imagen_dto_validation_failures():
    import pytest
    from pydantic import ValidationError

    from src.common.base_dto import GenerationModelEnum
    from src.images.dto.create_imagen_dto import CreateImagenDto

    # 1. Empty prompt
    with pytest.raises(ValidationError) as exc_info:
        CreateImagenDto(
            prompt="   ",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
        )
    assert "Prompt cannot be empty" in str(exc_info.value)

    # 2. Too many inputs
    with pytest.raises(ValidationError) as exc_info:
        CreateImagenDto(
            prompt="Generate image",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_2_5_FLASH_IMAGE,
            source_asset_ids=[1, 2, 3],
        )
    assert "maximum" in str(exc_info.value)

    # 3. Invalid aspect ratio for model
    from src.common.base_dto import AspectRatioEnum

    with pytest.raises(ValidationError) as exc_info:
        CreateImagenDto(
            prompt="Generate image",
            workspace_id=1,
            generation_model=GenerationModelEnum.GEMINI_2_5_FLASH_IMAGE,
            aspect_ratio=AspectRatioEnum.RATIO_1_4,
        )
    assert "is not supported" in str(exc_info.value)

    # 4. Invalid generation model for imagen
    with pytest.raises(ValidationError) as exc_info:
        CreateImagenDto(
            prompt="Generate image",
            workspace_id=1,
            generation_model=GenerationModelEnum.VEO_3_FAST,
        )
    assert "Invalid generation model" in str(exc_info.value)

    # 5. Unsupported editing model
    with pytest.raises(ValidationError) as exc_info:
        CreateImagenDto(
            prompt="Edit image",
            workspace_id=1,
            generation_model=GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
            source_asset_ids=[1],
        )
    assert "does not support image editing" in str(exc_info.value)


def test_upscale_imagen_dto_validation_failures():
    import pytest
    from pydantic import ValidationError

    from src.common.base_dto import GenerationModelEnum, MimeTypeEnum
    from src.images.dto.upscale_imagen_dto import UpscaleImagenDto

    # 1. Invalid model for upscale
    with pytest.raises(ValidationError) as exc_info:
        UpscaleImagenDto(
            generation_model=GenerationModelEnum.VEO_3_FAST,
            user_image="base64str",
        )
    assert "Invalid generation model" in str(exc_info.value)

    # 2. Invalid mime type
    with pytest.raises(ValidationError) as exc_info:
        UpscaleImagenDto(
            user_image="base64str", mime_type=MimeTypeEnum.AUDIO_WAV
        )
    assert "Invalid mime type" in str(exc_info.value)


def test_vto_dto_validation_failures():
    import pytest
    from pydantic import ValidationError

    from src.images.dto.vto_dto import VtoDto, VtoInputLink

    # 1. Invalid VtoInputLink (Both provided)
    with pytest.raises(ValidationError) as exc_info:
        VtoInputLink(
            source_asset_id=1,
            source_media_item={"media_item_id": 1, "media_index": 0},
        )
    assert "Exactly one" in str(exc_info.value)

    # 2. VtoDto with no garment
    valid_input = VtoInputLink(source_asset_id=1)
    with pytest.raises(ValidationError) as exc_info:
        VtoDto(workspace_id=1, person_image=valid_input)
    assert "At least one garment" in str(exc_info.value)
