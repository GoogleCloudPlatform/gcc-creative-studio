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

"""Service for folder business logic and validations."""

import logging
from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from src.folders.dto.folder_dto import (
    FolderBreadcrumbDto,
    FolderCreateDto,
    FolderResponseDto,
    FolderTreeNodeDto,
    FolderUpdateDto,
    MoveItemsDto,
)
from src.folders.repository.folder_repository import FolderRepository
from src.folders.schema.folder_model import Folder
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)


class FolderService:
    """Service layer handling validation, hierarchy integrity, and business logic for folders."""

    def __init__(self, folder_repo: FolderRepository = Depends()):
        self.folder_repo = folder_repo

    async def create_folder(
        self, dto: FolderCreateDto, user: UserModel
    ) -> FolderResponseDto:
        """Creates a new folder after validating parent folder and name uniqueness."""
        name = dto.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Folder name cannot be empty.",
            )

        if dto.parent_id is not None:
            parent = await self.folder_repo.get_folder_by_id(dto.parent_id)
            if not parent or parent.workspace_id != dto.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent folder not found in this workspace.",
                )

        if await self.folder_repo.is_folder_name_taken(
            workspace_id=dto.workspace_id,
            parent_id=dto.parent_id,
            name=name,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A folder named '{name}' already exists in this location.",
            )

        folder = Folder(
            workspace_id=dto.workspace_id,
            user_id=user.id,
            user_email=user.email,
            name=name,
            parent_id=dto.parent_id,
            color=dto.color,
        )
        try:
            self.folder_repo.db.add(folder)
            await self.folder_repo.db.commit()
            await self.folder_repo.db.refresh(folder)
        except IntegrityError as e:
            await self.folder_repo.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A folder named '{name}' already exists in this location.",
            ) from e

        return FolderResponseDto(
            id=folder.id,
            workspace_id=folder.workspace_id,
            user_id=folder.user_id,
            user_email=folder.user_email,
            name=folder.name,
            parent_id=folder.parent_id,
            color=folder.color,
            item_count=0,
            subfolder_count=0,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )

    async def get_folders(
        self, workspace_id: int, parent_id: int | None = None
    ) -> list[FolderResponseDto]:
        """Lists folders within a workspace under the specified parent or root."""
        return await self.folder_repo.list_by_parent(
            workspace_id=workspace_id, parent_id=parent_id
        )

    async def get_folder_by_id(
        self, folder_id: int, workspace_id: int | None = None
    ) -> FolderResponseDto:
        """Fetch folder by ID with item and subfolder counts."""
        folder = await self.folder_repo.get_folder_by_id(folder_id)
        if not folder or (
            workspace_id is not None and folder.workspace_id != workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found in this workspace.",
            )

        # Get counts
        folders = await self.folder_repo.list_by_parent(
            workspace_id=folder.workspace_id, parent_id=folder.parent_id
        )
        matched = next((f for f in folders if f.id == folder_id), None)
        if matched:
            return matched

        return FolderResponseDto(
            id=folder.id,
            workspace_id=folder.workspace_id,
            user_id=folder.user_id,
            user_email=folder.user_email,
            name=folder.name,
            parent_id=folder.parent_id,
            color=folder.color,
            item_count=0,
            subfolder_count=0,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )

    async def get_breadcrumbs(
        self, folder_id: int, workspace_id: int | None = None
    ) -> list[FolderBreadcrumbDto]:
        """Fetch ancestor breadcrumb trail from root to the given folder."""
        folder = await self.folder_repo.get_folder_by_id(folder_id)
        if not folder or (
            workspace_id is not None and folder.workspace_id != workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found in this workspace.",
            )
        return await self.folder_repo.get_breadcrumbs(folder_id)

    async def get_folder_tree(
        self, workspace_id: int
    ) -> list[FolderTreeNodeDto]:
        """Returns the full hierarchical tree of folders in a workspace."""
        return await self.folder_repo.get_tree(workspace_id)

    async def update_folder(
        self, folder_id: int, dto: FolderUpdateDto, user: UserModel
    ) -> FolderResponseDto:
        """Updates a folder name, color, or parent hierarchy with collision checks and auto-disambiguation."""
        folder = await self.folder_repo.get_folder_by_id(folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found.",
            )

        is_moving = False
        new_parent_id = folder.parent_id

        # Handle moving folder to a new parent
        if dto.parent_id is not None or "parent_id" in dto.model_fields_set:
            new_parent_id = dto.parent_id
            if new_parent_id == folder.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A folder cannot be its own parent.",
                )

            if new_parent_id is not None:
                parent = await self.folder_repo.get_folder_by_id(new_parent_id)
                if not parent or parent.workspace_id != folder.workspace_id:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Target parent folder not found in this workspace.",
                    )

                # Prevent cycles: cannot move folder into its own subtree
                descendant_ids = await self.folder_repo.get_descendant_ids(
                    folder.id
                )
                if new_parent_id in descendant_ids:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot move a folder into one of its own subfolders.",
                    )

            if new_parent_id != folder.parent_id:
                is_moving = True
                folder.parent_id = new_parent_id

        target_name = dto.name.strip() if dto.name is not None else folder.name
        if not target_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Folder name cannot be empty.",
            )

        if is_moving:
            # Auto-disambiguate on move if colliding in target location
            unique_name = await self.folder_repo.get_unique_folder_name(
                workspace_id=folder.workspace_id,
                parent_id=new_parent_id,
                base_name=target_name,
                exclude_folder_id=folder.id,
            )
            folder.name = unique_name
        else:
            # Standard Rename (within same parent)
            if dto.name is not None and target_name != folder.name:
                if await self.folder_repo.is_folder_name_taken(
                    workspace_id=folder.workspace_id,
                    parent_id=folder.parent_id,
                    name=target_name,
                    exclude_folder_id=folder.id,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"A folder named '{target_name}' already exists in this location.",
                    )
                folder.name = target_name

        if dto.color is not None:
            folder.color = dto.color

        try:
            await self.folder_repo.db.commit()
            await self.folder_repo.db.refresh(folder)
        except IntegrityError as e:
            await self.folder_repo.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A folder named '{folder.name}' already exists in this location.",
            ) from e

        return await self.get_folder_by_id(folder.id)

    async def delete_folder(
        self, folder_id: int, user: UserModel
    ) -> dict[str, bool]:
        """Soft deletes a folder and its subfolders."""
        folder = await self.folder_repo.get_folder_by_id(folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found.",
            )

        success = await self.folder_repo.soft_delete(
            folder_id=folder_id, user_id=user.id
        )
        return {"success": success}

    async def move_items(
        self, dto: MoveItemsDto, user: UserModel
    ) -> dict[str, int]:
        """Batch moves media items, source assets, and folders to a destination folder."""
        dest_folder_id = dto.destination_folder_id
        if dest_folder_id is not None:
            dest_folder = await self.folder_repo.get_folder_by_id(
                dest_folder_id
            )
            if not dest_folder or dest_folder.workspace_id != dto.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Destination folder not found in this workspace.",
                )

        # Validate folder moves against cycle creation
        valid_folder_ids: list[int] = []
        if dto.folder_ids:
            for f_id in dto.folder_ids:
                if dest_folder_id == f_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Folder {f_id} cannot be moved into itself.",
                    )
                if dest_folder_id is not None:
                    descendant_ids = await self.folder_repo.get_descendant_ids(
                        f_id
                    )
                    if dest_folder_id in descendant_ids:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot move folder {f_id} into its own subfolder.",
                        )
                valid_folder_ids.append(f_id)

        media_moved = await self.folder_repo.move_media_items(
            media_item_ids=dto.media_item_ids,
            workspace_id=dto.workspace_id,
            destination_folder_id=dest_folder_id,
        )
        assets_moved = await self.folder_repo.move_source_assets(
            source_asset_ids=dto.source_asset_ids,
            workspace_id=dto.workspace_id,
            destination_folder_id=dest_folder_id,
        )
        folders_moved = await self.folder_repo.move_folders(
            folder_ids=valid_folder_ids,
            workspace_id=dto.workspace_id,
            destination_folder_id=dest_folder_id,
        )

        return {
            "media_items_moved": media_moved,
            "source_assets_moved": assets_moved,
            "folders_moved": folders_moved,
            "total_moved": media_moved + assets_moved + folders_moved,
        }
