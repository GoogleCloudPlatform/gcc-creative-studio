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
"""Tests for Source Asset Service."""


import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image as PILImage

from src.common.base_dto import AspectRatioEnum, MimeTypeEnum
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAssetModel,
)
from src.source_assets.source_asset_service import SourceAssetService
from src.users.user_model import UserModel


def get_dummy_image_bytes():
    img = PILImage.new("RGB", (160, 90), color="blue")  # 16:9 ratio dummy
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(name="mock_dependencies")
def fixture_mock_dependencies():
    return {
        "repo": AsyncMock(),
        "user_repo": AsyncMock(),
        "gcs_service": MagicMock(bucket_name="bucket"),
        "iam_signer": MagicMock(),
        "imagen_service": AsyncMock(),
        "tags_repo": AsyncMock(),
    }


@pytest.fixture(name="service")
def fixture_service(mock_dependencies):
    return SourceAssetService(
        repo=mock_dependencies["repo"],
        user_repo=mock_dependencies["user_repo"],
        gcs_service=mock_dependencies["gcs_service"],
        iam_signer=mock_dependencies["iam_signer"],
        imagen_service=mock_dependencies["imagen_service"],
        tags_repo=mock_dependencies["tags_repo"],
    )


@pytest.fixture(name="sample_user")
def fixture_sample_user():
    return UserModel(
        id=1, email="test@example.com", name="Test User", roles=["user"]
    )


@pytest.mark.anyio
async def test_get_and_validate_aspect_ratio_image_deduced(service):
    contents = get_dummy_image_bytes()
    # 160x90 is 16:9
    ratio = await service._get_and_validate_aspect_ratio(
        contents=contents,
        is_video=False,
    )
    assert ratio == AspectRatioEnum.RATIO_16_9


@pytest.mark.anyio
async def test_get_and_validate_aspect_ratio_image_provided_valid(service):
    contents = b"irrelevant_bytes"
    ratio = await service._get_and_validate_aspect_ratio(
        contents=contents,
        is_video=False,
        provided_aspect_ratio="9:16",
    )
    assert ratio == AspectRatioEnum.RATIO_9_16


@pytest.mark.anyio
async def test_get_and_validate_aspect_ratio_image_provided_invalid(service):
    contents = b"irrelevant_bytes"
    with pytest.raises(HTTPException) as exc_info:
        await service._get_and_validate_aspect_ratio(
            contents=contents,
            is_video=False,
            provided_aspect_ratio="invalid_ratio",
        )
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_upload_asset_success_image(
    service, mock_dependencies, sample_user
):
    # Setup Mocks
    mock_dependencies["repo"].find_by_hash.return_value = None  # No duplicate
    mock_dependencies["gcs_service"].store_to_gcs.return_value = (
        "gs://bucket/asset.png"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    # Setup create returns saved object
    saved_asset = SourceAssetModel(
        id=10,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].create.return_value = saved_asset

    contents = get_dummy_image_bytes()

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=contents,
        filename="test.png",
        workspace_id=1,
        mime_type="image/png",
    )

    assert response.id == 10
    assert response.presigned_url == "https://signed.url"
    import hashlib

    expected_hash = hashlib.sha256(contents).hexdigest()
    mock_dependencies["repo"].find_by_hash.assert_called_once_with(
        sample_user.id, expected_hash, 1
    )
    mock_dependencies["repo"].create.assert_called_once()
    mock_dependencies["gcs_service"].store_to_gcs.assert_called_once()


@pytest.mark.anyio
async def test_upload_asset_duplicate(service, mock_dependencies, sample_user):
    # Setup duplicate found
    existing = SourceAssetModel(
        id=5,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].find_by_hash.return_value = existing
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    contents = get_dummy_image_bytes()

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=contents,
        filename="test.png",
        workspace_id=1,
        mime_type="image/png",
    )

    assert response.id == 5
    import hashlib

    expected_hash = hashlib.sha256(contents).hexdigest()
    mock_dependencies["repo"].find_by_hash.assert_called_once_with(
        sample_user.id, expected_hash, 1
    )
    mock_dependencies["repo"].create.assert_not_called()  # Did not save new
    mock_dependencies[
        "gcs_service"
    ].store_to_gcs.assert_not_called()  # Did not upload


