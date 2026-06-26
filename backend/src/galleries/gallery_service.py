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

import asyncio
import logging
import mimetypes
import tempfile
import zipfile

from fastapi import Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.media_item_model import (
    JobStatusEnum,
    MediaItemModel,
    SourceAssetLink,
    SourceMediaItemLink,
)
from src.common.storage_service import GcsService
from src.galleries.dto.bulk_copy_dto import BulkCopyDto
from src.galleries.dto.bulk_delete_dto import BulkDeleteDto
from src.galleries.dto.bulk_download_dto import BulkDownloadDto
from src.galleries.dto.gallery_response_dto import (
    MediaItemResponse,
    SourceAssetLinkResponse,
    SourceMediaItemLinkResponse,
)
from src.galleries.dto.gallery_search_dto import GallerySearchDto
from src.galleries.dto.unified_gallery_response import (
    UnifiedGalleryItemResponse,
)
from src.galleries.repository.unified_gallery_repository import (
    UnifiedGalleryRepository,
)
from src.images.imagen_service import ImagenService
from src.images.repository.media_item_repository import MediaRepository
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.workspace_auth_guard import WorkspaceAuth
from src.tags.repository.tags_repository import TagsRepository

logger = logging.getLogger(__name__)


class GalleryService:
    """Provides business logic for querying media items and preparing them for the gallery."""

    def __init__(
        self,
        media_repo: MediaRepository = Depends(),
        source_asset_repo: SourceAssetRepository = Depends(),
        unified_gallery_repo: UnifiedGalleryRepository = Depends(),
        user_repo: UserRepository = Depends(),
        workspace_repo: WorkspaceRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
        workspace_auth: WorkspaceAuth = Depends(),
        imagen_service: ImagenService = Depends(),
        gcs_service: GcsService = Depends(),
        tags_repo: TagsRepository = Depends(),
    ):
        """Initializes the service with its dependencies."""
        self.media_repo = media_repo
        self.source_asset_repo = source_asset_repo
        self.unified_gallery_repo = unified_gallery_repo
        self.user_repo = user_repo
        self.workspace_repo = workspace_repo
        self.iam_signer_credentials = iam_signer_credentials
        self.workspace_auth = workspace_auth
        self.imagen_service = imagen_service
        self.gcs_service = gcs_service
        self.tags_repo = tags_repo

    async def _enrich_source_asset_link(
        self,
        link: SourceAssetLink,
    ) -> SourceAssetLinkResponse | None:
        """Fetches the source asset document and generates a presigned URL for it."""
        asset_doc = await self.source_asset_repo.get_by_id(link.asset_id)

        if not asset_doc:
            return None

        tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url,
                asset_doc.gcs_uri,
            ),
        ]

        # Check if the asset has a thumbnail and create a task for it.
        # This requires the SourceAsset model to have a `thumbnail_gcs_uri` field.
        if asset_doc.thumbnail_gcs_uri:
            tasks.append(
                asyncio.to_thread(
                    self.iam_signer_credentials.generate_presigned_url,
                    asset_doc.thumbnail_gcs_uri,
                ),
            )

        results = await asyncio.gather(*tasks)
        presigned_url = results[0]
        presigned_thumbnail_url = results[1] if len(results) > 1 else None

        return SourceAssetLinkResponse(
            **link.model_dump(),
            presigned_url=presigned_url,
            presigned_thumbnail_url=presigned_thumbnail_url,
            gcs_uri=asset_doc.gcs_uri,
            mime_type=asset_doc.mime_type,
        )

    async def _enrich_source_media_item_link(
        self,
        link: SourceMediaItemLink,
    ) -> SourceMediaItemLinkResponse | None:
        """Fetches the parent MediaItem document and generates a presigned URL
        for the specific image that was used as input.
        """
        parent_item = await self.media_repo.get_by_id(link.media_item_id)
        if (
            not parent_item
            or not parent_item.gcs_uris
            or not (0 <= link.media_index < len(parent_item.gcs_uris))
        ):
            return None

        # Get the specific GCS URI of the parent image that was edited.
        parent_gcs_uri = parent_item.gcs_uris[link.media_index]

        # Prepare tasks for both the main media and its thumbnail
        tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url,
                parent_gcs_uri,
            ),
        ]

        parent_thumbnail_gcs_uri = None
        if parent_item.thumbnail_uris and 0 <= link.media_index < len(
            parent_item.thumbnail_uris,
        ):
            parent_thumbnail_gcs_uri = parent_item.thumbnail_uris[
                link.media_index
            ]
            tasks.append(
                asyncio.to_thread(
                    self.iam_signer_credentials.generate_presigned_url,
                    parent_thumbnail_gcs_uri,
                ),
            )

        results = await asyncio.gather(*tasks)
        presigned_url = results[0]
        presigned_thumbnail_url = results[1] if len(results) > 1 else None

        return SourceMediaItemLinkResponse(
            **link.model_dump(),
            presigned_url=presigned_url,
            presigned_thumbnail_url=presigned_thumbnail_url,
            gcs_uri=parent_gcs_uri,
            mime_type=parent_item.mime_type,
        )

    async def _create_gallery_response(
        self, item: MediaItemModel
    ) -> MediaItemResponse:
        """Helper function to convert a MediaItem into a GalleryItemResponse
        by generating presigned URLs in parallel for its GCS URIs.
        """
        all_gcs_uris = item.gcs_uris or []

        # 1. Create tasks for main media URLs
        main_url_tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url, uri
            )
            for uri in all_gcs_uris
            if uri
        ]

        # 1.5 Create tasks for original media URLs
        all_original_gcs_uris = item.original_gcs_uris or []
        original_url_tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url, uri
            )
            for uri in all_original_gcs_uris
            if uri
        ]

        # 2. Create tasks for thumbnail URLs
        thumbnail_tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url, uri
            )
            for uri in (item.thumbnail_uris or "")
            if uri
        ]

        # 3. Create tasks for source asset URLs
        source_asset_tasks = []
        if item.source_assets:
            source_asset_tasks = [
                self._enrich_source_asset_link(link)
                for link in item.source_assets
            ]

        # 4. Create tasks for generated input asset URLs
        source_media_item_tasks = []
        if item.source_media_items:
            source_media_item_tasks = [
                self._enrich_source_media_item_link(link)
                for link in item.source_media_items
            ]

        # 5. Gather all results concurrently
        (
            presigned_urls,
            original_presigned_urls,
            presigned_thumbnail_urls,
            enriched_source_assets_with_nones,
            enriched_source_media_items_with_nones,
        ) = await asyncio.gather(
            asyncio.gather(*main_url_tasks),
            asyncio.gather(*original_url_tasks),
            asyncio.gather(*thumbnail_tasks),
            asyncio.gather(*source_asset_tasks),
            asyncio.gather(*source_media_item_tasks),
        )

        enriched_source_assets = [
            asset for asset in enriched_source_assets_with_nones if asset
        ]
        enriched_source_media_items = [
            asset for asset in enriched_source_media_items_with_nones if asset
        ]

        # Create the response DTO, copying all original data and adding the new URLs
        return MediaItemResponse(
            **item.model_dump(exclude={"source_assets"}),
            presigned_urls=presigned_urls,
            original_presigned_urls=original_presigned_urls,
            presigned_thumbnail_urls=presigned_thumbnail_urls,
            enriched_source_assets=enriched_source_assets or None,
            enriched_source_media_items=enriched_source_media_items or None,
        )

    async def _enrich_unified_item(
        self,
        item: UnifiedGalleryItemResponse,
    ) -> UnifiedGalleryItemResponse:
        """Enriches a UnifiedGalleryItemResponse with presigned URLs."""

        # Helper to safely get list or string as list
        def as_list(val):
            if isinstance(val, list):
                return val
            return [val] if val else []

        uris_to_sign = []
        thumbnail_uris_to_sign = []

        uris_to_sign = item.gcs_uris or []
        thumbnail_uris_to_sign = item.thumbnail_uris or []

        # Create tasks
        url_tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url, uri
            )
            for uri in uris_to_sign
            if uri
        ]

        thumbnail_tasks = [
            asyncio.to_thread(
                self.iam_signer_credentials.generate_presigned_url, uri
            )
            for uri in thumbnail_uris_to_sign
            if uri
        ]

        (presigned_urls, presigned_thumbnail_urls) = await asyncio.gather(
            asyncio.gather(*url_tasks),
            asyncio.gather(*thumbnail_tasks),
        )

        item.presigned_urls = presigned_urls
        item.presigned_thumbnail_urls = presigned_thumbnail_urls
        return item

    async def get_paginated_gallery(
        self,
        search_dto: GallerySearchDto,
        current_user: UserModel,
    ) -> PaginationResponseDto[UnifiedGalleryItemResponse]:
        """Performs a paginated and filtered search for media items.
        Authorization is handled by a dependency in the controller.
        """
        is_admin = UserRoleEnum.ADMIN in current_user.roles
        # If the user is not an admin, force the search to only show completed items
        if not is_admin:
            search_dto.status = JobStatusEnum.COMPLETED

        # Run the database query directly (it is async)
        # We assume UnifiedGalleryRepository.query handles filtering
        unified_items_query = await self.unified_gallery_repo.query(
            search_dto,
        )
        unified_items = unified_items_query.data or []

        # Convert each MediaItem to a GalleryItemResponse in parallel
        response_tasks = [
            self._enrich_unified_item(item) for item in unified_items
        ]
        enriched_items = await asyncio.gather(*response_tasks)

        return PaginationResponseDto[UnifiedGalleryItemResponse](
            count=unified_items_query.count,
            page=unified_items_query.page,
            page_size=unified_items_query.page_size,
            total_pages=unified_items_query.total_pages,
            data=enriched_items,
        )

    async def get_media_by_id(
        self,
        item_id: int,
        current_user: UserModel,
    ) -> MediaItemResponse | None:
        """Retrieves a single media item, performs an authorization check,
        and enriches it with presigned URLs.
        """
        # Run the synchronous database query in a separate thread
        is_admin = UserRoleEnum.ADMIN in current_user.roles
        item = await self.media_repo.get_by_id(
            item_id, include_deleted=is_admin
        )

        if not item:
            return None

        # Fetch the workspace for authorization check
        workspace = await self.workspace_repo.get_by_id(item.workspace_id)

        # This should ideally not happen if data is consistent, but it's a good safeguard.
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent workspace for this item not found.",
            )

        # Use the centralized authorization logic
        await self.workspace_auth.authorize(
            workspace_id=item.workspace_id,
            user=current_user,
        )

        response = await self._create_gallery_response(item)
        response.tags = await self.tags_repo.get_tags_for_media_item(item_id)
        if item.user_id:
            user = await self.user_repo.get_by_id(item.user_id)
            if user:
                response.user_picture = user.picture
        return response

    async def bulk_delete(
        self,
        bulk_delete_dto: BulkDeleteDto,
        current_user: UserModel,
    ) -> dict[str, int]:
        """Deletes multiple gallery items after authorizing the workspace access."""
        # 1. Authorize workspace access
        await self.workspace_auth.authorize(
            workspace_id=bulk_delete_dto.workspace_id,
            user=current_user,
        )

        deleted_count = 0
        for item in bulk_delete_dto.items:
            try:
                if item.type == "media_item":
                    media_item = await self.media_repo.get_by_id(item.id)
                    if not media_item:
                        continue

                    if media_item.workspace_id != bulk_delete_dto.workspace_id:
                        logger.warning(
                            f"Refusing to delete media_item {item.id} outside requested workspace bounds.",
                        )
                        continue

                    is_admin = UserRoleEnum.ADMIN in current_user.roles
                    is_owner = (
                        getattr(media_item, "user_id", None) == current_user.id
                    )
                    if not is_admin and not is_owner:
                        logger.warning(
                            f"User {current_user.id} unauthorized to delete media {item.id}",
                        )
                        continue

                    await self.media_repo.soft_delete(
                        item.id,
                        deleted_by=current_user.id,
                    )
                    deleted_count += 1
                elif item.type == "source_asset":
                    asset = await self.source_asset_repo.get_by_id(item.id)
                    if not asset:
                        continue

                    if asset.workspace_id != bulk_delete_dto.workspace_id:
                        logger.warning(
                            f"Refusing to delete source_asset {item.id} outside requested workspace bounds.",
                        )
                        continue

                    is_admin = UserRoleEnum.ADMIN in current_user.roles
                    is_owner = (
                        getattr(asset, "user_id", None) == current_user.id
                    )
                    if not is_admin and not is_owner:
                        logger.warning(
                            f"User {current_user.id} unauthorized to delete asset {item.id}",
                        )
                        continue

                    await self.source_asset_repo.soft_delete(
                        item.id,
                        deleted_by=current_user.id,
                    )
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting {item.type} {item.id}: {e}")

        return {"deleted_count": deleted_count}

    async def restore_item(
        self,
        item_id: int,
        item_type: str,
        current_user: UserModel,
    ) -> bool:
        """Restores a soft-deleted item (media_item or source_asset) after authorizing roles."""
        is_admin = UserRoleEnum.ADMIN in current_user.roles
        if not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can restore items.",
            )

        if item_type == "media_item":
            result = await self.media_repo.restore(item_id)
        elif item_type == "source_asset":
            result = await self.source_asset_repo.restore(item_id)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid item_type: {item_type}",
            )

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"{item_type} with ID {item_id} not found",
            )

        return True

    async def bulk_download(
        self,
        bulk_download_dto: BulkDownloadDto,
        current_user: UserModel,
    ) -> StreamingResponse:
        """Creates a ZIP archive of the selected media items and streams it to the client."""
        # 1. Authorize workspace access
        await self.workspace_auth.authorize(
            workspace_id=bulk_download_dto.workspace_id,
            user=current_user,
        )

        # Create a temporary file to hold the ZIP archive to avoid OOM
        temp_file = tempfile.TemporaryFile()
        downloads_log = []

        try:
            with zipfile.ZipFile(
                temp_file,
                "w",
                zipfile.ZIP_DEFLATED,
                True,
            ) as zip_file:
                for item in bulk_download_dto.items:
                    try:
                        gcs_uri = None
                        filename = None

                        if item.type == "media_item":
                            media_item = await self.media_repo.get_by_id(
                                item.id
                            )
                            if not media_item:
                                continue

                            # Authorize workspace access for this item
                            await self.workspace_auth.authorize(
                                workspace_id=media_item.workspace_id,
                                user=current_user,
                            )
                            if media_item.gcs_uris:
                                gcs_uri = media_item.gcs_uris[0]
                                mime_type = getattr(
                                    media_item, "mime_type", None
                                )

                                # Use mimetypes library for guessing extension
                                ext = "bin"
                                if mime_type:
                                    ext = (
                                        mimetypes.guess_extension(
                                            str(mime_type)
                                        )
                                        or "bin"
                                    )
                                    if ext.startswith("."):
                                        ext = ext[1:]
                                elif "." in gcs_uri:
                                    ext = gcs_uri.split(".")[-1]

                                filename = f"media_{item.id}.{ext}"
                        elif item.type == "source_asset":
                            asset = await self.source_asset_repo.get_by_id(
                                item.id
                            )
                            if not asset:
                                continue

                            # Authorize workspace access for this asset
                            await self.workspace_auth.authorize(
                                workspace_id=asset.workspace_id,
                                user=current_user,
                            )
                            if asset.gcs_uri:
                                gcs_uri = asset.gcs_uri
                                ext = (
                                    gcs_uri.split(".")[-1]
                                    if "." in gcs_uri
                                    else "bin"
                                )
                                filename = f"asset_{item.id}.{ext}"

                        if gcs_uri and filename:
                            try:
                                # Stream from GCS directly into ZipFile.open() to avoid OOM
                                def stream_to_zip():
                                    with zip_file.open(filename, "w") as zf:
                                        for (
                                            chunk
                                        ) in self.gcs_service.download_stream_from_gcs(
                                            gcs_uri,
                                        ):
                                            zf.write(chunk)

                                await asyncio.to_thread(stream_to_zip)
                                downloads_log.append(f"- Success: {filename}")
                            except Exception as e:
                                downloads_log.append(
                                    f"- Failed: {filename} ({e})"
                                )
                                logger.error(
                                    f"Error streaming {item.type} {item.id} to ZIP: {e}",
                                )
                    except Exception as e:
                        logger.error(
                            f"Error processing {item.type} {item.id}: {e}"
                        )

                # Add failure / success manifest README
                if downloads_log:
                    manifest_content = (
                        "Bulk Download Manifest\n======================\n\n"
                        + "\n".join(downloads_log)
                    )
                    zip_file.writestr("manifest.txt", manifest_content)

            # Seek to beginning for streaming
            temp_file.seek(0)

            async def iter_file():
                try:
                    while True:
                        # Use asyncio.to_thread to read from disk without blocking the event loop
                        chunk = await asyncio.to_thread(temp_file.read, 8192)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    temp_file.close()  # Delete TemporaryFile

            return StreamingResponse(
                iter_file(),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename=workspace_{bulk_download_dto.workspace_id}_bulk_download.zip",
                },
            )

        except Exception as e:
            temp_file.close()
            raise e

    async def bulk_copy(
        self,
        bulk_copy_dto: BulkCopyDto,
        current_user: UserModel,
    ) -> dict:
        """Copies multiple gallery items to a target workspace."""
        # 1. Authorize target workspace access
        await self.workspace_auth.authorize(
            workspace_id=bulk_copy_dto.target_workspace_id,
            user=current_user,
        )

        copied_count = 0
        for item in bulk_copy_dto.items:
            try:
                if item.type == "media_item":
                    media_item = await self.media_repo.get_by_id(item.id)
                    if not media_item:
                        continue

                    # Authorize source workspace access (where the item is currently)
                    await self.workspace_auth.authorize(
                        workspace_id=media_item.workspace_id,
                        user=current_user,
                    )

                    # Create a new MediaItem instance with updated workspace_id
                    # exclude 'id', 'created_at', 'updated_at', 'deleted_at', 'deleted_by'
                    new_item_data = media_item.model_dump(
                        exclude={
                            "id",
                            "created_at",
                            "updated_at",
                            "deleted_at",
                            "deleted_by",
                            "workspace_id",
                        },
                    )
                    new_item_data["workspace_id"] = (
                        bulk_copy_dto.target_workspace_id
                    )

                    # Ensure user_id and user_email are set to the current user copying
                    new_item_data["user_id"] = current_user.id
                    new_item_data["user_email"] = current_user.email

                    await self.media_repo.create(new_item_data)
                    copied_count += 1

                elif item.type == "source_asset":
                    asset = await self.source_asset_repo.get_by_id(item.id)
                    if not asset:
                        continue

                    # Authorize source workspace access
                    await self.workspace_auth.authorize(
                        workspace_id=asset.workspace_id,
                        user=current_user,
                    )

                    # Create a new SourceAsset instance with updated workspace_id
                    new_asset_data = asset.model_dump(
                        exclude={
                            "id",
                            "created_at",
                            "updated_at",
                            "deleted_at",
                            "deleted_by",
                            "workspace_id",
                        },
                    )
                    new_asset_data["workspace_id"] = (
                        bulk_copy_dto.target_workspace_id
                    )

                    # Ensure user_id is set to the current user copying
                    new_asset_data["user_id"] = current_user.id

                    await self.source_asset_repo.create(new_asset_data)
                    copied_count += 1

            except Exception as e:
                logger.error(f"Error copying {item.type} {item.id}: {e}")

        return {"copied_count": copied_count}
