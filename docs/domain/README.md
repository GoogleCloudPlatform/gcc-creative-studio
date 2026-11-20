# Creative Studio Domain Invariants

These modular guides document the baseline authorization, session, data-isolation, and test-harness invariants that future changes must preserve. Keep each guide public-safe (no internal links, bug trackers, or internal addresses).

## Domain Index

- [`auth.md`](auth.md) — Token verification paths (`X-User-Authorization`, `ya29.` OAuth, Firebase/OIDC), outage fail-closed behavior, post-auth hook scope, and frontend browser session renewal.
- [`admin.md`](admin.md) — `RoleChecker([UserRoleEnum.ADMIN])`, admin router and user-management protections, self-delete guard, soft-delete restore restrictions, and `AdminAuthGuard`.
- [`gallery.md`](gallery.md) — Unified gallery search scoping (`UnifiedGalleryItemResponse`), `bulk_delete` workspace and owner/admin checks, admin-only restore, and `FolderService.is_workspace_manager`.
- [`workspaces.md`](workspaces.md) — `WorkspaceScopeEnum` (`PUBLIC` vs `PRIVATE`), `WorkspaceRoleEnum`, `WorkspaceAuth.authorize`, creator `OWNER` assignment, and owner/admin invitation rules.

## Test Harness & Contract Invariants

- **Shared `NullPool` async engine (`backend/tests/conftest.py`, `backend/main.py`):** Tests share one `NullPool` SQLAlchemy async engine bound to `src.database.engine` and `src.database.async_session_local`, while `backend/main.py` clears lifespan hooks cleanly on shutdown. `backend/tests/e2e/conftest.py` reuses that same engine without recreating it.
- **Autouse global hook reset (`fixture_reset_global_hooks`):** Runs before and after every backend test to call `clear_post_auth_hooks()`, `set_dispatch_hook(None)`, and `reset_dispatch_tick_throttle()`.
- **Hermetic unit-test socket guard (`_block_external_network_in_unit_tests`):** Active on every non-`tests/e2e` backend test; wraps `socket.socket.connect` and `socket.socket.connect_ex` to permit Unix sockets and loopback (`127.0.0.1`, `::1`, `localhost`) while failing closed with `RuntimeError` on outbound network calls.
- **Shared PostgreSQL harness (`backend/tests/postgres_harness.py`):** Provides `recreate_throwaway_db`, `drop_throwaway_db`, `run_alembic_upgrade`, `run_alembic_downgrade`, and `make_nullpool_session_factory`. Setting `REQUIRE_POSTGRES_TESTS=1` turns unreachable PostgreSQL into a `RuntimeError` failure instead of a silent skip. In `backend/tests/alembic/test_workflow_runs_migration.py`, `pg_constraint` queries filter `contype <> 'n'` so PostgreSQL 18 cataloged `NOT NULL` rows do not break PG15 compatibility (`is_nullable` is asserted separately via `information_schema.columns`).
- **Typed ORM factories (`backend/tests/factories.py`):** Provide `make_user`, `make_workspace`, `make_workspace_member`, `make_folder`, `make_source_asset`, `make_media_item`, and `make_tag` with strict schema-matching attributes.
- **Strict request DTOs and endpoint contracts (`backend/tests/contracts/test_api_dto_contracts.py`):** Every mutation body DTO enforces `extra="forbid"` unless explicitly listed in `DYNAMIC_SCHEMA_ALLOWLIST`. Frontend JSON mutation routes must match registered backend routes (outside the three documented legacy methods in `LEGACY_UNWIRED_FRONTEND_MUTATIONS`).
