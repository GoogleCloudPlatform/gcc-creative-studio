# Auth & Session Invariants

Source files:
- `backend/src/auth/auth_guard.py`
- `frontend/src/app/common/services/auth.service.ts`
- `frontend/src/app/auth.interceptor.ts`

## Token Verification & Outage Semantics

- **Header precedence & agent context (`get_current_user`):**
  - Checks `X-User-Authorization` first; when present, sets `is_agent_request.set(True)` and strips any `Bearer ` prefix. Otherwise resets `is_agent_request.set(False)` and reads the `Authorization: Bearer` token via `oauth2_scheme`.
  - Missing tokens immediately fail with `HTTP 401` (`Missing authentication token.`).
- **Token verification paths:**
  - **`ya29.` OAuth access tokens:** Verified synchronously (offloaded via `asyncio.to_thread`) against `https://oauth2.googleapis.com/tokeninfo`. Non-`200` responses, missing `email`, or upstream network failures (`requests.RequestException`) fail closed with `HTTP 401` (`Failed to contact Google authentication server.` on network outages) — authentication never falls back open.
  - **`ENVIRONMENT == "local"`:** Verifies via `firebase_admin.auth.verify_id_token`, falling back to `google.oauth2.id_token.verify_oauth2_token` (with `GOOGLE_TOKEN_AUDIENCE`).
  - **Non-local environments:** Verifies Google Identity Platform OIDC ID tokens directly via `google.oauth2.id_token.verify_oauth2_token` with `audience=config_service.GOOGLE_TOKEN_AUDIENCE`.
  - Expired or invalid Firebase ID tokens (`auth.ExpiredIdTokenError`, `auth.InvalidIdTokenError`) raise `HTTP 401`.
- **Identity, allowlists, and JIT provisioning:**
  - Verified tokens lacking an `email` claim fail with `HTTP 403`.
  - If `ALLOWED_EMAILS` or `ALLOWED_ORGS` (`hd` claim) is configured and neither matches, `get_current_user` raises `HTTP 401`.
  - Valid first-time users are provisioned Just-In-Time via `user_service.create_user_if_not_exists(email=email, name=name, picture=picture)` (missing returned profile raises `HTTP 500`).
- **Post-auth hook boundaries:**
  - `_run_post_auth_hooks` runs **only** for direct user ID tokens — it is explicitly skipped when `X-User-Authorization` is set (`user_auth_header`) or when `token.startswith("ya29.")`.
  - Hook exceptions log warnings and do not fail authentication. Test hooks are cleared before and after each test via `clear_post_auth_hooks()`.

## Browser Session & Renewal

- **Client persistence & proactive renewal (`AuthSessionStore` / `GisClientAdapter`):**
  - Stores `{token, expiry}` in `localStorage['firebase_session']` and the synced `UserModel` in `USER_DETAILS`. Keeps an expired session at boot so reload or sleep recovery attempts silent GIS renewal (`auto_select`, 5-minute buffer + 0-30 s jitter, `RENEW_RETRY_MS = 60 s` cooldown, `focus`/`visibilitychange`/`online` wake triggers) before redirecting to `/login`.
  - Pure JWT clock-skew (`iat`), symmetric `sub`/`email` identity checks, `returnUrl` sanitization, `AuthRenewalError` (non-enumerable `rejectedToken`), and `markSessionHandled` live in `auth-token.utils.ts`; GIS SDK interfaces live in `gis.types.ts`.
  - `GisClientAdapter` enforces interactive `use_fedcm_for_button: true` fallback (`GisPromptSuppressedError`) and cancels stale prompts via `abortActivePrompt()`.
- **Cross-tab safety, single-flight renewal & sign-out paths (`AuthService`):**
  - Interactive sign-in validates the candidate token against `GET /users/me` (`Authorization: Bearer <token>`) **before** writing `firebase_session` or `USER_DETAILS`, so rejected logins (401/403) never disturb an active session in another tab.
  - Silent renewal is single-flight per tab (`shareReplay`) and cross-tab (`navigator.locks` + storage re-check), syncs `/users/me` asynchronously, and handles cross-tab `storage` account switches without serving stale tokens.
  - **Request retry & error handling (`AuthInterceptor` / `AgentChatService`):** Perform at most one `401` renew-and-retry (skipping org-unauthorized `401`s) and brand terminal renewal errors via `markSessionHandled` so duplicate error toasts never stack.
  - **Two sign-out paths:** Manual `logout()` disables GIS auto-select; automatic `onSessionRenewalFailed()` -> `expireSession()` preserves silent sign-in and deep-link `?returnUrl=...`. Neither clears server-side queued workflows.
