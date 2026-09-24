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
- **`write_state` does NOT set the shell variable.** It only appends to the profile file. So `write_state "TF_BUCKET_NAME" "$X"` leaves `$TF_BUCKET_NAME` empty for the rest of the run unless it was sourced by `read_state` on a previous run. This caused a silent bug: the migration bucket fell back to `${GCP_PROJECT_ID}-terraform-state`, which never matches the real convention `${GCP_PROJECT_ID}-cstudio-${ENV_NAME}-tfstate`, so `gcloud storage ls` queried a non-existent bucket, `2>/dev/null` swallowed the error, and Step 9 skipped the migration prompt while printing nothing. Always resolve it via `resolve_migration_bucket()`.
- **Never let a detection step print nothing.** Every branch of a step must emit at least one line, otherwise a silent failure is indistinguishable from a correct skip.
- **Backend service names are not fixed.** Legacy deployments use `cstudio-be`; current ones use `cs-[ENV_NAME]-backend`. Always check both with `gcloud run services describe` before acting — never assume which exists.
- **Imports need an empty schema.** Terraform may update a Cloud SQL instance in place, leaving tables behind. `gcloud sql import` then fails with `relation "..." already exists`. Always drop + recreate `creative_studio` right before importing.
- **Migration artifacts live in the Terraform state bucket only.** `migration_backup.sql.gz` goes in `$TF_BUCKET_NAME` — that bucket owns infrastructure artifacts. Do not scan or write to the asset bucket for migrations.
- **PITR makes constant backup prompts redundant.** New Private IP instances have Point-in-Time Recovery. The default "happy path" must stay **completely silent** — no prompts, no backups. Only prompt when there is a real legacy signal (V1 DB, orphaned backup) or an explicit `--migrate-db`.
- **Izumi: region pinning is REQUIRED, and it only works together with model pinning.** Vertex AI's `global` endpoint gives **no data residency guarantee** — requests may be processed in any region, which fails GDPR/sovereignty requirements. Izumi hardcodes `"GOOGLE_CLOUD_LOCATION": "global"` in the runtime `env_vars` of `scripts/deploy_to_agent_platform.py`, and `mediagent_kit/__init__.py` prefers that over `IZUMI_LOCATION`, so `bootstrap.sh` **must** `sed` it to `$DEPLOY_REGION`. The catch: Izumi's default models (`gemini-3.7-flash`, `gemini-3.1-pro-preview`) are served from `global` only, so pinning the region *without* also pinning the models produces "model not found in europe" 404s. **Do both or neither.** An earlier agent removed the `sed` to "fix" the 404 — that silently broke residency and did not fix the agent.
- **Izumi: `ads_x/agent.py` hardcodes `model=` on every `LlmAgent` (13× `gemini-3.7-flash`, 1× `gemini-3.1-pro-preview`).** `mediagent_config.json` does **not** reach these — it only feeds `mediagent_kit` helpers (`utils/adk.py`, `cs_media_generation_service`). Pinning only the JSON is a no-op for the agent's actual reasoning. `bootstrap.sh` seds the literals directly.
- **Izumi: `MODEL_TARGET_LOCATION` is a second residency leak.** With `USE_CREATIVE_STUDIO=True` it is the location of the `genai.Client` in `cs_media_generation_service.generate_text_inline` (the only direct Vertex client on that path — video/tts/music go through the Creative Studio backend). Set it to `$DEPLOY_REGION`, not `global`.
- **Izumi: `mediagent_config.json` is NOT read at runtime inside Agent Engine — `mediagent_kit/config.py` is the real source of truth.** The deploy script copies `demos/backend/*` and `mediagent_kit/` into the bundle and nothing else, so upstream's repo-root copy never even reaches the agent. But writing it to `demos/backend/mediagent_config.json` is *also* not enough: `MediagentKitConfig` resolves the file CWD-relative (or relative to the parent of `mediagent_kit/`), and at runtime neither matches, because `pip install .` puts `mediagent_kit` in `.venv/site-packages`. The Agent Engine log proved it — `models={'text': {'default': 'gemini-3.7-flash'…}}` with **no** `[MediagentKitConfig] Loaded models from …` line. **Therefore `bootstrap.sh` seds the hardcoded fallback dict in `mediagent_kit/config.py` directly.** The JSON is still written as a belt-and-braces measure for local runs.
- **The absence of `[MediagentKitConfig] Loaded models from <path>` in the logs is the single best diagnostic.** `config.py` prints it unconditionally whenever it finds the JSON; if you do not see it, the JSON was not discovered and only the hardcoded fallbacks are in play.
- **Izumi: every patch must be verified, never silent.** A `sed` that stops matching after an upstream refactor would either break the agent or silently violate data residency. Always `grep` first and report success/failure explicitly. `bootstrap.sh` additionally re-verifies inside Cloud Build (on the *uploaded* source) and `exit 1`s before deploying if any unsupported literal survived — a local check cannot prove what actually got uploaded.
- **Never write `$(grep -c … || echo 0)`.** `grep -c` prints `0` **and** exits 1 when there are no matches, so the substitution yields `"0\n0"` and `[ … -gt 0 ]` dies with `integer expression expected`. Use `grep -o … | wc -l | tr -d ' '`.
- **Izumi model pinning.** `gemini-2.5-flash` and `gemini-2.5-pro` are in upstream's `_compatible_models` for text and are both available on `europe-west1`/`europe-west4`. Because `config.py`'s fallbacks are patched by literal substitution, the media families (`image_gemini`, `video`, `music`, `tts`) are only touched when `IZUMI_REGIONAL_MEDIA=true` / `--regional-media`.
- **Izumi: residual `global` calls that cannot be regionalized.** `media_generation_service.py` forces `region = "global"` for any model whose name contains `preview`, and Lyria 3 / Omni hardcode `…/locations/global/interactions`. These are unreachable on this deployment (`USE_CREATIVE_STUDIO=True` routes media through `CSMediaGenerationService`), but they would matter if Creative Studio were disabled.
- **Izumi never calls Vertex for media.** `CSMediaGenerationService.generate_image/video/tts/music` POST to the Creative Studio backend (`/api/images/generate-images` etc.) with `generationModel` in the payload; the only direct `genai.Client` on that path is `generate_text_inline`. This is why media kept working while text was 404ing. Consequence: Izumi's media model names are only a *compatibility* concern with our backend's `GenerationModelEnum`, not a residency one.
- **`IZUMI_REGIONAL_MEDIA` is opt-in on purpose.** Pinning media to older models (`gemini-2.5-flash-image`, `imagen-4.0-generate-001`, `veo-3.1-generate-001`, `lyria-002`, `gemini-2.5-flash-tts`) costs output quality, and the newer defaults work today. Only set it for clients whose Vertex processing must stay in-region. Text pinning, by contrast, is always on — it is mandatory once the endpoint is regional. **Caveat: until the backend's `LOCATION` is pinned (next bullet), the flag does NOT deliver regional media** — Izumi only names the model, and the backend calls it on `global`. That is also why video is `veo-3.1-generate-001`: `veo-3.0-generate-001` 404s on `global` (seen on `creative-studio-test-4`), while 3.1 was verified working through the Creative Studio UI. Every media model chosen here must be served wherever the backend actually calls it.
- **The real media residency gap is Creative Studio's own config, not Izumi.** `backend/src/config/config_service.py` defaults `LOCATION: str = "global"`, and nothing in `infrastructure/app.tf` overrides it (only `AGENT_LOCATION` and `WORKFLOWS_LOCATION` are set). So the backend's GenAI client runs on the global endpoint regardless of what Izumi does. Fixing that is a Terraform/app change (`LOCATION = var.region`) and must be paired with regionally available model IDs, or image/video generation will start 404ing.

---
