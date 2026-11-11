# Gallery & Folder Invariants

Source files:
- `backend/src/galleries/gallery_controller.py`
- `backend/src/galleries/gallery_service.py`
- `backend/src/folders/folder_service.py`

## Unified Search Scoping

- **`POST /api/gallery/search` (`search_gallery_items`):** Returns `PaginationResponseDto[UnifiedGalleryItemResponse]`.
- **Non-admin scoping:** `search_dto.workspace_id` is mandatory (`HTTP 400` if omitted) and always verified through `WorkspaceAuth.authorize(workspace_id=search_dto.workspace_id, user=current_user)`.
- **Admin scoping:** System admins (`UserRoleEnum.ADMIN`) may query without `workspace_id` (excluding other users' `PERSONAL` workspaces in `UnifiedGalleryRepository`), or pass a `workspace_id` (validated via `WorkspaceAuth.authorize`, which rejects cross-user access to `PERSONAL` workspaces even for global `ADMIN` users).

## Bulk Delete & Recovery

- **`GalleryService.bulk_delete`:**
  1. Authorizes write access on the requested `bulk_delete_dto.workspace_id` via `self.workspace_auth.authorize_write(...)` first (rejecting `VIEWER`s with HTTP `403`).
  2. For each `media_item` or `source_asset`, verifies **both**:
     - **Workspace boundary:** `item.workspace_id == bulk_delete_dto.workspace_id` (refuses cross-workspace IDs even when passed in the payload).
     - **Item permission:** `is_workspace_manager(current_user, workspace)` or `item.user_id == current_user.id`.
  3. Unauthorized or cross-workspace entries are skipped without mutating the database; only authorized deletions increment `deleted_count`.
- **`GalleryService.restore_item` (`POST /api/gallery/items/{item_id}/restore`):**
  - Restricted to `UserRoleEnum.ADMIN` (`HTTP 403` otherwise) and authorizes `workspace_auth.authorize_write(...)` on `item.workspace_id` (blocking global admins from foreign `PERSONAL` workspaces).
  - Validates `item_type` (`"media_item"` or `"source_asset"`, `HTTP 400` otherwise) and raises `HTTP 404` if restoration returns `false`.

## Folder Management Policy

- **`FolderService.is_workspace_manager(user, workspace)` (backed by `workspace_auth_guard.is_workspace_manager`):**
  - On `WorkspaceScopeEnum.PERSONAL` workspaces, only the owner (`workspace.owner_id == user.id`) holds management rights; global `UserRoleEnum.ADMIN` users are excluded.
  - On `WorkspaceScopeEnum.PRIVATE` workspaces, global `UserRoleEnum.ADMIN` users, the workspace owner (`workspace.owner_id == user.id`), and `WorkspaceRoleEnum.OWNER` / `ADMIN` members manage all folders.
  - On `WorkspaceScopeEnum.PUBLIC` workspaces, only global `UserRoleEnum.ADMIN` users hold blanket folder management rights.

## Query Pushdown, Presigned URL Caching & Background Auth Hooks

- **Two-stage paginated search (`UnifiedGalleryRepository.query`):**
  - Stage 1 counts matching IDs directly across `media_items` and `source_assets` base tables without constructing JSONB view rows.
  - Stage 2 pushes per-branch `.order_by(...).limit(offset + limit)` down when both tables are queried, then filters `unified_gallery_view` by constant `item_type` and `ANY(ARRAY[...])` PK predicates so PostgreSQL uses `c8f4a2e91d05` partial covering indexes (`deleted_at IS NULL`).
- **IAM presigned URL caching & lifecycle (`IamSignerCredentials`):**
  - Defaults `DEFAULT_PRESIGNED_EXPIRATION_HOURS` to `6` hours with a 15-minute refresh buffer, an LRU cache bounded at `_MAX_URL_CACHE_SIZE = 10_000`, async singleflight deduplication on `_inflight_futures`, and a lazy 32-worker signing executor shut down cleanly by `shutdown_signing_executor()` during FastAPI teardown.
- **Large source-asset thumbnail guard (`SourceAssetService.finalize_direct_upload`):**
  - Enforces `MAX_INLINE_THUMBNAIL_BYTES` (50 MiB) by checking GCS object metadata (reloading if `blob.size is None`) before synchronous thumbnail generation; oversized assets log a warning and skip thumbnail creation instead of buffering large blobs in memory.
- **Non-blocking post-auth workflow session sync (`schedule_post_auth_session`):**
  - Offloads workflow token persistence and throttled dispatcher ticks onto a tracked background `asyncio.Task` with per-user singleflight dedup and queued token rotation, and drains cleanly via `drain_post_auth_tasks()` during shutdown.

## Single-Item Audio Analysis Read

- **`GET /api/gallery/item/{item_id}/audio-analysis` (`GalleryService.get_media_audio_analysis`):**
  - Verifies workspace access through `_get_authorized_media_item(item_id, current_user)` (`WorkspaceAuth.authorize` on `item.workspace_id`; raises `HTTP 404` when missing) and returns `normalize_audio_analysis(item.audio_analysis)` without generating presigned GCS URLs.