@pytest.mark.anyio
async def test_delete_asset(service, mock_dependencies):
    # Setup
    asset = SourceAssetModel(
        id=1,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].get_by_id.return_value = asset
    mock_dependencies["repo"].soft_delete.return_value = True

    result = await service.delete_asset(asset_id=1, current_user_id=2)

    assert result is True
    mock_dependencies["repo"].soft_delete.assert_called_once_with(
        1, deleted_by=2
    )


@pytest.mark.anyio
async def test_delete_asset_not_found(service, mock_dependencies):
    mock_dependencies["repo"].get_by_id.return_value = None

    result = await service.delete_asset(asset_id=1)

    assert result is False
    mock_dependencies["repo"].soft_delete.assert_not_called()


@pytest.mark.anyio
@patch("src.source_assets.source_asset_service.get_video_dimensions")
@patch("src.source_assets.source_asset_service.generate_thumbnail")
async def test_upload_asset_video(
    mock_generate_thumbnail,
    mock_get_dimensions,
    service,
    mock_dependencies,
    sample_user,
):
    # Setup Mocks
    mock_get_dimensions.return_value = (1920, 1080)  # 16:9
    mock_generate_thumbnail.return_value = "/tmp/thumb.png"
    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].upload_file_to_gcs.return_value = (
        "gs://bucket/vid.mp4"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_asset = SourceAssetModel(
        id=20,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="v",
        file_hash="h2",
        mime_type=MimeTypeEnum.VIDEO_MP4,
    )
    mock_dependencies["repo"].create.return_value = saved_asset

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=b"fake_video_bytes",
        filename="test.mp4",
        workspace_id=1,
        mime_type="video/mp4",
    )

    assert response.id == 20
    mock_dependencies["gcs_service"].upload_file_to_gcs.assert_called()
    mock_generate_thumbnail.assert_called_once()


@pytest.mark.anyio
async def test_upload_asset_with_upscale(
    service, mock_dependencies, sample_user
):
    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].store_to_gcs.return_value = (
        "gs://bucket/orig.png"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    # Mock Upscale Result
    mock_upscaled = MagicMock()
    mock_upscaled.image.gcs_uri = "gs://bucket/upscaled.png"
    mock_dependencies["imagen_service"].upscale_image.return_value = (
        mock_upscaled
    )

    saved_asset = SourceAssetModel(
        id=30,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="u",
        file_hash="h3",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].create.return_value = saved_asset

    contents = get_dummy_image_bytes()

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=contents,
        filename="test.png",
        workspace_id=1,
        mime_type="image/png",
        upscale_factor="x2",
    )

    assert response.id == 30
    mock_dependencies["imagen_service"].upscale_image.assert_called_once()


@pytest.mark.anyio
async def test_get_all_vto_assets(service, mock_dependencies, sample_user):

    mock_asset1 = SourceAssetModel(
        id=1,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b/1",
        original_filename="m",
        file_hash="h1",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        asset_type=AssetTypeEnum.VTO_PERSON_MALE,
    )
    mock_asset2 = SourceAssetModel(
        id=2,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b/2",
        original_filename="f",
        file_hash="h2",
        mime_type=MimeTypeEnum.IMAGE_PNG,
        asset_type=AssetTypeEnum.VTO_PERSON_FEMALE,
    )

    mock_dependencies[
        "repo"
    ].find_system_and_private_assets_by_types.return_value = [
        mock_asset1,
        mock_asset2,
    ]
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    result = await service.get_all_vto_assets(user=sample_user)

    assert len(result.male_models) == 1
    assert len(result.female_models) == 1
    mock_dependencies[
        "repo"
    ].find_system_and_private_assets_by_types.assert_called_once()


@pytest.mark.anyio
async def test_convert_to_png_success(service):
    # Setup mock UploadFile
    mock_file = AsyncMock()
    mock_file.filename = "image.png"
    mock_file.content_type = "image/png"
    mock_file.read.return_value = get_dummy_image_bytes()

    png_bytes = await service.convert_to_png(mock_file)
    assert png_bytes is not None
    assert len(png_bytes) > 0


