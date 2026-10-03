# 🤖 GEMINI.md - AI Agent & Developer Guide

This document serves as a comprehensive guide for AI Agents and developers working on the **Google Cloud Creative Studio Platform** project. It outlines the architecture, setup, development workflow, and strict guidelines to ensure code quality and consistency.

---

## 🏗️ System Architecture

Creative Studio follows a **Modular, Feature-Driven Architecture** (inspired by Hexagonal Architecture).

- **Structure:** Code is organized by feature domain (e.g., `/images`, `/users`) rather than technical layer.
- **Cohesion:** All code for a single feature is co-located (controllers, services, DTOs).
- **Coupling:** Modules interact through well-defined interfaces.

---

## 🚀 Bootstrapping (Docker Compose)

The standard development environment uses **Docker Compose**.

### 1. Prerequisites

- **gcloud CLI**: Authenticated and project set.
- **Docker & Docker Compose**
- **uv**: Fast Python package installer.

### 2. Environment Configuration

- **Backend (`backend/.env`)**:
  - Set `ENVIRONMENT="local"`
  - Set `USE_CLOUD_SQL_AUTH_PROXY=false` (uses local Postgres container).
  - Set `isLocal = True` (critical for local auth).
- **Frontend (`frontend/src/environments/environment.development.ts`)**:
  - Set `isLocal: true`
  - Configure Firebase credentials.

### 3. Starting the Application

From the root directory:

```bash
# Authenticate gcloud
gcloud auth application-default login

# Start containers
docker compose up --build
```

### 4. Seeding Initial Data

If the database is fresh, run the bootstrap script to seed templates:

```bash
docker exec -t creative-studio-backend sh -c "PYTHONPATH=/app uv run python -m bootstrap.bootstrap"
```

### 5. Local Izumi Agent (optional, for the Workbench chat)

With `ENVIRONMENT=local`, `AgentService` talks to a **local Izumi container** at `IZUMI_AGENT_URL` (default `http://izumi-agent:8080`) instead of Vertex AI Agent Engine. Set `USE_LOCAL_IZUMI_AGENT=false` in `backend/.env` to force the Agent Engine path locally (requires `AGENT_ENGINE_RESOURCE_NAME`).

```bash
# One-time: clone upstream Izumi next to this repo (already gitignored)
git clone --depth 1 -b v0.2.1 https://github.com/GoogleCloudPlatform/genmedia-izumi-agent.git genmedia-izumi-agent

# Upstream has no compose file for ads_x: copy the tracked reference files from docs/local-izumi/
cp docs/local-izumi/docker-compose.yml docs/local-izumi/.env.example genmedia-izumi-agent/demos/backend/ads_x/

# Start the ads_x agent + Firestore emulator (Creative Studio must already be up:
# the compose joins the `gcc-creative-studio_default` network)
cd genmedia-izumi-agent/demos/backend/ads_x
cp .env.example .env      # set GOOGLE_CLOUD_PROJECT / ASSET_SERVICE_GCS_BUCKET
docker compose up --build # first build is slow (node + python stages)
```

- The agent is reachable from the host at `http://localhost:8082` (ADK dev UI at `/dev-ui`).
- `demos/backend` and `mediagent_kit` are bind-mounted with `--reload`; the venv lives in the `izumi_backend_venv` volume.
- `docs/local-izumi/` is the source of truth for the compose file and `.env.example` (the Izumi clone is gitignored, so edits there are not tracked). `DEVELOPMENT.md` also documents a plain `docker build` / `docker run` fallback for hosts without Docker Compose.
- The adapter lives in `backend/src/agents/local_adk_client.py` (ADK REST API: `/apps/{app}/users/{user}/sessions`, `PATCH` state delta, `/run_sse`); sessions require the `user_id`, so `AgentService` routes every session call through its `_sessions_*` helpers.

---

## 🛠️ Development Workflow

### Backend (Python)

- **Hot Reload**: Enabled by default in Docker.
- **Package Management**: Uses `uv` and `pyproject.toml`.
- **Running Scripts**: **ALWAYS** use `docker compose` to run Python scripts (e.g., `docker exec ...`).

