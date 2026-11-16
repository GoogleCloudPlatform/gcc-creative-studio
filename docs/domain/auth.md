# Auth & Session Invariants

Source files:
- `backend/src/auth/auth_guard.py`
- `frontend/src/app/common/services/auth.service.ts`
- `frontend/src/app/auth.interceptor.ts`

## Token Verification & Outage Semantics

- **Header precedence & agent context (`get_current_user`):**
  - Checks `X-User-Authorization` first; when present, sets `is_agent_request.set(True)` and strips any `Bearer ` prefix. Otherwise resets `is_agent_request.set(False)` and reads the `Authorization: Bearer` token via `oauth2_scheme`.
  - Missing tokens immediately fail with `HTTP 401` (`Missing authentication token.`).
- **Token verification paths & outage semantics:**
  - **`ya29.` OAuth access tokens:** Verified synchronously (offloaded via `asyncio.to_thread`) against `https://oauth2.googleapis.com/tokeninfo`. Client rejection (`4xx` or missing `email`) raises `HTTP 401` (`Invalid Google access token.`), whereas upstream outages (`requests.RequestException`, `5xx`, or `429`) fail closed with `HTTP 503` (`Failed to contact Google authentication server.`) — authentication never falls back open and transient outages do not log users out.
  - **`ENVIRONMENT == "local"`:** Verifies via `firebase_admin.auth.verify_id_token`, falling back to `google.oauth2.id_token.verify_oauth2_token` (with `GOOGLE_TOKEN_AUDIENCE`). Preserves Firebase `ExpiredIdTokenError` / `CertificateFetchError` semantics over fallback errors.
  - **Non-local environments:** Verifies Google Identity Platform OIDC ID tokens directly via `google.oauth2.id_token.verify_oauth2_token` with `audience=config_service.GOOGLE_TOKEN_AUDIENCE`.
  - Expired/invalid ID tokens (`ExpiredIdTokenError`, `ValueError`, `GoogleAuthError`, `FirebaseError`) map to `HTTP 401` (`"Authentication token has expired."` vs `"Invalid authentication token."`), while Google cert/transport failures (`CertificateFetchError`, `TransportError`) map to `HTTP 503`. Log sanitization redacts JWT/base64 token segments while retaining diagnostic failure reasons.
- **Identity, allowlists, and JIT provisioning:**
  - Verified tokens lacking an `email` claim fail with `HTTP 403`.
  - If `ALLOWED_EMAILS` or `ALLOWED_ORGS` (`hd` claim) is configured and neither matches, `get_current_user` logs a `WARNING` and raises `HTTP 401`.
  - Valid first-time users are provisioned Just-In-Time via `user_service.create_user_if_not_exists(email=email, name=name, picture=picture)` (missing returned profile raises `HTTP 500`).
- **Post-auth hook boundaries:**
  - `_run_post_auth_hooks` runs **only** for direct user ID tokens — it is explicitly skipped when `X-User-Authorization` is set (`user_auth_header`) or when `token.startswith("ya29.")`.
  - Hook exceptions log warnings and do not fail authentication. Test hooks are cleared before and after each test via `clear_post_auth_hooks()`.

## Browser Session & Renewal

- **Client persistence (`AuthService`):**
  - Stores the session `{token, expiry}` JSON in `localStorage` under `FIREBASE_SESSION_KEY` (`"firebase_session"`) and the synced backend `UserModel` under `USER_DETAILS` (`"USER_DETAILS"`).
  - `loadSessionFromStorage()` discards expired entries on startup (`session.expiry <= Date.now()`).
  - `isLoggedIn()` returns `false` on the server (`!isPlatformBrowser`) and checks in-memory `firebaseIdToken && firebaseTokenExpiry > Date.now()` in the browser, navigating to `/login` when expired or missing.
- **Request interception & silent renewal (`AuthInterceptor`):**
  - Attaches `Authorization: Bearer <token>` only for relative `/` URLs and requests matching `environment.backendURL`.
  - Calls `AuthService.getValidIdentityPlatformToken$()` to reuse the cached token or silently refresh before dispatching the HTTP request.
  - Only non-`HttpErrorResponse` failures (silent token renewal failures) trigger `AuthService.logout()`, which clears `firebase_session`, `USER_DETAILS`, and `showTooltip` and navigates to `/login`. Backend `HttpErrorResponse` errors (`404`, `500`, etc.) are re-thrown without logging the user out.
