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
- `backend/src/workflows/workflow_service.py`
- `frontend/src/app/services/workspace/workspace-state.service.ts`

## Workspace Visibility & Scope (`PUBLIC`, `PRIVATE`, `PERSONAL`)

- **Personal Workspace ("My Workspace", `scope = 'personal'`):** Every user gets exactly one personal workspace, enforced in PostgreSQL by the partial unique index `uq_workspaces_personal_owner` and provisioned lazily via `WorkspaceRepository.ensure_personal_workspace`. Personal workspaces are strictly single-user: `WorkspaceAuth.authorize`, `WorkspaceAuth.authorize_write`, `is_workspace_manager`, and unscoped queries (`UnifiedGalleryRepository`, `SourceAssetRepository`, `TagsRepository`, `AdminRepository`) never expose another user's personal workspace, including to global `ADMIN` users. Cross-workspace moves (`bulk_move`) out of a personal workspace are rejected (`400`); items in a personal workspace remain isolated unless explicitly copied (`bulk_copy`). In the Angular client (`WorkspaceSwitcherComponent` + `WorkspaceStateService`), initial navigation defaults to `"My Workspace"` unless overridden by `?workspaceId=` or a per-tab, user-scoped `sessionStorage` selection (`cs_active_workspace_id:<userKey>`).
- **Org-Wide Shared Workspace (`scope = 'public'`):** Visible to all authenticated users. Regular users receive effective role `EDITOR`; global `ADMIN` users receive `ADMIN` and act as workspace managers. `WorkspaceService.invite_user_to_workspace` rejects invitations targeting `PUBLIC` or `PERSONAL` workspaces.
- **Team Shared Workspace (`scope = 'private'`):** Visible only to explicit members (`workspace_members`) and global `ADMIN` users. User workspace lists return `[personal, ...private, ...public]` with `current_user_role` populated via `resolve_effective_role`.

## Shared-Workspace Role Parity (`Owner / Admin / Editor / Viewer`)

`backend/src/workspaces/workspace_auth_guard.py` is the single source of truth for workspace authorization (`authorize`, `authorize_write`, `resolve_effective_role`, `is_workspace_manager`):

- **`OWNER` / `ADMIN` (plus global `ADMIN` on shared workspaces):** Full management rights (`is_workspace_manager == True`), including inviting/managing workspace members (except assigning `OWNER` via invitation), managing folders and subtrees regardless of item creator, managing workspace Brand Guidelines, deleting/moving any workspace gallery item or folder, and editing/deleting workspace tags.
- **`EDITOR`:** Read and write access (`authorize_write` passes), creator-scoped for folder updates/deletes/moves (`ensure_can_manage_folder`, `subtree_has_foreign_content`), tag updates/deletes, and gallery `bulk_delete` / `bulk_move`. Cannot invite members or mutate Brand Guidelines.
- **`VIEWER`:** Strictly read-only in `PRIVATE` workspaces. All shared-workspace write endpoints (`POST`/`PUT`/`PATCH`/`DELETE` across folders, tags, source assets, gallery mutations, projects, storyboards, agent chats, and timeline create/update/delete) call `authorize_write` (directly or via `ProjectAuth`/`TimelineAuth(..., write=True)`) and reject `VIEWER`s with HTTP `403`, while generation and timeline-render routes call read-context `authorize` and write outputs privately into the caller's personal workspace. Frontend gallery, folder, tag, and lightbox controls mirror these permissions via `WorkspaceStateService.canEditWorkspace` and `WorkspaceStateService.canManageWorkspace`.

## Brand Guidelines (Shared Workspaces Only)

- Brand Guidelines belong strictly to shared (`PUBLIC` or `PRIVATE`) workspaces (`400` if targeting a `PERSONAL` workspace). Management (`generate_signed_upload_url`, create, update, delete) requires `is_workspace_manager`; reads require workspace membership (`authorize`).

## Workbench Projects, Timelines & Private Clip Access

- **Owner-Only Projects & Timelines (`ProjectAuth`, `TimelineAuth`):** Projects, storyboards, agent chats, and timelines are strictly owner-scoped (with legacy unattributed timelines admin-only) and require active access to the owning project's workspace (`WorkspaceAuth.authorize` for reads and timeline renders; `WorkspaceAuth.authorize_write` for writes via `write=True`).
- **Saving or Rendering a Timeline (`POST /timelines`, `PUT /timelines/{id}`, `POST /render`):** Enforces `ProjectAuth`/`TimelineAuth(..., write=True)` on timeline creates/updates (or read-context `TimelineAuth.authorize` on render, which routes outputs privately via `resolve_generation_context`) and `ensure_can_reference_inputs` across every referenced `MediaItem` and non-`SYSTEM` `SourceAsset` (video clips, first/last frame references, and audio clips), plus `_ensure_storyboard_in_workspace` when a `storyboard_id` is supplied. A caller who lacks direct read access to another user's private clip is rejected with HTTP `403` before any database write or background render job is queued.

