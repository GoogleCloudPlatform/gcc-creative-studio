# Workspace Access & Membership Invariants

Source files:
- `backend/src/workspaces/schema/workspace_model.py`
- `backend/src/workspaces/workspace_auth_guard.py`
- `backend/src/workspaces/workspace_controller.py`
- `backend/src/workspaces/workspace_service.py`

## Roles & Visibility Scopes

- **`WorkspaceRoleEnum`:** `viewer`, `editor`, `admin`, `owner`.
- **`WorkspaceScopeEnum`:**
  - `public`: Visible across users (e.g., shared public workspace galleries).
  - `private`: Restricted to workspace members and global admins.

## Central Workspace Authorization (`WorkspaceAuth.authorize`)

- Looks up workspace scope first (`workspace_repo.get_scope(workspace_id)`):
  - Missing workspace raises `HTTP 404`.
  - Grants access immediately when `UserRoleEnum.ADMIN in user.roles` OR `scope == WorkspaceScopeEnum.PUBLIC`.
  - For `WorkspaceScopeEnum.PRIVATE`, verifies `await self.workspace_repo.is_member(workspace_id, user.id)` and raises `HTTP 403` if the user is not a member.

## Creation & Invitations

- **Authentication baseline:** All `/api/workspaces` routes require `get_current_user` at the router level.
- **Workspace creation (`POST /api/workspaces` -> `WorkspaceService.create_workspace`):** Sets `owner_id = user.id` and creates the initial `WorkspaceMember` record with `WorkspaceRoleEnum.OWNER`.
- **Member invitations (`POST /api/workspaces/{workspace_id}/invites` -> `WorkspaceService.invite_user_to_workspace`):**
  - Verifies workspace existence (`HTTP 404` if missing).
  - Requires either `UserRoleEnum.ADMIN in current_user.roles` or `current_user.id == workspace.owner_id` (`HTTP 403` otherwise).
  - Controller returns `HTTP 404` when the invited user email does not exist in `users`.
