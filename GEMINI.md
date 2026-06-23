# 🤖 GEMINI.md - AI Agent & Developer Guide

This document serves as a comprehensive guide for AI Agents and developers working on the **GCC Creative Studio** project. It outlines the architecture, setup, development workflow, and strict guidelines to ensure code quality and consistency.

---

## 🏗️ System Architecture

Creative Studio follows a **Modular, Feature-Driven Architecture** (inspired by Hexagonal Architecture).

*   **Structure:** Code is organized by feature domain (e.g., `/images`, `/users`) rather than technical layer.
*   **Cohesion:** All code for a single feature is co-located (controllers, services, DTOs).
*   **Coupling:** Modules interact through well-defined interfaces.

---

## 🚀 Bootstrapping (Docker Compose)

The standard development environment uses **Docker Compose**.

### 1. Prerequisites
*   **gcloud CLI**: Authenticated and project set.
*   **Docker & Docker Compose**
*   **uv**: Fast Python package installer.

### 2. Environment Configuration
*   **Backend (`backend/.env`)**:
    *   Set `ENVIRONMENT="local"`
    *   Set `USE_CLOUD_SQL_AUTH_PROXY=false` (uses local Postgres container).
    *   Set `isLocal = True` (critical for local auth).
*   **Frontend (`frontend/src/environments/environment.development.ts`)**:
    *   Set `isLocal: true`
    *   Configure Firebase credentials.

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
*   **Hot Reload**: Enabled by default in Docker.
*   **Package Management**: Uses `uv` and `pyproject.toml`.
*   **Running Scripts**: **ALWAYS** use `docker compose` to run Python scripts (e.g., `docker exec ...`).

### Frontend (Angular)
*   **Reactivity**: Strictly use **Angular Signals** for state management and computed values.
*   **API Calls**: Implement API calls in a **Service**. **DO NOT** use `fetch` or `HttpClient` directly inside components.

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
*   **Backend**: `black` (formatting), `pylint` (linting).
*   **Frontend**: `gts` (ESLint + Prettier).
*   **License**: `addlicense` (adds headers).

---

## 🧪 Running Tests

### Backend (Python)
We use `pytest` and `pytest-cov`.

> [!IMPORTANT]
> **PR Requirement**: You must achieve at least **80% code coverage** across all `src/` files.

**Verify Coverage Locally**:
```bash
cd backend
uv run pytest tests -v --cov=src --cov-fail-under=80
```

**Run Specific Tests**:
```bash
uv run pytest tests/users -v
```

---

## 📜 AI Agent Guidelines & Senior Rules

To maintain a pristine codebase, AI Agents **MUST** follow these rules:

1.  **Docker Enforcement**: Always use `docker compose` or `docker exec` to run Python scripts or commands that interact with the app environment.
2.  **No Placeholders**: Never use placeholder images or text. Use generation tools or real assets.
3.  **Precise Edits**: When editing files, ensure you replace **only** the target content. **DO NOT** append garbage lines or duplicate code.
4.  **Reactivity First**: In Angular, leverage Signals for computed state to avoid reactivity bugs.
5.  **Error Handling**: Always wrap async/stream operations in `try/catch` and log errors appropriately.
6.  **Format Before Commit**: Always ensure the code is formatted (`npm run format` for frontend, `black` for backend) before suggesting a commit.

---