### Frontend (Angular)

- **Reactivity**: Strictly use **Angular Signals** for state management and computed values.
- **API Calls**: Implement API calls in a **Service**. **DO NOT** use `fetch` or `HttpClient` directly inside components.

---

## 🛡️ Code Quality & Linters (Pre-commit)

We use a **fully containerized `pre-commit` pipeline**. **DO NOT** run linters locally on your host machine.

### 1. Setup Git Hook

Run once from the root:

```bash
cp pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

### 2. Manual Run

To format and lint the **entire repository** at once:

```bash
docker compose run --rm pre-commit run --all-files
```

### 3. Linters Used

- **Backend**: `black` (formatting), `pylint` (linting).
- **Frontend**: `gts` (ESLint + Prettier).
- **License**: `addlicense` (adds headers).

---

## 🧪 Running Tests

### Backend (Python)

We use `pytest` and `pytest-cov`.

> [!IMPORTANT]
> **PR Requirement**: You must achieve at least **80% code coverage** across all `src/` files.

**Verify Coverage Locally**:

```bash
cd backend
uv run pytest tests -v --asyncio-mode=auto --cov=src --cov-fail-under=80
```

**Run Specific Tests**:

```bash
uv run pytest tests/users -v --asyncio-mode=auto
```

---

## 📜 AI Agent Guidelines & Rules

To maintain a pristine codebase, AI Agents **MUST** follow these rules:

1.  **Docker Enforcement**: Always use `docker compose` or `docker exec` to run Python scripts or commands that interact with the app environment. Always check if the docker containers are running correctly and in case of finding any errors solve them until the container starts successfully.
2.  **Precise Edits**: When editing files, ensure you replace **only** the target content. **DO NOT** append garbage lines or duplicate code.
3.  **Reactivity First**: In Angular, leverage Signals for computed state to avoid reactivity bugs.
4.  **Error Handling**: Always wrap async/stream operations in `try/catch` and log errors appropriately.
5.  **Format Before Commit**: Always ensure the code is formatted by using the prechecks leveraging automation for code quality before finishing execution.
6.  **Commiting Changes**: Never commit changes, just leave the changes in the files for the user to review and commit.
7.  **Testing**: Always run the tests and verify the coverage is above 80% before finishing execution, if it fails or coverage is below 80%, fix it, add the missing tests and run the tests again until it passes and coverage is above 80%.
8.  **Linting**: Always run the linter and verify the code is clean before finishing execution, if it fails, fix it and run the pre-commit hook again.
9.  **Documentation**: Always update the documentation when making changes to the code, even this file if needed.
10. **Seniority**: Act as a Senior Software Engineer with 10+ years of experience in software development.
11. **Code Review**: Always review the code before finishing execution, if it fails, fix it and run the pre-commit hook again.
12. **Security**: Always review the code for security vulnerabilities and fix them if found.
13. **Isolation**: Always work in isolation, do not modify files outside the scope of the task. Work with docker containers, do not run any gcloud commands locally nor modify any cloud resources.

---

## 🧠 Learnings & Hard Rules (READ THIS FIRST)

> [!CAUTION]
> This section exists because previous agents repeatedly broke working code. These are not suggestions. Violating any of them wastes the user's time and forces a full rollback of your work.

### ❌ What has gone WRONG before (do not repeat)

| Mistake | What actually happened | Rule |
| --- | --- | --- |
| **Scope creep** | Asked to change *only* migration steps, the agent also rewrote `configure_environment`, the `.tfvars` generation, and the profile editor — silently deleting the user's `db_tier` / `db_availability_type` work. | Change **only** the functions named in the request. Nothing else. Ever. |
| **Rolling back user edits** | The user edits files *concurrently*. Large rewrites clobbered their in-flight changes, and rejecting the agent diff reverted their work too. | Prefer **small, additive** edits over rewrites. Never replace a whole function when a 3-line change works. |
| **Assuming file state** | The agent edited based on what it *remembered* writing, not what was actually on disk after the user rejected/reverted. | **Always re-read the file** (`view_file` / `git diff`) at the start of a turn. Never trust memory of prior edits. |
| **Running `gcloud`** | Context Aware Access blocks `gcloud` for the agent; the commands failed and wasted turns. | **NEVER run `gcloud` commands.** Write them into the script and let the user execute. |
| **Committing** | The agent committed and pushed without permission. | **NEVER run `git commit` or `git push`.** Leave changes in the working tree. |
| **Hardcoding `us-central1`** | Broke a client in `europe-west1` whose org policy (`constraints/gcp.resourceLocations`) blocked US resources; Terraform tried to destroy and recreate EU resources. | Always use `$DEPLOY_REGION` / `var.region`. Never hardcode a region. |

### ✅ Required workflow for edits to `bootstrap.sh`

1. `git status` + `git diff` first — confirm the real baseline before editing.
2. Read the exact target function with `view_file`.
3. Make the **smallest possible** edit. Prefer inserting a new function over modifying an existing one.
4. Verify scope immediately:
   ```bash
   bash -n bootstrap.sh                          # syntax must pass
   git diff -U0 bootstrap.sh | grep -E "^@@"     # confirm hunks land ONLY in intended functions
   ```
5. If a hunk appears in a function you were not asked to touch, **revert it**.

### 📌 Domain knowledge worth keeping

- **The Cloud Run deadlock.** When Terraform changes VPC settings on an *existing* Cloud Run service, the live container can no longer reach the DB, crash-loops, and hangs `terraform apply` indefinitely. Deploying `us-docker.pkg.dev/cloudrun/container/hello` beforehand severs that dependency and breaks the deadlock. A *brand-new* service does not deadlock, since it is created with the dummy image anyway.
- **Why the dummy image survives `terraform apply`.** `modules/compute/main.tf` sets `lifecycle { ignore_changes = [template[0].containers[0].image, ...] }`. Terraform therefore never reverts the dummy image mid-apply; it stays until Cloud Build redeploys the real code. Removing that `ignore_changes` would silently break the entire migration flow.
- **Never force a Cloud Run restart with an env var.** `ignore_changes` covers the *image only*, not `env`. Setting something like `RESTART_TRIGGER=$(date +%s)` via `gcloud run services update` becomes permanent Terraform drift: every later plan reports `1 to change` and churns a needless revision. To force a fresh revision safely, read the service's current image with `--format="value(image)"` and re-deploy that same image — image changes are ignored by Terraform, so there is no drift.
- **Secrets written after a revision starts are invisible to it.** Cloud Run resolves `latest` only at revision start. Step 14 (`seed_database`) waits for the backend build, so that revision is live *before* Step 15 writes `agent_engine_resource_name`; it keeps Terraform's `placeholder_value_waiting_for_bootstrap_sh` and the backend calls `.../locations/<region>/placeholder_value_waiting_for_bootstrap_sh/sessions` → 404. `deploy_izumi_agent()` must therefore ALWAYS refresh the backend (same image) after writing the secret — waiting for any in-flight `BE_BUILD_ID` first — never skip it because "a build ran".
- **`write_state` does NOT set the shell variable.** It only appends to the profile file. So `write_state "TF_BUCKET_NAME" "$X"` leaves `$TF_BUCKET_NAME` empty for the rest of the run unless it was sourced by `read_state` on a previous run. This caused a silent bug: the migration bucket fell back to `${GCP_PROJECT_ID}-terraform-state`, which never matches the real convention `${GCP_PROJECT_ID}-cstudio-${ENV_NAME}-tfstate`, so `gcloud storage ls` queried a non-existent bucket, `2>/dev/null` swallowed the error, and Step 9 skipped the migration prompt while printing nothing. Always resolve it via `resolve_migration_bucket()`.
- **Never let a detection step print nothing.** Every branch of a step must emit at least one line, otherwise a silent failure is indistinguishable from a correct skip.
- **Backend service names are not fixed.** Legacy deployments use `cstudio-be`; current ones use `cs-[ENV_NAME]-backend`. Always check both with `gcloud run services describe` before acting — never assume which exists.
- **Legacy V1 DB instances ALWAYS have a random suffix.** V1 Terraform named them `creative-studio-db-${random_id.db_name_suffix.hex}` (e.g. `creative-studio-db-6eb3034d`), so an exact `^creative-studio-db$` match can never fire — it silently skipped every V1 backup. Match `^creative-studio-db(-[0-9a-f]+)?$`. V2 instances are `cs-<env>-db-<hex>`. The logical database inside V1 is `creative_studio` (V1's `db_name` default), matching the export. When both V1 and V2 exist, always prefer V1 as the backup source: `gcloud sql instances list` has no guaranteed order, and the V2 DB may be freshly created and empty.
- **Imports need an empty schema.** Terraform may update a Cloud SQL instance in place, leaving tables behind. `gcloud sql import` then fails with `relation "..." already exists`. Always drop + recreate `creative_studio` right before importing.
- **A failed apply can leave the migration source un-exportable.** Terraform destroys the V1 `google_sql_database` and `google_sql_user` in parallel; the user delete can fail (`role "studio_user" cannot be dropped because some objects depend on it`) *after* the database is already gone. The instance survives, so Step 8 re-detects it, and every re-export fails with `database "creative_studio" does not exist`. The backup from the first run is intact in the TF state bucket; `--use-existing-backup` (or the fallback prompt on export failure) reuses it. Never let a failed export overwrite or discard that file.
- **Migration artifacts live in the Terraform state bucket only.** `migration_backup.sql.gz` goes in `$TF_BUCKET_NAME` — that bucket owns infrastructure artifacts. Do not scan or write to the asset bucket for migrations.
- **PITR makes constant backup prompts redundant.** New Private IP instances have Point-in-Time Recovery. The default "happy path" must stay **completely silent** — no prompts, no backups. Only prompt when there is a real legacy signal (V1 DB, orphaned backup) or an explicit `--migrate-db`.
- **Izumi is deployed exactly as upstream ships it.** `bootstrap.sh` does not patch Izumi's Vertex endpoint, model IDs or `mediagent_kit` defaults; the agent runs on the `global` endpoint with upstream's models. The only location we set is where the Agent Engine resource itself lives (`--location=$DEPLOY_REGION`, required for reasoning engines). Do not reintroduce region/model pinning `sed`s.
- **Never write `$(grep -c … || echo 0)`.** `grep -c` prints `0` **and** exits 1 when there are no matches, so the substitution yields `"0\n0"` and `[ … -gt 0 ]` dies with `integer expression expected`. Use `grep -o … | wc -l | tr -d ' '`.
- **Lyria 3 `content_blocked` is a wording refusal, and the Izumi CS adapter does not retry it.** Vertex's Interactions API answers `400 {'code': 'content_blocked'}` for prompts its policy filter dislikes (an Ads-X brief with "engine roaring to life … separate voiceover" was refused). Upstream Izumi's direct-Vertex path raises `ContentBlockedError` so `generate_background_music` can reword and retry, but the Creative Studio path (`cs_media_generation_service.generate_music`) returns a `GeneratedAsset(status="failed", gcs_uri="")` without raising — so the agent binds the failed media item to the storyboard, the timeline carries an audio clip with `presigned_url: null`, and the final cut is silent. Our fix lives in `backend/src/audios/audio_service.py`: on `content_blocked` the worker retries **once, still on Lyria 3**, with `_simplify_lyria3_prompt()` (style head + neutral instrumental suffix), persists the reworded brief as `prompt` (keeping `original_prompt`), and otherwise fails with `LYRIA_3_CONTENT_BLOCKED_MESSAGE`. Do **not** add a `lyria-002` fallback — the user explicitly chose Lyria 3 only. The upstream adapter fix (raise on `failed`) is pending as a PR to `genmedia-izumi-agent`.
- **`timeline_id` is NOT evidence that a final video exists.** The Ads-X agent creates the workbench timeline the moment it persists the storyboard, long before `stitch_final_video`. The storyboard panel's "See Video" CTA therefore follows `AgentChatService.finalVideoReady`, which `chat-interface` derives only from the agent's `final_video_asset_id` / `final_video_asset_ref` state keys (session load + streamed deltas; the `regenerate_*` tools null them out) or a successful `stitch_final_video` tool response. `refreshStoryboardForSession()` runs on every stream close and must only emit `videoGenerated$` when told `videoReady`. Never re-add `if (sb.timeline_id) showSeeVideoBtn.set(true)`.
- **The Izumi agent ignores `mediaIndex` on attached images.** It resolves a media item by id and always takes its first image, so the Workbench chat opens the picker with `firstIndexOnly: true` (`ImageSelectorComponent` → `MediaGalleryComponent` → `GalleryCardComponent` hides the per-item carousel and pins `selectedIndex` to 0) and normalises any selection to index 0. Keep this until the agent honours `mediaIndex` (pinned for the upstream PR together with the `docker-compose.yml`); other pickers (Home, Video, Upscale, Workflows) still allow every index.
- **Backend Cloud Run runs at 8Gi / 2 vCPU** (`infrastructure/app.tf`): ffmpeg stitching plus concurrent Lyria/Veo workers OOM'd at 2Gi, and Cloud Run rejects 8Gi with fewer than 2 vCPU. The compute module's `cpu`/`memory` variables keep their small defaults; the sizing is set explicitly at the call site.
- **Agent-generated media lands in `Izumi Agent/<user email>/` in the gallery.** The agent's generation payloads carry no `folder_id` or session id — only the `X-User-Authorization` header, which `auth_guard` turns into the `is_agent_request` ContextVar. `backend/src/folders/agent_output_folder.py::resolve_agent_output_folder_id(db, workspace_id, user)` returns `None` for regular users and otherwise gets-or-creates two levels: the shared root `Izumi Agent` (**owned by the workspace owner**, i.e. the bootstrap admin on the public workspace — looked up via `WorkspaceRepository`/`UserRepository`, falling back to the requesting user) and a per-user child named by **email** (owned by that user; email, not display name, because the unique index is on `lower(trim(name))`). Both levels share one `_get_or_create_folder` that handles the unique-index race; every error path swallows and returns `None` so a folder hiccup never fails a generation. It is a module-level helper using `self.media_repo.db` on purpose — no new constructor params, so existing service tests keep working. It is called at the **placeholder creation** of all 7 sites (imagen ×3, veo ×2, audio, workbench render) and must stay in the request path: the ContextVar is not visible from the background worker. Renaming the root breaks the name-based lookup (a fresh `Izumi Agent` is created next time) — accepted trade-off instead of a system-folder column.
- **Folder delete/rename/move is owner-scoped; `workspace_auth.authorize` alone is NOT enough.** `authorize` only answers "may this user act in the workspace" (auto-pass on PUBLIC scope, membership on PRIVATE), and folder delete cascades over every media item in the subtree — which used to bypass the per-item owner check that `GalleryService.bulk_delete` already had. The policy now lives in `FolderService`: `is_workspace_manager(user, workspace)` = global ADMIN **or** owner of a *PRIVATE* workspace (public-workspace owners get nothing special); `ensure_can_manage_folder(folder, user, workspace, check_subtree=…)` lets non-managers touch only folders they created, and with `check_subtree=True` (delete, re-parent, move-items) additionally refuses if `FolderRepository.subtree_has_foreign_content` finds any subfolder/media/asset owned by someone else (NULL owners count as foreign); `ensure_can_move_items` applies the same to every folder and item in a `MoveItemsDto` via `has_foreign_items`. The controller decides `check_subtree` (`update_folder`: only when `parent_id` actually changes). `copy_items` and media `bulk_delete` are untouched. Membership roles (`WorkspaceRoleEnum`) are deliberately not consulted yet. Frontend mirrors it in `MediaGalleryComponent.canManageFolder()` → `FolderCardComponent.canManage` (hides Edit/Move/Delete, blocks drag; Copy stays) and shows the 403 `detail` as the toast. **Never name a method `assert_*`** on a class that tests replace with `AsyncMock()`/`MagicMock()`: `unittest.mock` raises `AttributeError` for unknown `assert*` attributes, which is why the policy methods are `ensure_can_*`.
- **The Workbench "Feedback" pill is configured in `frontend/src/app/common/config/feedback-config.ts`, not in `environment.*`.** `FEEDBACK_FORM_URL` is a tracked constant (the same Google Form is shared by every deployment); `resolveFeedbackFormUrl()` lets a gitignored `environment.development.ts` override it via an *untyped* optional `feedbackFormUrl` and returns `''` for anything that is not `https://`. `FeedbackFabComponent` (`app-feedback-fab`, declared in `app.module.ts`, mounted only at the end of `workbench.component.html`) renders nothing when the URL is empty, so the button is invisible until a form URL is pasted in. It was deliberately **not** added as a typed environment field (would break the user's gitignored local env file) nor as a `cloudbuild-deploy.yaml` substitution (needs trigger changes in infra). Google Forms pre-fill (`entry.<id>=` query params) is not wired yet.
- **The agent deletes `parameters.storyline_guidance` in templated mode — brief length has nothing to do with "missing scenes".** Upstream `ads_x/tools/strategy/strategy_tools.py::map_strategy_to_metadata` strips `storyline_guidance` from `parameters` whenever `template_name != "Custom"` ("Storyline sanitized for templated mode"); a brief that names a template (e.g. "Feature Spotlight") therefore loses its planned beats from `session.state` right after extraction, while the earlier `extract_campaign_parameters` delta is still in `session.events`. The Campaign tab shows **Planned beats** (from `parameters.storyline_guidance.scenes`) only until the storyboard exists, then **Scene breakdown** (from `storyboard.scenes`) — a session parked at the strategy gate has no storyboard yet, so without the beats it shows nothing. The frontend fix lives in `campaign-details.ts` (`findStorylineGuidanceInEvents`, `withStorylineGuidance`) and `ChatInterfaceComponent.syncCampaignDetails(state, keepExisting, events)`: streamed `parameters` without a storyline inherit the one already seen; session loads recover it from `events`. `StoryboardComponent.plannedBeatsHint` tells the user the template drives the final structure. Do not "fix" this by clearing stale beats on every delta — that reintroduces the bug. The brief card is clamped (`BRIEF_COLLAPSE_THRESHOLD = 280` chars, `white-space: pre-line`, Show more/less) and the toggle resets only when the brief *text* changes, because `campaignDetails` is re-emitted on every delta.
- **The Workbench video track has exactly ONE layout formula: `start(N+1) = start(N) + duration(N) − transition(N)/2`.** It mirrors the backend ffmpeg xfade graph (`ffmpeg_service._build_filter_complex` → `clip_start_times`) and Izumi's `video_stitching_service`. Audio clips are stored as **absolute** `startTime` (`start_at: {video_clip_index: -1, offset_seconds}`), so if the UI lays the video track out differently from the render, the user positions audio against a wrong reference and the render "ignores" the move. That is precisely what happened: `refreshTimelineLayout()` (called on clip delete, trim end and metadata extraction) used `currentTime += clip.duration` with no overlap, so after deleting a voiceover every video clip slid later by Σ(transition/2) on screen while the render stayed put. All relayouts in `workbench.component.ts` now go through the private `layoutVideoTrack()` helper (used by `refreshTimelineLayout` and `resolveOverlaps`; `processGeneratedData` and `applyMiddleTransitionToClips` apply the same formula inline because they also build/patch the clips). Never add a new relayout path that doesn't subtract `transition/2`, and never change the formula in one place only — update the helper and the backend together. Regression specs live in `workbench.component.spec.ts` under "Video track layout (cross-fade overlap)".

---
