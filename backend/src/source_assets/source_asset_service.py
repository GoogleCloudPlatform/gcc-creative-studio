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
"""Service module for source asset operations including uploads, details, and delete."""

import asyncio
import hashlib
import io
import logging
import mimetypes
import os
import shutil
import uuid

from fastapi import Depends, HTTPException, UploadFile, status
from PIL import Image as PILImage

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.media_utils import generate_thumbnail, get_video_dimensions
from src.common.storage_service import GcsService
from src.images.dto.upscale_imagen_dto import UpscaleImagenDto
from src.images.imagen_service import ImagenService
from src.multimodal.gemini_service import GeminiService
from src.source_assets.dto.finalize_upload_dto import (
    FinalizeSourceAssetUploadDto,
)
from src.source_assets.dto.generate_upload_url_dto import (
    GenerateSourceAssetUploadUrlDto,
    GenerateSourceAssetUploadUrlResponseDto,
)
from src.source_assets.dto.source_asset_response_dto import (
    SourceAssetResponseDto,
)
from src.source_assets.dto.source_asset_search_dto import SourceAssetSearchDto
from src.source_assets.dto.vto_assets_response_dto import VtoAssetsResponseDto
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.tags.repository.tags_repository import TagsRepository
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum,
    AssetTypeEnum,
    SourceAssetModel,
)
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum

logger = logging.getLogger(__name__)