@pytest.mark.anyio
async def test_get_asset_by_id_authorized_owner(
    service,
    mock_dependencies,
    sample_user,
):
    asset = SourceAssetModel(
        id=40,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h4",
        scope=AssetScopeEnum.PRIVATE,
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].get_by_id.return_value = asset
    mock_dependencies["user_repo"].get_by_id.return_value = sample_user
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    response = await service.get_asset_by_id(asset_id=40, user=sample_user)

    assert response is not None
    assert response.id == 40
    assert response.user_email == "test@example.com"


@pytest.mark.anyio
async def test_create_from_gcs_uri_success(
    service, mock_dependencies, sample_user
):
    # Mock download_bytes_from_gcs returning real image bytes
    mock_dependencies["gcs_service"].download_bytes_from_gcs.return_value = (
        get_dummy_image_bytes()
    )
    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].store_to_gcs.return_value = (
        "gs://bucket/out.png"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_asset = SourceAssetModel(
        id=50,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h5",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].create.return_value = saved_asset

    response = await service.create_from_gcs_uri(
        user=sample_user,
        workspace_id=1,
        gcs_uri="gs://input/in.png",
    )

    assert response.id == 50
    mock_dependencies[
        "gcs_service"
    ].download_bytes_from_gcs.assert_called_once_with(
        "gs://input/in.png",
    )
    mock_dependencies["gcs_service"].store_to_gcs.assert_called_once()
    mock_dependencies["repo"].create.assert_called_once()


@pytest.mark.anyio
@patch("src.source_assets.source_asset_service.generate_thumbnail")
async def test_create_from_gcs_uri_video(
    mock_thumb,
    service,
    mock_dependencies,
    sample_user,
):
    # Mock download_bytes_from_gcs returning dummy video bytes
    mock_dependencies["gcs_service"].download_bytes_from_gcs.return_value = (
        b"dummy_video_bytes"
    )
    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].upload_file_to_gcs.return_value = (
        "gs://bucket/out.mp4"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    mock_thumb.return_value = "/tmp/thumbnails/thumb.png"

    saved_asset = SourceAssetModel(
        id=55,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://bucket/out.mp4",
        original_filename="a.mp4",
        file_hash="h55",
        mime_type=MimeTypeEnum.VIDEO_MP4,
    )
    mock_dependencies["repo"].create.return_value = saved_asset

    # Mock _get_and_validate_aspect_ratio to avoid slow calls
    with patch.object(service, "_get_and_validate_aspect_ratio") as mock_aspect:
        mock_aspect.return_value = AspectRatioEnum.RATIO_16_9

        response = await service.create_from_gcs_uri(
            user=sample_user,
            workspace_id=1,
            gcs_uri="gs://input/in.mp4",
        )

    assert response.id == 55
    mock_dependencies[
        "gcs_service"
    ].download_bytes_from_gcs.assert_called_once_with(
        "gs://input/in.mp4",
    )
    assert mock_dependencies["gcs_service"].upload_file_to_gcs.call_count >= 1
    mock_dependencies["repo"].create.assert_called_once()


@pytest.mark.anyio
async def test_upload_asset_non_png(service, mock_dependencies, sample_user):
    import io

    from PIL import Image

    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].store_to_gcs.return_value = (
        "gs://bucket/asset.png"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_asset = SourceAssetModel(
        id=60,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h6",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )

    mock_dependencies["repo"].create.return_value = saved_asset

    img = Image.new("RGB", (100, 100), color="red")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG")
    contents = img_byte_arr.getvalue()

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=contents,
        filename="test.jpg",
        workspace_id=1,
        mime_type="image/jpeg",
    )

    assert response.id == 60
    mock_dependencies["gcs_service"].store_to_gcs.assert_called_once()


@pytest.mark.anyio
async def test_upload_asset_audio(service, mock_dependencies, sample_user):
    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].store_to_gcs.return_value = (
        "gs://bucket/audio.mp3"
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_asset = SourceAssetModel(
        id=70,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b/audio.mp3",
        original_filename="s.mp3",
        file_hash="h7",
        mime_type=MimeTypeEnum.AUDIO_MPEG,
    )

    mock_dependencies["repo"].create.return_value = saved_asset

    contents = b"fake_mp3_data"

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=contents,
        filename="song.mp3",
        workspace_id=1,
        mime_type="audio/mpeg",
    )

    assert response.id == 70


@pytest.mark.anyio
async def test_upload_asset_upscale_failure(
    service, mock_dependencies, sample_user
):
    mock_dependencies["repo"].find_by_hash.return_value = None
    mock_dependencies["gcs_service"].store_to_gcs.return_value = (
        "gs://bucket/asset.png"
    )
    mock_dependencies["imagen_service"].upscale_image.side_effect = Exception(
        "Upscale failed",
    )
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_asset = SourceAssetModel(
        id=80,
        workspace_id=1,
        user_id=1,
        gcs_uri="gs://b",
        original_filename="a",
        file_hash="h8",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )

    mock_dependencies["repo"].create.return_value = saved_asset

    from tests.source_assets.test_source_asset_service import (
        get_dummy_image_bytes,
    )

    contents = get_dummy_image_bytes()

    response = await service.upload_asset(
        user=sample_user,
        file_bytes=contents,
        filename="test.png",
        workspace_id=1,
        mime_type="image/png",
        upscale_factor="x4",
    )

    assert response.id == 80


@pytest.mark.anyio
async def test_generate_signed_upload_url_success(
    service, mock_dependencies, sample_user
):
    from src.source_assets.dto.generate_upload_url_dto import (
        GenerateSourceAssetUploadUrlDto,
    )

    mock_dependencies[
        "iam_signer"
    ].generate_v4_upload_signed_url.return_value = (
        "https://signed.gcs/upload",
        "gs://bucket/source_assets/1/uploads/uuid/test.png",
    )
    mock_dependencies["gcs_service"].bucket_name = "bucket"

    dto = GenerateSourceAssetUploadUrlDto(
        workspace_id=1,
        filename="test.png",
        content_type="image/png",
        size=1024,
    )
    result = await service.generate_signed_upload_url(dto, sample_user)

    assert result.upload_url == "https://signed.gcs/upload"
    assert result.gcs_uri == "gs://bucket/source_assets/1/uploads/uuid/test.png"
    assert result.file_uuid is not None


@pytest.mark.anyio
async def test_generate_signed_upload_url_error(
    service, mock_dependencies, sample_user
):
    from src.source_assets.dto.generate_upload_url_dto import (
        GenerateSourceAssetUploadUrlDto,
    )

    mock_dependencies[
        "iam_signer"
    ].generate_v4_upload_signed_url.return_value = (
        None,
        None,
    )
    mock_dependencies["gcs_service"].bucket_name = "bucket"

    dto = GenerateSourceAssetUploadUrlDto(
        workspace_id=1,
        filename="test.png",
        content_type="image/png",
        size=1024,
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.generate_signed_upload_url(dto, sample_user)
    assert exc_info.value.status_code == 500


@pytest.mark.anyio
async def test_finalize_direct_upload_success_image(
    service, mock_dependencies, sample_user
):
    from src.source_assets.dto.finalize_upload_dto import (
        FinalizeSourceAssetUploadDto,
    )

    mock_dependencies["gcs_service"].bucket_name = "bucket"
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_asset = SourceAssetModel(
        id=101,
        workspace_id=1,
        user_id=sample_user.id,
        gcs_uri="gs://bucket/source_assets/1/uploads/uuid/image.png",
        original_filename="image.png",
        file_hash="hash101",
        mime_type=MimeTypeEnum.IMAGE_PNG,
    )
    mock_dependencies["repo"].create.return_value = saved_asset

    dto = FinalizeSourceAssetUploadDto(
        workspace_id=1,
        gcs_uri="gs://bucket/source_assets/1/uploads/uuid/image.png",
        filename="image.png",
        mime_type="image/png",
        size=2048,
    )
    response = await service.finalize_direct_upload(dto, sample_user)

    assert response.id == 101
    assert response.original_filename == "image.png"
    mock_dependencies["repo"].create.assert_called_once()


@pytest.mark.anyio
async def test_finalize_direct_upload_video_and_audio(
    service, mock_dependencies, sample_user
):
    from src.source_assets.dto.finalize_upload_dto import (
        FinalizeSourceAssetUploadDto,
    )

    mock_dependencies["gcs_service"].bucket_name = "bucket"
    mock_dependencies["iam_signer"].generate_presigned_url.return_value = (
        "https://signed.url"
    )

    saved_video = SourceAssetModel(
        id=102,
        workspace_id=1,
        user_id=sample_user.id,
        gcs_uri="gs://bucket/source_assets/1/uploads/uuid/video.mp4",
        original_filename="video.mp4",
        file_hash="hash102",
        mime_type=MimeTypeEnum.VIDEO_MP4,
        asset_type=AssetTypeEnum.GENERIC_VIDEO,
    )
    mock_dependencies["repo"].create.return_value = saved_video

    video_dto = FinalizeSourceAssetUploadDto(
        workspace_id=1,
        gcs_uri="gs://bucket/source_assets/1/uploads/uuid/video.mp4",
        filename="video.mp4",
        mime_type="video/mp4",
        size=50000,
    )
    res_video = await service.finalize_direct_upload(video_dto, sample_user)
    assert res_video.id == 102

    saved_audio = SourceAssetModel(
        id=103,
        workspace_id=1,
        user_id=sample_user.id,
        gcs_uri="gs://bucket/source_assets/1/uploads/uuid/audio.mp3",
        original_filename="audio.mp3",
        file_hash="hash103",
        mime_type=MimeTypeEnum.AUDIO_MPEG,
    )
    mock_dependencies["repo"].create.return_value = saved_audio

    audio_dto = FinalizeSourceAssetUploadDto(
        workspace_id=1,
        gcs_uri="gs://bucket/source_assets/1/uploads/uuid/audio.mp3",
        filename="audio.mp3",
        mime_type="audio/mp3",
        size=30000,
    )
    res_audio = await service.finalize_direct_upload(audio_dto, sample_user)
    assert res_audio.id == 103


@pytest.mark.anyio
async def test_finalize_direct_upload_non_admin_scope_error(
    service, mock_dependencies, sample_user
):
    from src.source_assets.dto.finalize_upload_dto import (
        FinalizeSourceAssetUploadDto,
    )

    mock_dependencies["gcs_service"].bucket_name = "bucket"

    dto = FinalizeSourceAssetUploadDto(
        workspace_id=1,
        gcs_uri="gs://bucket/source_assets/1/file.png",
        filename="file.png",
        mime_type="image/png",
        size=100,
        scope=AssetScopeEnum.SYSTEM,
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.finalize_direct_upload(dto, sample_user)
    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_convert_to_png_heic_heif_success(service, monkeypatch):
    from fastapi import UploadFile

    class MockHEIC2PNG:
        def __init__(self, path, quality=None, overwrite=False):
            self.path = path
            self.overwrite = overwrite

        def save(self, output_path):
            img = PILImage.new("RGB", (20, 20), color="green")
            img.save(output_path, format="PNG")

    monkeypatch.setattr("heic2png.HEIC2PNG", MockHEIC2PNG)

    buf = io.BytesIO(b"fake_heic_bytes")
    upload_file = UploadFile(file=buf, filename="test.heic")
    png_bytes = await service.convert_to_png(upload_file)
    assert png_bytes is not None
    out_img = PILImage.open(io.BytesIO(png_bytes))
    assert out_img.format == "PNG"
    assert out_img.size == (20, 20)


@pytest.mark.anyio
async def test_convert_to_png_standard_image_success(service):
    from fastapi import UploadFile

    img = PILImage.new("RGB", (20, 20), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    upload_file = UploadFile(file=buf, filename="test.jpg")
    png_bytes = await service.convert_to_png(upload_file)
    assert png_bytes is not None
    out_img = PILImage.open(io.BytesIO(png_bytes))
    assert out_img.format == "PNG"
    assert out_img.size == (20, 20)
