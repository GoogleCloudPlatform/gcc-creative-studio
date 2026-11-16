# Admin & Role-Based Access Invariants

Source files:
- `backend/src/auth/auth_guard.py`
- `backend/src/users/user_model.py`
- `backend/src/admin/admin_controller.py`
- `backend/src/users/user_controller.py`
- `backend/src/galleries/gallery_service.py`
- `frontend/src/app/admin/admin-auth.guard.ts`

## System Roles & Enforcement

- **Defined system roles (`UserRoleEnum`):** `user`, `creator`, `admin`, `workflows`.
- **`RoleChecker` (`backend/src/auth/auth_guard.py`):** Depends on `get_current_user` and verifies that at least one role in `user.roles` is in `allowed_roles`. Missing permissions raise `HTTP 403` (`You do not have sufficient permissions to perform this action.`).

## Protected Admin Surfaces

- **Admin router (`backend/src/admin/admin_controller.py`):** Every `/api/admin/**` endpoint inherits router-level `Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN]))`.
- **User management (`backend/src/users/user_controller.py`):**
  - `GET /api/users/me` requires only `get_current_user`.
  - Administrative user endpoints (listing, role updates, soft deletion, restoration) require `admin_only = Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN]))`.
  - **Self-delete guard (`DELETE /api/users/{user_id}`):** Even admins cannot delete themselves — `user_id == current_user.id` raises `HTTP 400` (`You cannot delete yourself.`).
- **Soft-deleted gallery item recovery (`GalleryService.restore_item`):** Restoring a soft-deleted `media_item` or `source_asset` requires `UserRoleEnum.ADMIN in current_user.roles` (`HTTP 403` otherwise).

## Frontend Route Guard

- **`AdminAuthGuard` (`frontend/src/app/admin/admin-auth.guard.ts`):**
  - Allows SSR shell rendering when `!isPlatformBrowser(this.platformId)`.
  - In the browser, delegates route activation to `canActivateWithSilentRenewal(...)`, allowing an expired local session a single silent renewal before evaluating `userEmail && this.authService.isUserAdmin()`. Otherwise shows an access-denied snackbar, triggers `this.authService.expireSession()` (keeping GIS silent auto-select intact), and denies activation (`return false`).
