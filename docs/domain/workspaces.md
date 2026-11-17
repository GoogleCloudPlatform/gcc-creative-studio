# Workspace Access, Roles, and Collaboration Invariants

Source files:
- `backend/src/workspaces/schema/workspace_model.py`
- `backend/src/workspaces/workspace_auth_guard.py`
- `backend/src/workspaces/generation_workspace.py`
- `backend/src/workspaces/workspace_service.py`
- `backend/src/workspaces/repository/workspace_repository.py`
- `backend/src/galleries/gallery_service.py`
- `backend/src/folders/folder_service.py`
- `backend/src/tags/tags_controller.py`
- `backend/src/workbench/workbench_controller.py`
- `backend/src/workbench/workbench_service.py`
- `frontend/src/app/services/workspace/workspace-state.service.ts`

## Workspace Visibility & Scope (`PUBLIC`, `PRIVATE`, `PERSONAL`)

- **Personal Workspace ("My Workspace", `scope = 'personal'`):** Every user gets exactly one personal workspace, enforced in PostgreSQL by the partial unique index `uq_workspaces_personal_owner` and provisioned lazily via `WorkspaceRepository.ensure_personal_workspace`. Personal workspaces are strictly single-user: `WorkspaceAuth.authorize`, `WorkspaceAuth.authorize_write`, `is_workspace_manager`, and unscoped queries (`UnifiedGalleryRepository`, `SourceAssetRepository`, `TagsRepository`, `AdminRepository`) never expose another user's personal workspace, including to global `ADMIN` users. Cross-workspace moves (`bulk_move`) out of a personal workspace are rejected (`400`); items in a personal workspace remain isolated unless explicitly copied (`bulk_copy`). In the Angular client (`WorkspaceSwitcherComponent` + `WorkspaceStateService`), initial navigation defaults to `"My Workspace"` unless overridden by `?workspaceId=` or a per-tab, user-scoped `sessionStorage` selection (`cs_active_workspace_id:<userKey>`).
- **Org-Wide Shared Workspace (`scope = 'public'`):** Visible to all authenticated users. Regular users receive effective role `EDITOR`; global `ADMIN` users receive `ADMIN` and act as workspace managers. `WorkspaceService.invite_user_to_workspace` rejects invitations targeting `PUBLIC` or `PERSONAL` workspaces.
- **Team Shared Workspace (`scope = 'private'`):** Visible only to explicit members (`workspace_members`) and global `ADMIN` users. User workspace lists return `[personal, ...private, ...public]` with `current_user_role` populated via `resolve_effective_role`.

## Shared-Workspace Role Parity (`Owner / Admin / Editor / Viewer`)

`backend/src/workspaces/workspace_auth_guard.py` is the single source of truth for workspace authorization (`authorize`, `authorize_write`, `resolve_effective_role`, `is_workspace_manager`):

- **`OWNER` / `ADMIN` (plus global `ADMIN` on shared workspaces):** Full management rights (`is_workspace_manager == True`), including inviting/managing workspace members (except assigning `OWNER` via invitation), managing folders and subtrees regardless of item creator, managing workspace Brand Guidelines, deleting/moving any workspace gallery item or folder, and editing/deleting workspace tags.
- **`EDITOR`:** Read and write access (`authorize_write` passes), creator-scoped for folder updates/deletes/moves (`ensure_can_manage_folder`, `subtree_has_foreign_content`), tag updates/deletes, and gallery `bulk_delete` / `bulk_move`. Cannot invite members or mutate Brand Guidelines.
- **`VIEWER`:** Strictly read-only in `PRIVATE` workspaces. All write endpoints (`POST`/`PUT`/`PATCH`/`DELETE` across folders, tags, source assets, gallery mutations, image/VTO/video/audio generation and upload-upscale, and timeline create/update/delete/render) call `authorize_write` and reject `VIEWER`s with HTTP `403`. Frontend gallery, folder, tag, and lightbox controls mirror these permissions via `WorkspaceStateService.canEditWorkspace` and `WorkspaceStateService.canManageWorkspace`.

## Brand Guidelines (Shared Workspaces Only)

- Brand Guidelines belong strictly to shared (`PUBLIC` or `PRIVATE`) workspaces (`400` if targeting a `PERSONAL` workspace). Management (`generate_signed_upload_url`, create, update, delete) requires `is_workspace_manager`; reads require workspace membership (`authorize`).

## Shared Timelines & Private Clip Access

- **Reading a Shared Timeline (`GET /api/workbench/timelines/{id}`, `GET /api/workbench/timelines`):** Requires read access (`authorize`) on the timeline's workspace (`timeline.workspace_id`, failing closed with `403` when missing - never falling back to a fabricated workspace ID). Once authorized, `enrich_timeline` signs all clip URLs so any workspace member can open and inspect a shared timeline even when it contains clips originally created in another member's private workspace.
- **Saving or Rendering a Timeline (`POST /timelines`, `PUT /timelines/{id}`, `POST /render`):** Enforces both `authorize_write` on the target workspace and `ensure_can_reference_inputs` across every referenced `MediaItem` and non-`SYSTEM` `SourceAsset` (video clips, first/last frame references, and audio clips), plus `_ensure_storyboard_in_workspace` when a `storyboard_id` is supplied. A colleague who lacks direct read access to an author's private clip is rejected with HTTP `403` before any database write or background render job is queued.

## Schema Rollback (`c8f3a1b2d4e5`)

- Downgrading revision `c8f3a1b2d4e5` drops the personal-workspace unique index (`uq_workspaces_personal_owner`) after cleaning up `scope = 'personal'` rows: empty `personal` workspaces (with no `media_items`, `source_assets`, `folders`, `tags`, `brand_guidelines`, `storyboards`, or `timelines`) are deleted, while non-empty `personal` workspaces are converted to `scope = 'private'` with `owner` membership preserved in `workspace_members` so pre-feature versions boot cleanly without data loss. Because downgraded rows have `scope = 'private'`, they become visible to global `ADMIN` users on pre-feature code, and re-upgrading `c8f3a1b2d4e5` lazily provisions a fresh `'My Workspace'` personal workspace per user rather than auto-converting downgraded `private` workspaces back to `personal`.
