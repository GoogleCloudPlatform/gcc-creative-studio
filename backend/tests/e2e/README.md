# Creative Studio E2E Test Suite Infrastructure & Architecture

This document describes the design, methodology, and execution instructions for the End-to-End (E2E) testing framework in Google Cloud Creative Studio.

---

## 1. Feature Inventory

The E2E test suite covers the following features and requirements:

*   **R1: Authenticated Multimodal Text Generation** (`POST /api/gemini/multimodal-generation`)
    *   Prompt-only text generation.
    *   Text generation with single source asset references.
    *   Text generation with single media item references.
    *   Text generation with mixed assets (source assets + media items).
    *   Custom model configuration and parameter parsing.
    *   Authentication and permission checks (unauthenticated and unauthorized roles).
    *   Gemini API exception handling and graceful failures.

*   **R2 & R3: Database Schema Compliance & Automatic Metadata Generation**
    *   Programmatic SQLAlchemy reflection checks ensuring `title` and `description` exist on `media_items` and `source_assets` tables.
    *   Source Asset upload (`POST /api/source_assets/upload`) metadata generation and DB persistence.
    *   Imagen Image generation (`POST /api/images/generate-images`) metadata generation.
    *   Veo Video generation (`POST /api/videos/generate-videos`) metadata generation.
    *   Audio generation (`POST /api/audios/generate`) metadata generation.
    *   User-provided titles/descriptions are ignored and overwritten by Gemini.
    *   Graceful fallback to default/null metadata values if Gemini metadata generation service fails.

*   **R4: DTO Synchronization & Unified Gallery Retrieval**
    *   Verify API responses (`SourceAssetResponseDto`, `MediaItemResponse`) include camelCased `title` and `description`.
    *   Lifecycle checks: asset upload -> multimodal generation usage -> deletion -> soft-delete database status.

---

## 2. Testing Methodology & E2E Test Architecture

Our E2E test architecture ensures full integration testing from the HTTP routing layer down to the physical PostgreSQL database, while keeping tests offline-capable and deterministic by mocking external Google Cloud dependencies.

### 2.1 Component Architecture

```
                    +--------------------+
                    |  FastAPI App (app) |
                    +--------------------+
                              |
                     [FastAPI TestClient]
                              |
           +------------------+-------------------+
           |                                      |
           v                                      v
  [Authenticated Routers]               [Background Workers]
  (Controller / Route context)        (ThreadPoolExecutor context)
           |                                      |
           +------------------+-------------------+
                              |
                              v
                     [Service / Repo layers]
                              |
           +------------------+-------------------+
           |                                      |
           v                                      v
+-----------------------+              +-----------------------+
|  Real Database        |              |  Mocked External APIs |
|  (PostgreSQL Local)   |              |  - Gemini Client      |
|                       |              |  - GCS Storage        |
+-----------------------+              +-----------------------+
```

1.  **FastAPI TestClient Context**: HTTP requests hit real FastAPI route handlers, resolving dependency injections (FastAPI `Depends()`).
2.  **Authentication Mocking**: The test runner overrides `get_current_user` to mock specific roles (`UserModel`).
3.  **Real Database Connection**: We route database operations to the active PostgreSQL container. We do not mock SQL operations; the system queries and writes to real tables.
4.  **Mocked External APIs**:
    *   **Gemini AI**: The singleton class `GenAIModelSetup` is patched to return a `MagicMock` client that simulates model generations (text output, JSON structures, image URIs).
    *   **Google Cloud Storage**: The `GcsService` helper class is mocked to return simulated GCS URIs (`gs://mock-bucket/...`) and local dummy paths without hitting network APIs.

---

## 3. Database Isolation and Cleanup Strategy

Because background tasks (Imagen, Veo, Audio) execute in a `ThreadPoolExecutor` using the `WorkerDatabase` context manager (which creates independent SQLAlchemy sessions and loops), a standard transaction rollback on the main test thread is insufficient.

To prevent test-to-test pollution:
1.  Each test creates a **temporary workspace** via `POST /api/workspaces` and performs all actions within that workspace.
2.  Upon completion, the `e2e_test_workspace` fixture runs a cascade delete in the database tables `media_items`, `source_assets`, and `workspaces` for that workspace ID.

---

## 4. Run Commands

All tests must be run inside the `creative-studio-backend` docker container.

### 4.1 Running the entire E2E test suite
```bash
docker exec -t creative-studio-backend uv run pytest tests/e2e -v
```

### 4.2 Running a specific file
```bash
docker exec -t creative-studio-backend uv run pytest tests/e2e/test_multimodal.py -v
```

### 4.3 Running with coverage check
```bash
docker exec -t creative-studio-backend uv run pytest tests/e2e -v --cov=src --cov-fail-under=80
```