class SourceAssetService:
    """Provides business logic for managing user-uploaded assets."""

    def __init__(
        self,
        repo: SourceAssetRepository = Depends(),
        user_repo: UserRepository = Depends(),
        gcs_service: GcsService = Depends(),
        iam_signer: IamSignerCredentials = Depends(),
        imagen_service: ImagenService = Depends(),
        gemini_service: GeminiService = Depends(),
        tags_repo: TagsRepository = Depends(),
    ):
        self.repo = repo
        self.user_repo = user_repo
        self.gcs_service = gcs_service
        self.iam_signer = iam_signer
        self.imagen_service = imagen_service  # Service to perform the upscale
        self.gemini_service = gemini_service
        self.tags_repo = tags_repo

    async def _get_and_validate_aspect_ratio(
        self,
        contents: bytes,
        is_video: bool,
        temp_video_path: str | None = None,
        provided_aspect_ratio: str | None = None,
    ) -> AspectRatioEnum:
        """Validates a provided aspect ratio or deduces it from the file.
        Rejects files that do not match a supported AspectRatioEnum value.
        """
        # For videos, we ALWAYS deduce the aspect ratio and ignore any provided one.
        if is_video:
            if not temp_video_path:
                raise ValueError(
                    "Temp video path is required to deduce video aspect ratio.",
                )
            width, height = await asyncio.to_thread(
                get_video_dimensions,
                temp_video_path,
            )

        # For images, we first check if a valid ratio was provided.
        elif provided_aspect_ratio:
            try:
                # If the provided string is a valid enum member, we're done.
                return AspectRatioEnum(provided_aspect_ratio)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid aspect ratio '{provided_aspect_ratio}' provided.",
                ) from exc

        # For images without a provided ratio, we deduce it.
        else:
            pil_image = PILImage.open(io.BytesIO(contents))
            width, height = pil_image.size

        if height == 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Media has zero height."
            )

        actual_ratio = width / height

        # Find the closest supported enum by comparing float values
        supported_ratios = {
            e: float(e.value.split(":")[0]) / float(e.value.split(":")[1])
            for e in AspectRatioEnum
            if ":" in e.value
        }

        closest_enum = min(
            supported_ratios.keys(),
            key=lambda e: abs(supported_ratios[e] - actual_ratio),
        )

        # Check if the closest match is within a small tolerance (e.g., 2%)
        if abs(supported_ratios[closest_enum] - actual_ratio) > 0.02:
            logger.info(
                "Falling back to 'OTHER' ratio for %sx%s (actual ratio: %.3f)",
                width,
                height,
                actual_ratio,
            )
            return AspectRatioEnum.OTHER

        logger.info("Deduced aspect ratio as %s", closest_enum.value)
        return closest_enum

    def _determine_mime_type_enum(self, content_type: str) -> MimeTypeEnum:
        """Determines the appropriate MimeTypeEnum for a given content type string."""
        if content_type.startswith("video/"):
            return MimeTypeEnum.VIDEO_MP4
        if content_type.startswith("audio/"):
            if content_type in ["audio/mpeg", "audio/mp3"]:
                return MimeTypeEnum.AUDIO_MPEG
            if content_type == "audio/wav":
                return MimeTypeEnum.AUDIO_WAV
            if content_type == "audio/ogg":
                return MimeTypeEnum.AUDIO_OGG
            if content_type == "audio/webm":
                return MimeTypeEnum.AUDIO_WEBM
            return MimeTypeEnum.AUDIO_MPEG
        if content_type in ["image/jpeg", "image/jpg"]:
            return MimeTypeEnum.IMAGE_JPEG
        if content_type == "image/webp":
            return MimeTypeEnum.IMAGE_WEBP
        return MimeTypeEnum.IMAGE_PNG

    async def _create_asset_response(
        self,
        asset: SourceAssetModel,
        user_email: str | None = None,
        user_picture: str | None = None,
    ) -> SourceAssetResponseDto:
        """Generates presigned URLs for the asset and its thumbnail."""
        tasks = [
            asyncio.to_thread(
                self.iam_signer.generate_presigned_url, asset.gcs_uri
            ),
        ]

        if asset.original_gcs_uri:
            tasks.append(
                asyncio.to_thread(
                    self.iam_signer.generate_presigned_url,
                    asset.original_gcs_uri,
                ),
            )

        if asset.thumbnail_gcs_uri:
            tasks.append(
                asyncio.to_thread(
                    self.iam_signer.generate_presigned_url,
                    asset.thumbnail_gcs_uri,
                ),
            )

        results = await asyncio.gather(*tasks)
        presigned_url = results[0]
        presigned_original_url = ""
        presigned_thumbnail_url = ""
        next_index = 1

        if asset.original_gcs_uri:
            presigned_original_url = results[next_index]
            next_index += 1

        if asset.thumbnail_gcs_uri:
            presigned_thumbnail_url = results[next_index]

        return SourceAssetResponseDto(
            **asset.model_dump(),
            presigned_url=presigned_url,
            presigned_original_url=presigned_original_url,
            presigned_thumbnail_url=presigned_thumbnail_url,
            user_email=user_email,
            user_picture=user_picture,
        )

    async def upload_asset(
        self,
        user: UserModel,
        file_bytes: bytes,
        filename: str,
        workspace_id: int,
        mime_type: str,
        scope: AssetScopeEnum | None = None,
        asset_type: AssetTypeEnum | None = None,
        aspect_ratio: AspectRatioEnum | None = None,
        upscale_factor: str | None = None,
        enhance_input_image: bool | None = None,
        image_preservation_factor: float | None = None,
        metadata_generation_model: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> SourceAssetResponseDto:
        """Handles uploading, de-duplicating, upscaling, and saving a new user asset."""
        contents = file_bytes
        if not contents:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot upload an empty file.",
            )

        file_hash = hashlib.sha256(contents).hexdigest()

        # 1. Check for duplicates for this user
        existing_asset = await self.repo.find_by_hash(
            user.id, file_hash, workspace_id
        )
        if existing_asset:
            logger.info(
                "Duplicate asset found for user %s with hash %s. Returning existing.",
                user.email,
                file_hash[:8],
            )
            return await self._create_asset_response(existing_asset)

        # 2. Handle file processing based on type (image vs. video vs. audio)
        is_video: bool = bool(mime_type and "video" in mime_type)
        is_audio: bool = bool(mime_type and "audio" in mime_type)
        final_gcs_uri: str | None = None
        thumbnail_gcs_uri: str | None = None
        original_gcs_uri: str | None = None

        temp_dir = f"temp/source_assets/{uuid.uuid4()}"
        final_aspect_ratio: AspectRatioEnum

        try:
            local_path = None
            if is_video:
                # --- Video Upload Logic ---
                os.makedirs(temp_dir, exist_ok=True)
                local_path = os.path.join(temp_dir, filename or "asset")
                with open(local_path, "wb") as buffer:
                    buffer.write(contents)

                # Check for valid aspect ratio early in the process
                final_aspect_ratio = await self._get_and_validate_aspect_ratio(
                    contents=contents,
                    is_video=is_video,
                    temp_video_path=local_path,
                    provided_aspect_ratio=aspect_ratio,
                )

                # Upload the original video
                final_gcs_uri = self.gcs_service.upload_file_to_gcs(
                    local_path=local_path,
                    destination_blob_name=f"source_assets/{user.id}/{file_hash}/{filename}",
                    mime_type="video/mp4",
                )

                # Generate and upload thumbnail
                thumbnail_path = generate_thumbnail(local_path)
                if thumbnail_path:
                    thumbnail_gcs_uri = self.gcs_service.upload_file_to_gcs(
                        local_path=thumbnail_path,
                        destination_blob_name=f"source_assets/{user.id}/{file_hash}/thumbnail.png",
                        mime_type="image/png",
                    )
            elif is_audio:
                # --- Audio Upload Logic ---
                # Audio files don't need image processing or aspect ratio
                final_aspect_ratio = aspect_ratio or AspectRatioEnum.RATIO_1_1

                # Determine audio mime type
                audio_mime = mime_type or "audio/mpeg"
                file_extension = (
                    os.path.splitext(filename or "audio.mp3")[1] or ".mp3"
                )

                # Upload the audio file directly
                final_gcs_uri = self.gcs_service.store_to_gcs(
                    folder=f"source_assets/{user.id}/audio",
                    file_name=f"{file_hash}{file_extension}",
                    mime_type=audio_mime,
                    contents=contents,
                    decode=False,
                )
            else:
                # --- Image Upload & Upscale Logic ---
                # Check for valid aspect ratio early in the process
                final_aspect_ratio = await self._get_and_validate_aspect_ratio(
                    contents=contents,
                    is_video=is_video,
                    temp_video_path=local_path,
                    provided_aspect_ratio=aspect_ratio,
                )

                # Convert image to PNG for standardization before storing.
                pil_image = PILImage.open(io.BytesIO(contents))
                png_contents: bytes

                if pil_image.format != "PNG":
                    with io.BytesIO() as output:
                        # Convert to RGB to avoid issues with palettes (e.g., in GIFs)
                        if pil_image.mode != "RGB":
                            pil_image = pil_image.convert("RGB")
                        pil_image.save(output, format="PNG")
                        png_contents = output.getvalue()
                else:
                    png_contents = contents

                # If the image is already high-resolution, we skip upscaling.
                # Validate resolution for upscaling
                max_output_pixels = (
                    17 * 1024 * 1024
                )  # ~17MP limit for Imagen 4 Upscale

                current_pixels = pil_image.width * pil_image.height

                # --- Upscale Conditional Logic ---
                if upscale_factor:
                    factor_int = 2
                    if upscale_factor == "x4":
                        factor_int = 4
                    elif upscale_factor == "x3":
                        factor_int = 3

                    projected_pixels = current_pixels * (
                        factor_int * factor_int
                    )

                    if projected_pixels > max_output_pixels:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                f"Image is too large for upscaling to {upscale_factor} times. "
                                f"Max output is ~17MP. Your image would result in ~{projected_pixels / 1000000:.1f}MP."
                            ),
                        )

                # --- Store Original ---
                original_gcs_uri = self.gcs_service.store_to_gcs(
                    folder=f"source_assets/{user.id}/originals",
                    file_name=f"{file_hash}.png",
                    mime_type=MimeTypeEnum.IMAGE_PNG,
                    contents=png_contents,
                    decode=False,
                )
                if not original_gcs_uri:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Could not store the original asset.",
                    )

                if upscale_factor:
                    try:
                        # Upscale the standardized PNG image.
                        upscale_dto = UpscaleImagenDto(
                            user_image=original_gcs_uri,
                            upscale_factor=upscale_factor,
                            mime_type=MimeTypeEnum.IMAGE_PNG,
                            generation_model=GenerationModelEnum.IMAGEN_4_UPSCALE_PREVIEW,
                            enhance_input_image=enhance_input_image or False,
                            image_preservation_factor=image_preservation_factor,
                        )
                        upscaled_result = (
                            await self.imagen_service.upscale_image(
                                upscale_dto,
                            )
                        )

                        if (
                            not upscaled_result
                            or not upscaled_result.image.gcs_uri
                        ):
                            logger.warning(
                                "Upscaling failed, using original image."
                            )
                            final_gcs_uri = original_gcs_uri
                        else:
                            final_gcs_uri = upscaled_result.image.gcs_uri
                            logger.info(
                                "Upscaling complete. Final asset at %s",
                                final_gcs_uri,
                            )
                    except Exception as e:
                        logger.error(
                            "Failed to upscale asset for user %s: %s",
                            user.email,
                            e,
                            exc_info=True,
                        )
                        # Fallback: if upscale fails, use the original URI
                        final_gcs_uri = original_gcs_uri
                else:
                    # No upscale requested, use original
                    final_gcs_uri = original_gcs_uri

            if not final_gcs_uri:
                raise RuntimeError("Failed to process and upload asset.")

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Asset processing failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process asset: {e}",
            ) from e
        finally:
            # Clean up the temporary directory if it was created
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

        # 4. Create and save the new UserAsset document
        # Determine mime_type based on content_type
        content_type = mime_type or ""
        mime_type = self._determine_mime_type_enum(content_type)

        is_admin = UserRoleEnum.ADMIN in user.roles
        final_scope = AssetScopeEnum.PRIVATE
        final_asset_type = asset_type or AssetTypeEnum.GENERIC_IMAGE

        if is_admin:
            # Admins can set scope and type freely.
            final_scope = scope or AssetScopeEnum.PRIVATE
        # Non-admins cannot set system-level scope.
        elif scope and scope != AssetScopeEnum.PRIVATE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can set a non-private scope.",
            )

        final_titles = [title] if title else []
        final_descriptions = [description] if description else []
        if metadata_generation_model:
            try:
                metadata = await asyncio.to_thread(
                    self.gemini_service.generate_media_metadata,
                    prompt="Describe this asset.",
                    media_uris=[final_gcs_uri],
                    model_name=metadata_generation_model,
                    mime_type=(
                        mime_type.value
                        if hasattr(mime_type, "value")
                        else content_type
                    ),
                )
                metadata_titles = metadata.get("titles")
                if metadata_titles:
                    final_titles = metadata_titles
                metadata_descriptions = metadata.get("descriptions")
                if metadata_descriptions:
                    final_descriptions = metadata_descriptions
            except Exception as e:
                logger.warning("Failed to generate metadata for asset: %s", e)

        new_asset = SourceAssetModel(
            workspace_id=workspace_id,
            user_id=user.id,
            aspect_ratio=final_aspect_ratio,
            original_gcs_uri=original_gcs_uri,
            gcs_uri=final_gcs_uri,
            thumbnail_gcs_uri=thumbnail_gcs_uri,
            original_filename=filename or "untitled",
            mime_type=mime_type,
            file_hash=file_hash,
            scope=final_scope,
            asset_type=final_asset_type,
            titles=final_titles,
            descriptions=final_descriptions,
        )
        created_asset = await self.repo.create(new_asset)
        new_asset.id = created_asset.id

        return await self._create_asset_response(new_asset)

    async def generate_signed_upload_url(
        self,
        request_dto: GenerateSourceAssetUploadUrlDto,
        current_user: UserModel,
    ) -> GenerateSourceAssetUploadUrlResponseDto:
        """Generates a GCS v4 signed URL for a client-side direct source asset upload.

        Uses same strategy as: backend/src/brand_guidelines/brand_guideline_service.py
        """
        file_uuid = str(uuid.uuid4())
        destination_blob_name = f"source_assets/{current_user.id}/uploads/{file_uuid}/{os.path.basename(request_dto.filename)}"

        signed_url, gcs_uri = await asyncio.to_thread(
            self.iam_signer.generate_v4_upload_signed_url,
            destination_blob_name,
            request_dto.content_type,
            self.gcs_service.bucket_name,
        )

        if not signed_url or not gcs_uri:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Could not generate upload URL.",
            )

        return GenerateSourceAssetUploadUrlResponseDto(
            upload_url=signed_url,
            gcs_uri=gcs_uri,
            file_uuid=file_uuid,
        )

    async def finalize_direct_upload(
        self,
        request_dto: FinalizeSourceAssetUploadDto,
        current_user: UserModel,
    ) -> SourceAssetResponseDto:
        """Finalizes registration of a source asset uploaded directly to GCS."""
        expected_prefix = f"gs://{self.gcs_service.bucket_name}/source_assets/{current_user.id}/"
        if (
            not request_dto.gcs_uri.startswith(expected_prefix)
            or ".." in request_dto.gcs_uri
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid GCS URI path.",
            )
        content_type = request_dto.mime_type or ""
        mime_type_enum = self._determine_mime_type_enum(content_type)

        is_admin = UserRoleEnum.ADMIN in current_user.roles
        final_scope = AssetScopeEnum.PRIVATE
        if is_admin:
            final_scope = request_dto.scope or AssetScopeEnum.PRIVATE
        elif request_dto.scope and request_dto.scope != AssetScopeEnum.PRIVATE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can set a non-private scope.",
            )

        if request_dto.asset_type:
            final_asset_type = request_dto.asset_type
        elif content_type.startswith("video/"):
            final_asset_type = AssetTypeEnum.GENERIC_VIDEO
        else:
            final_asset_type = AssetTypeEnum.GENERIC_IMAGE

        final_aspect_ratio = (
            request_dto.aspect_ratio or AspectRatioEnum.RATIO_1_1
        )

        # Fallback to hashing the GCS URI as a unique placeholder because the file content is not available on the server
        file_hash = hashlib.sha256(
            request_dto.gcs_uri.encode("utf-8")
        ).hexdigest()

        new_asset = SourceAssetModel(
            workspace_id=request_dto.workspace_id,
            user_id=current_user.id,
            aspect_ratio=final_aspect_ratio,
            original_gcs_uri=request_dto.gcs_uri,
            gcs_uri=request_dto.gcs_uri,
            thumbnail_gcs_uri=None,
            original_filename=request_dto.filename or "untitled",
            mime_type=mime_type_enum,
            file_hash=file_hash,
            scope=final_scope,
            asset_type=final_asset_type,
        )

        created_asset = await self.repo.create(new_asset)
        new_asset.id = created_asset.id

        return await self._create_asset_response(new_asset)

    async def convert_to_png(self, file: UploadFile) -> bytes:
        """Converts an uploaded image file (including HEIC/HEIF) to PNG format in memory."""
        try:
            contents = await file.read()
            if not contents:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Cannot convert an empty file.",
                )

            filename = file.filename or ""
            content_type = file.content_type or ""
            is_heic = filename.lower().endswith(
                (".heic", ".heif")
            ) or content_type.lower() in ["image/heic", "image/heif"]

            if is_heic:
                import tempfile
                from heic2png import HEIC2PNG

                with tempfile.NamedTemporaryFile(
                    suffix=".heic", delete=False
                ) as temp_in:
                    temp_in.write(contents)
                    temp_in_path = temp_in.name

                try:
                    heic_img = HEIC2PNG(temp_in_path, overwrite=True)
                    with tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False
                    ) as temp_out:
                        temp_out_path = temp_out.name

                    try:
                        heic_img.save(temp_out_path)
                        with open(temp_out_path, "rb") as f:
                            return f.read()
                    finally:
                        if os.path.exists(temp_out_path):
                            os.remove(temp_out_path)
                finally:
                    if os.path.exists(temp_in_path):
                        os.remove(temp_in_path)

            pil_image = PILImage.open(io.BytesIO(contents))

            # Convert to a standard color mode to handle various formats
            # (e.g., GIFs with palettes, CMYK) gracefully, preserving transparency.
            if pil_image.mode not in ["RGB", "RGBA"]:
                pil_image = pil_image.convert(
                    "RGBA" if "A" in pil_image.getbands() else "RGB",
                )

            # Save the converted image to an in-memory buffer
            with io.BytesIO() as output:
                pil_image.save(output, format="PNG")
                return output.getvalue()
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Failed to convert image to PNG: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process image: {e}",
            ) from e

    async def delete_asset(
        self,
        asset_id: int,
        current_user_id: int | None = None,
    ) -> bool:
        """Deletes an asset from Firestore and its corresponding file from GCS.
        This is an admin-only operation.

        Returns:
            bool: True if deletion was successful, False if the asset was not found.

        """
        # 1. Get the asset document from Firestore
        asset_to_delete = await self.repo.get_by_id(asset_id)
        if not asset_to_delete:
            logger.warning(
                "Attempted to delete non-existent asset with ID: %s",
                asset_id,
            )
            return False

        # 2. Skip deleting the file from GCS for soft delete
        # This allows for potential restoration of the asset in the future.
        # logger.info("Skipping GCS file deletion for soft delete: %s", asset_to_delete.gcs_uri)

        # 3. Mark the document as deleted in the database
        logger.info(
            "Soft deleting asset document from database with ID: %s by user: %s",
            asset_id,
            current_user_id,
        )
        return await self.repo.soft_delete(asset_id, deleted_by=current_user_id)

    async def list_assets_for_user(
        self,
        search_dto: SourceAssetSearchDto,
        target_user_id: int | None = None,
    ) -> PaginationResponseDto[SourceAssetResponseDto]:
        """Performs a paginated search, scoped to a target_user_id if provided."""
        assets_query_result = await self.repo.query(search_dto, target_user_id)
        assets = assets_query_result.data or []

        response_tasks = [
            self._create_asset_response(asset) for asset in assets
        ]
        enriched_assets = await asyncio.gather(*response_tasks)

        return PaginationResponseDto[SourceAssetResponseDto](
            count=assets_query_result.count,
            page=assets_query_result.page,
            page_size=assets_query_result.page_size,
            total_pages=assets_query_result.total_pages,
            data=enriched_assets,
        )

    async def get_all_vto_assets(self, user: UserModel) -> VtoAssetsResponseDto:
        """Fetches all system-level VTO assets and categorizes them.

        This is used to populate the VTO selection UI for users or admins.
        """
        vto_asset_types: list[AssetTypeEnum] = [
            AssetTypeEnum.VTO_PERSON_MALE,
            AssetTypeEnum.VTO_PERSON_FEMALE,
            AssetTypeEnum.VTO_TOP,
            AssetTypeEnum.VTO_BOTTOM,
            AssetTypeEnum.VTO_DRESS,
            AssetTypeEnum.VTO_SHOE,
        ]

        # Query for both system assets and the user's private assets in a single DB call.
        all_assets = await self.repo.find_system_and_private_assets_by_types(
            user.id,
            vto_asset_types,
        )

        # Create presigned URLs for all assets in parallel
        response_tasks = [
            self._create_asset_response(asset) for asset in all_assets
        ]
        enriched_assets = await asyncio.gather(*response_tasks)

        # Categorize the assets into the response DTO
        categorized_assets = VtoAssetsResponseDto()
        asset_map = {
            AssetTypeEnum.VTO_PERSON_MALE: categorized_assets.male_models,
            AssetTypeEnum.VTO_PERSON_FEMALE: categorized_assets.female_models,
            AssetTypeEnum.VTO_TOP: categorized_assets.tops,
            AssetTypeEnum.VTO_BOTTOM: categorized_assets.bottoms,
            AssetTypeEnum.VTO_DRESS: categorized_assets.dresses,
            AssetTypeEnum.VTO_SHOE: categorized_assets.shoes,
        }

        for asset in enriched_assets:
            if asset.asset_type in asset_map:
                asset_map[asset.asset_type].append(asset)

        return categorized_assets

    async def get_asset_by_id(
        self,
        asset_id: int,
        user: UserModel,
    ) -> SourceAssetResponseDto | None:
        """Retrieves a single source asset by ID, ensuring the user has access."""
        asset = await self.repo.get_by_id(asset_id)
        if not asset:
            return None

        # Authorization check
        is_admin = UserRoleEnum.ADMIN in user.roles
        is_owner = asset.user_id == user.id
        is_system = asset.scope in [
            AssetScopeEnum.SYSTEM,
        ]

        if not (is_admin or is_owner or is_system):
            return None

        # Fetch the owner's email and picture to display in the frontend
        owner_email = None
        owner_picture = None
        owner = await self.user_repo.get_by_id(asset.user_id)
        if owner:
            owner_email = owner.email
            owner_picture = owner.picture

        response = await self._create_asset_response(
            asset, user_email=owner_email, user_picture=owner_picture
        )
        response.tags = await self.tags_repo.get_tags_for_source_asset(asset_id)
        return response

    async def create_from_gcs_uri(
        self,
        user: UserModel,
        workspace_id: int,
        gcs_uri: str,
    ) -> SourceAssetResponseDto:
        """Creates a source asset from a GCS URI.
        Downloads the file, validates it, and re-uploads it to the system bucket.
        """
        # 1. Download bytes
        contents = await asyncio.to_thread(
            self.gcs_service.download_bytes_from_gcs,
            gcs_uri,
        )
        if not contents:
            raise ValueError(f"Could not read file from {gcs_uri}")

        # 2. Hash
        file_hash = hashlib.sha256(contents).hexdigest()

        # 3. Check duplicate
        existing_asset = await self.repo.find_by_hash(
            user.id, file_hash, workspace_id
        )
        if existing_asset:
            logger.info(
                "Duplicate asset found for user %s with hash %s. Returning existing.",
                user.email,
                file_hash[:8],
            )
            return await self._create_asset_response(existing_asset)

        # 4. Determine details
        filename = gcs_uri.rsplit("/", maxsplit=1)[-1]
        mime_type_guess, _ = mimetypes.guess_type(filename)
        is_video = mime_type_guess and "video" in mime_type_guess

        # Fallback if mimetype is unknown? assume boolean based on extension?
        if not mime_type_guess:
            # Basic extension check
            if filename.lower().endswith((".mp4", ".mov", ".avi")):
                is_video = True
            else:
                is_video = False

        final_gcs_uri: str | None = None
        thumbnail_gcs_uri: str | None = None
        temp_dir = f"temp/source_assets/{uuid.uuid4()}"
        final_aspect_ratio: AspectRatioEnum

        try:
            local_path = None
            if is_video:
                # --- Video Upload Logic ---
                os.makedirs(temp_dir, exist_ok=True)
                local_path = os.path.join(temp_dir, filename)
                with open(local_path, "wb") as buffer:
                    buffer.write(contents)

                # Check for valid aspect ratio early in the process
                final_aspect_ratio = await self._get_and_validate_aspect_ratio(
                    contents=contents,
                    is_video=is_video,
                    temp_video_path=local_path,
                )

                # Upload the video
                final_gcs_uri = self.gcs_service.upload_file_to_gcs(
                    local_path=local_path,
                    destination_blob_name=f"source_assets/{user.id}/{file_hash}/{filename}",
                    mime_type=mime_type_guess or "video/mp4",
                )

                # Generate and upload thumbnail
                thumbnail_path = generate_thumbnail(local_path)
                if thumbnail_path:
                    thumbnail_gcs_uri = self.gcs_service.upload_file_to_gcs(
                        local_path=thumbnail_path,
                        destination_blob_name=f"source_assets/{user.id}/{file_hash}/thumbnail.png",
                        mime_type="image/png",
                    )
            else:
                # --- Image Upload & Upscale Logic ---
                # Skip strict aspect ratio validation here for batch processing.
                # We allow any aspect ratio, falling back to 'other' if needed.

                # Convert image to PNG for standardization before storing.
                pil_image = PILImage.open(io.BytesIO(contents))
                png_contents: bytes

                if pil_image.format != "PNG":
                    with io.BytesIO() as output:
                        # Convert to RGB to avoid issues with palettes (e.g., in GIFs)
                        if pil_image.mode != "RGB":
                            pil_image = pil_image.convert("RGB")
                        pil_image.save(output, format="PNG")
                        png_contents = output.getvalue()
                else:
                    png_contents = contents

                # Determine aspect ratio (fallback to 'other' if non-standard)
                final_aspect_ratio = await self._get_and_validate_aspect_ratio(
                    contents=png_contents,
                    is_video=is_video,
                )

                final_gcs_uri = self.gcs_service.store_to_gcs(
                    folder=f"source_assets/{user.id}/originals",
                    file_name=f"{file_hash}.png",
                    mime_type=MimeTypeEnum.IMAGE_PNG,
                    contents=png_contents,
                    decode=False,
                )

            if not final_gcs_uri:
                raise RuntimeError("Failed to upload processed asset.")

        except Exception as e:
            logger.error("Batch asset processing failed: %s", e, exc_info=True)
            raise ValueError(f"Failed to process asset from GCS: {e!s}") from e
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

        # Create Record
        new_asset = SourceAssetModel(
            workspace_id=workspace_id,
            user_id=user.id,
            aspect_ratio=final_aspect_ratio,
            gcs_uri=final_gcs_uri,
            thumbnail_gcs_uri=thumbnail_gcs_uri,
            original_filename=filename,
            mime_type=(
                MimeTypeEnum.VIDEO_MP4 if is_video else MimeTypeEnum.IMAGE_PNG
            ),
            file_hash=file_hash,
            scope=AssetScopeEnum.PRIVATE,
            asset_type=AssetTypeEnum.GENERIC_IMAGE,
        )
        new_asset = await self.repo.create(new_asset)

        return await self._create_asset_response(new_asset)
