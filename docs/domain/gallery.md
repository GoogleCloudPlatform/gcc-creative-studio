# Gallery & Folder Invariants

Source files:
- `backend/src/galleries/gallery_controller.py`
- `backend/src/galleries/gallery_service.py`
- `backend/src/folders/folder_service.py`

## Unified Search Scoping

- **`POST /api/gallery/search` (`search_gallery_items`):** Returns `PaginationResponseDto[UnifiedGalleryItemResponse]`.
- **Non-admin scoping:** `search_dto.workspace_id` is mandatory (`HTTP 400` if omitted) and always verified through `WorkspaceAuth.authorize(workspace_id=search_dto.workspace_id, user=current_user)`.
- **Admin scoping:** System admins (`UserRoleEnum.ADMIN`) may query without `workspace_id`, or pass a `workspace_id` (which is still validated via `WorkspaceAuth.authorize`).

## Bulk Delete & Recovery

- **`GalleryService.bulk_delete`:**
  1. Authorizes the requested `bulk_delete_dto.workspace_id` via `self.workspace_auth.authorize(...)` first.
  2. For each `media_item` or `source_asset`, verifies **both**:
     - **Workspace boundary:** `item.workspace_id == bulk_delete_dto.workspace_id` (refuses cross-workspace IDs even when passed in the payload).
     - **Item permission:** `UserRoleEnum.ADMIN in current_user.roles` or `item.user_id == current_user.id`.
  3. Unauthorized or cross-workspace entries are skipped without mutating the database; only authorized deletions increment `deleted_count`.
- **`GalleryService.restore_item` (`POST /api/gallery/items/{item_id}/restore`):**
  - Restricted to `UserRoleEnum.ADMIN` (`HTTP 403` otherwise).
  - Validates `item_type` (`"media_item"` or `"source_asset"`, `HTTP 400` otherwise) and raises `HTTP 404` if restoration returns `false`.

## Folder Management Policy

- **`FolderService.is_workspace_manager(user, workspace)`:**
  - Global `UserRoleEnum.ADMIN` users can manage any folder across all workspaces.
  - On `WorkspaceScopeEnum.PRIVATE` workspaces, the workspace owner (`workspace.owner_id == user.id`) manages all folders in that workspace.
  - On `WorkspaceScopeEnum.PUBLIC` workspaces, only global admins hold blanket folder management rights.