## Schema Rollback (`c8f3a1b2d4e5`)

- Downgrading revision `c8f3a1b2d4e5` drops the personal-workspace unique index (`uq_workspaces_personal_owner`) after cleaning up `scope = 'personal'` rows: empty `personal` workspaces (with no `media_items`, `source_assets`, `folders`, `tags`, `brand_guidelines`, `storyboards`, `timelines`, `projects`, or `agent_sessions` when present) are deleted, while non-empty `personal` workspaces are converted to `scope = 'private'` with `owner` membership preserved in `workspace_members` so pre-feature versions boot cleanly without data loss. Because downgraded rows have `scope = 'private'`, they become visible to global `ADMIN` users on pre-feature code, and re-upgrading `c8f3a1b2d4e5` lazily provisions a fresh `'My Workspace'` personal workspace per user rather than auto-converting downgraded `private` workspaces back to `personal`.

## Private-First Generation, Upload, and Loop Routing

- **Private-First Output Routing (`resolve_generation_context`):** Generation and render endpoints (`ImagenService`, `VeoService`, `AudioService`, `WorkbenchService.render_timeline_by_id`, and upload-upscale) authorize read access on `requested_workspace_id` and any distinct `context_workspace_id`, lazily provision the caller's personal workspace via `WorkspaceRepository.ensure_personal_workspace` whenever a shared workspace is targeted, route `output_workspace_id = personal_ws.id` while preserving `brand_workspace_id = context_workspace_id or requested_workspace_id`, and ignore shared `folder_id` values for personal outputs after verifying folder read access. `WorkflowService.batch_execute_workflow` likewise routes batch CSV `gs://` `SourceAsset` ingestion via `resolve_generation_context(..., resolve_folder=False)` while preserving the caller's `workspace_id` on the submitted workflow run. In background video jobs, `VeoService._process_video_in_background` re-verifies referenced inputs in the worker against both `output_workspace_id` and `context_workspace_id`.
- **Cross-Workspace Input Authorization (`ensure_can_reference_inputs`) & DTO Strictness:** Imagen, Veo, VTO, Video Concatenation, and Upload-Upscale validate every referenced `MediaItem` and non-`SYSTEM` `SourceAsset` against the caller's readable workspaces (`authorize` or `PUBLIC` read), allowing users to browse shared workspace assets and generate derivatives privately. Only `CreateImagenDto`, `CreateVeoDto`, and `VtoDto` accept optional `context_workspace_id` (`contextWorkspaceId` for shared brand-guideline lookup and worker input verification); `CreateAudioDto`, `ConcatenateVideosDto`, and `RenderTimelineRequest` enforce `extra="forbid"` without `context_workspace_id`, so frontend callers (`AudioComponent`, `VideoComponent` concatenation, and `WorkbenchComponent` render) must omit it.
- **Workflow Loop Item Authorization (`WorkflowsExecutorService._resolve_linked_items`):** When resolving gallery inputs for workflow loops, `UnifiedGalleryRepository.lookup_linked_loop_item_workspaces` maps each referenced `MediaItem` or `SourceAsset` ID to its owning workspace and `WorkspaceAuth.authorize` confirms caller read access before exposing items to workflow execution.
- **Frontend Upload, Cropper, Picker, and Workbench Routing:** `WorkspaceStateService.getTargetWorkspaceParam()` returns `{workspaceId: personal ?? active}` for payloads without `contextWorkspaceId` (`AudioComponent`, `UpscaleComponent`), while `WorkspaceStateService.getReferencedGenerationWorkspaceParams()` returns `{workspaceId: personal ?? active, contextWorkspaceId}` for Imagen, Veo, and VTO. Direct drops, cropper saves, and `ImageSelectorComponent` uploads route to the personal workspace, whereas `MediaGalleryComponent` direct and Drive uploads target `effectiveWorkspaceId` (the currently browsed workspace and `currentFolderId`, guarded by `authorize_write` in the backend). `WorkbenchComponent` saves preserve `loadedTimelineWorkspaceId`, then match `projectState.activeProjectWorkspaceId()` when an active project is selected (so `project_id` and `workspace_id` stay aligned), then fall back to storyboard / personal / active workspace, failing closed if no workspace is available.
