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
    ConflictStrategyEnum,
    FolderBreadcrumbDto,
    FolderCreateDto,
    FolderResponseDto,
    FolderTreeNodeDto,
    FolderUpdateDto,
    MoveItemsDto,
    CopyItemsDto,
)
from src.folders.repository.folder_repository import FolderRepository
from src.folders.schema.folder_model import Folder
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)

MAX_FOLDER_DEPTH: int = 20


class FolderService:
    """Service layer handling validation, hierarchy integrity, and business logic for folders."""

    def __init__(self, folder_repo: FolderRepository = Depends()):
        self.folder_repo = folder_repo

    async def _handle_integrity_error(
        self, e: IntegrityError, folder_name: str
    ) -> None:
        """Inspects an IntegrityError and raises an appropriate HTTPException.

        Differentiates between unique constraint violations (e.g. name collisions),
        foreign key constraint violations (e.g. non-existent workspace, user, parent),
        and other database integrity errors.
        """
        await self.folder_repo.db.rollback()
        logger.warning(
            "IntegrityError during folder operation for folder '%s': %s",
            folder_name,
            e,
        )

        orig = getattr(e, "orig", None)
        pgcode = (
            getattr(orig, "pgcode", None)
            or getattr(orig, "sqlstate", None)
            or getattr(e, "pgcode", None)
        )

        error_parts = [
            str(e),
            str(orig) if orig is not None else "",
            str(getattr(orig, "detail", "") or ""),
            str(getattr(orig, "constraint_name", "") or ""),
        ]
        diag = getattr(orig, "diag", None)
        if diag is not None:
            error_parts.append(str(getattr(diag, "constraint_name", "") or ""))
            error_parts.append(str(getattr(diag, "message_detail", "") or ""))

        combined_msg = " ".join(error_parts).lower()

        is_fk = (
            pgcode == "23503"
            or "foreign key" in combined_msg
            or "foreignkey" in combined_msg
            or "is not present in table" in combined_msg
            or "violates foreign key constraint" in combined_msg
        )
        is_unique = (
            pgcode == "23505"
            or "unique" in combined_msg
            or "duplicate key" in combined_msg
            or "uq_" in combined_msg
        )

        # 1. Foreign Key Constraint Violation
        if pgcode == "23503" or (is_fk and not is_unique):
            if "workspace" in combined_msg:
                detail = "The specified workspace does not exist."
            elif "user" in combined_msg:
                detail = "The specified user does not exist."
            elif "parent" in combined_msg:
                detail = "The specified parent folder does not exist."
            else:
                detail = "Referenced entity (workspace, user, or parent folder) does not exist."
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            ) from e

        # 2. Unique Constraint Violation
        if pgcode == "23505" or is_unique:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A folder named '{folder_name}' already exists in this location.",
            ) from e

        # 3. Other Database Integrity Errors (e.g. check constraints, not-null constraints)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database integrity constraint violation.",
        ) from e

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
            parent_depth = await self.folder_repo.get_folder_depth(
                dto.parent_id
            )
            if parent_depth >= MAX_FOLDER_DEPTH:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot create folder: maximum folder tree depth of {MAX_FOLDER_DEPTH} levels reached.",
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
            await self._handle_integrity_error(e, name)

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

    async def get_raw_folder(
        self, folder_id: int, workspace_id: int | None = None
    ) -> Folder:
        """Fetch raw Folder model by ID without computing count subqueries."""
        folder = await self.folder_repo.get_folder_by_id(folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found.",
            )
        if workspace_id is not None and folder.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found in this workspace.",
            )
        return folder

    get_folder_model = get_raw_folder

    async def get_folder_by_id(
        self, folder_id: int, workspace_id: int | None = None
    ) -> FolderResponseDto:
        """Fetch folder by ID with item and subfolder counts."""
        folder = await self.folder_repo.get_folder_by_id(folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found.",
            )
        if workspace_id is not None and folder.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found in this workspace.",
            )

        # Get counts
        item_count, subfolder_count = await self.folder_repo.get_folder_counts(
            folder.id
        )

        return FolderResponseDto(
            id=folder.id,
            workspace_id=folder.workspace_id,
            user_id=folder.user_id,
            user_email=folder.user_email,
            name=folder.name,
            parent_id=folder.parent_id,
            color=folder.color,
            item_count=item_count,
            subfolder_count=subfolder_count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )

    async def get_breadcrumbs(
        self, folder_id: int, workspace_id: int | None = None
    ) -> list[FolderBreadcrumbDto]:
        """Fetch ancestor breadcrumb trail from root to the given folder."""
        breadcrumbs = await self.folder_repo.get_breadcrumbs(folder_id)
        if not breadcrumbs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found.",
            )

        # Verify the workspace on the target folder (which will be the last item in breadcrumbs)
        if (
            workspace_id is not None
            and breadcrumbs[-1].workspace_id != workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder with ID {folder_id} not found in this workspace.",
            )
        return breadcrumbs

    async def get_folder_tree(
        self, workspace_id: int
    ) -> list[FolderTreeNodeDto]:
        """Returns the full hierarchical tree of folders in a workspace."""
        return await self.folder_repo.get_tree(workspace_id)

    async def update_folder(
        self,
        folder_id: int,
        dto: FolderUpdateDto,
        user: UserModel,
        folder: Folder | None = None,
    ) -> FolderResponseDto:
        """Updates a folder name, color, or parent hierarchy with collision checks and auto-disambiguation."""
        if folder is None:
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
                if new_parent_id is not None:
                    dest_depth = await self.folder_repo.get_folder_depth(
                        new_parent_id
                    )
                    subtree_depth = await self.folder_repo.get_subtree_depth(
                        folder.id
                    )
                    if dest_depth + subtree_depth > MAX_FOLDER_DEPTH:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot move folder: would exceed maximum folder tree depth of {MAX_FOLDER_DEPTH} levels.",
                        )
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

        if dto.color is not None or "color" in dto.model_fields_set:
            folder.color = dto.color

        try:
            await self.folder_repo.db.commit()
            await self.folder_repo.db.refresh(folder)
        except IntegrityError as e:
            await self._handle_integrity_error(e, folder.name)

        item_count, subfolder_count = await self.folder_repo.get_folder_counts(
            folder.id
        )

        return FolderResponseDto(
            id=folder.id,
            workspace_id=folder.workspace_id,
            user_id=folder.user_id,
            user_email=folder.user_email,
            name=folder.name,
            parent_id=folder.parent_id,
            color=folder.color,
            item_count=item_count,
            subfolder_count=subfolder_count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )

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
        dest_depth = 0
        if dest_folder_id is not None:
            dest_folder = await self.folder_repo.get_folder_by_id(
                dest_folder_id
            )
            if not dest_folder or dest_folder.workspace_id != dto.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Destination folder not found in this workspace.",
                )
            dest_depth = await self.folder_repo.get_folder_depth(dest_folder_id)

        # Validate folder moves against cycle creation and tree depth limit
        valid_folder_ids: list[int] = []
        if dto.folder_ids:
            unique_folder_ids = list(dict.fromkeys(dto.folder_ids))
            for f_id in unique_folder_ids:
                if dest_folder_id == f_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Folder {f_id} cannot be moved into itself.",
                    )

            # Validate workspace ownership in a single batch query beforehand to prevent
            # executing expensive recursive queries on foreign/invalid folders.
            folders = await self.folder_repo.get_folders_by_ids(
                folder_ids=unique_folder_ids,
                workspace_id=dto.workspace_id,
            )
            if len(folders) != len(unique_folder_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more specified folders were not found in this workspace.",
                )

            for folder in folders:
                f_id = folder.id
                if dest_folder_id is not None:
                    descendant_ids = await self.folder_repo.get_descendant_ids(
                        f_id
                    )
                    if dest_folder_id in descendant_ids:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot move folder {f_id} into its own subfolder.",
                        )
                    subtree_depth = await self.folder_repo.get_subtree_depth(
                        f_id
                    )
                    if dest_depth + subtree_depth > MAX_FOLDER_DEPTH:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot move folder: would exceed maximum folder tree depth of {MAX_FOLDER_DEPTH} levels.",
                        )
                valid_folder_ids.append(f_id)

            if dto.conflict_strategy is None and valid_folder_ids:
                existing_map = await self.folder_repo.get_existing_folders_map(
                    workspace_id=dto.workspace_id,
                    parent_id=dest_folder_id,
                    exclude_folder_ids=valid_folder_ids,
                )
                conflicts = []
                for f_id in valid_folder_ids:
                    f_obj = next((f for f in folders if f.id == f_id), None)
                    if f_obj and f_obj.parent_id != dest_folder_id:
                        key = f_obj.name.strip().lower()
                        if key in existing_map:
                            conflicts.append(
                                {
                                    "folder_id": f_obj.id,
                                    "folder_name": f_obj.name,
                                    "target_folder_id": existing_map[key].id,
                                }
                            )
                if conflicts:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "FOLDER_COLLISION",
                            "conflicts": conflicts,
                        },
                    )

        try:
            media_moved = await self.folder_repo.move_media_items(
                media_item_ids=dto.media_item_ids,
                workspace_id=dto.workspace_id,
                destination_folder_id=dest_folder_id,
                commit=False,
            )
            assets_moved = await self.folder_repo.move_source_assets(
                source_asset_ids=dto.source_asset_ids,
                workspace_id=dto.workspace_id,
                destination_folder_id=dest_folder_id,
                commit=False,
            )
            folders_moved = await self.folder_repo.move_folders(
                folder_ids=valid_folder_ids,
                workspace_id=dto.workspace_id,
                destination_folder_id=dest_folder_id,
                conflict_strategy=dto.conflict_strategy
                or ConflictStrategyEnum.KEEP_BOTH,
                user_id=user.id,
                user_email=user.email,
                commit=False,
            )
            await self.folder_repo.db.commit()
        except IntegrityError as e:
            await self.folder_repo.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A database conflict occurred while moving items.",
            ) from e
        except Exception:
            await self.folder_repo.db.rollback()
            raise

        return {
            "media_items_moved": media_moved,
            "source_assets_moved": assets_moved,
            "folders_moved": folders_moved,
            "total_moved": media_moved + assets_moved + folders_moved,
        }

    async def copy_items(
        self, dto: CopyItemsDto, user: UserModel
    ) -> dict[str, int]:
        """Batch copies media items, source assets, and folders to a destination folder."""
        dest_folder_id = dto.destination_folder_id
        dest_depth = 0
        if dest_folder_id is not None:
            dest_folder = await self.folder_repo.get_folder_by_id(
                dest_folder_id
            )
            if not dest_folder or dest_folder.workspace_id != dto.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Destination folder not found in this workspace.",
                )
            dest_depth = await self.folder_repo.get_folder_depth(dest_folder_id)

        valid_folder_ids: list[int] = []
        if dto.folder_ids:
            unique_folder_ids = list(dict.fromkeys(dto.folder_ids))
            folders = await self.folder_repo.get_folders_by_ids(
                folder_ids=unique_folder_ids,
                workspace_id=dto.workspace_id,
            )
            if len(folders) != len(unique_folder_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more specified folders were not found in this workspace.",
                )

            for folder in folders:
                f_id = folder.id
                if dest_folder_id is not None:
                    subtree_depth = await self.folder_repo.get_subtree_depth(
                        f_id
                    )
                    if dest_depth + subtree_depth > MAX_FOLDER_DEPTH:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cannot copy folder: would exceed maximum folder tree depth of {MAX_FOLDER_DEPTH} levels.",
                        )
                valid_folder_ids.append(f_id)

            if dto.conflict_strategy is None and valid_folder_ids:
                existing_map = await self.folder_repo.get_existing_folders_map(
                    workspace_id=dto.workspace_id,
                    parent_id=dest_folder_id,
                    exclude_folder_ids=valid_folder_ids,
                )
                conflicts = []
                for f_id in valid_folder_ids:
                    f_obj = next((f for f in folders if f.id == f_id), None)
                    if f_obj:
                        key = f_obj.name.strip().lower()
                        if key in existing_map:
                            conflicts.append(
                                {
                                    "folder_id": f_obj.id,
                                    "folder_name": f_obj.name,
                                    "target_folder_id": existing_map[key].id,
                                }
                            )
                if conflicts:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "FOLDER_COLLISION",
                            "conflicts": conflicts,
                        },
                    )

        return await self.folder_repo.copy_items(
            workspace_id=dto.workspace_id,
            media_item_ids=dto.media_item_ids,
            source_asset_ids=dto.source_asset_ids,
            folder_ids=valid_folder_ids,
            destination_folder_id=dest_folder_id,
            conflict_strategy=dto.conflict_strategy
            or ConflictStrategyEnum.KEEP_BOTH,
            user_id=user.id,
            user_email=user.email,
        )
