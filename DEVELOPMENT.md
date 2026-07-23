# Step by step guide for DEVs | Local Development of Creative Studio

This guide provides a comprehensive walkthrough for setting up and running the Creative Studio application **on your local machine**. It covers the **standard local development setup using Docker Compose**.

## 1. Prerequisites

Before you begin, ensure you have the following tools installed on your system:

- **Git**: For cloning the repository.
- **Google Cloud CLI (gcloud)**: For authenticating and managing your GCP resources.
- **Github Account**: If you don't already have a GitHub account.
- **Install Antigravity**: [Download Antigravity](https://antigravity.google/)
- **Install Docker and docker compose**: [Download Docker](http://docker.com/get-started/)
- **Install nvm**: [Download nvm](https://github.com/nvm-sh/nvm#installing-and-updating) and then install the latest node version. Version 20 or higher.
- **Install uv**: A fast Python package installer. [Install it here](https://github.com/astral-sh/uv).

## 2. Initial Setup

1.  Go to your GCP Account and make sure you can login.
2.  After you create your account:
    - You create a fork of [Open Source Repo](https://github.com/GoogleCloudPlatform/gcc-creative-studio/tree/main)
    - You see this video [How to Deploy Creative Studio.mp4](./screenshots/how_to_deploy_creative_studio.mp4) and deploy Creative Studio into your GCP Account environment, using CloudShell for simplicity.
3.  Ensure required Google Cloud APIs are enabled in your project:
    - **Google Drive API**: Ensure `drive.googleapis.com` is enabled in your project via the [Google Cloud Console API Overview](https://console.developers.google.com/apis/api/drive.googleapis.com/overview) if planning to use media gallery upload from Drive.

## 3. Add env variables to repo where we’ll work

You can connect to your new GCP Argolis Account by setting a `backend/.env` file for the backend and a `frontend/src/environments/development.environment.ts` file for the frontend.

> **Important!!!** set `isLocal = True`, in both frontend and backend, this is so that instead of loggin in with Identity Platform, we login with Firebase, and we keep Identity Platform Authorized Javascript origins clean, without the need to whitelist localhost.

Add the following env variables in your cloned repo “gcc-creative-studio” modifying the corresponding locations, and replacing with your env values:

### `backend/.env` file

```bash
# Common env vars
FRONTEND_URL="http://localhost:4200"
ENVIRONMENT="local"
LOG_LEVEL="INFO"

# Project ID: creative-studio-deploy
GOOGLE_CLOUD_PROJECT="creative-studio-deploy"
PROJECT_ID="creative-studio-deploy"
GENMEDIA_BUCKET="creative-studio-deploy-cs-development-bucket"
SIGNING_SA_EMAIL="cs-development-read@creative-studio-deploy.iam.gserviceaccount.com"
GOOGLE_TOKEN_AUDIENCE="XXXX-XXXXXXXXXXX.apps.googleusercontent.com"
IDENTITY_PLATFORM_ALLOWED_ORGS=""

# --- Database Configuration (Local Docker Postgres) ---
DB_USER="studio_user"
DB_PASS="studio_pass"
DB_NAME="creative_studio"
DB_HOST="postgres"
DB_PORT="5432"
USE_CLOUD_SQL_AUTH_PROXY=false
ADMIN_USER_EMAIL="your-user-email"
```

> 💡 **Best Practice Tip: Local PostgreSQL Container**
> For local development and testing, we include a lightweight PostgreSQL Docker container to bypass the need for an actual Cloud SQL instance. This delivers key advantages:
>
> - **Zero Costs**: Avoids billing accrual on cloud data lookups during validation work cycles.
> - **Safe Experimentation**: Clear volume bindings locally without risking production states or accidental cloud data drops.
> - **Instant Migrations Validation**: Speed runs Alembic updates completely isolated and offline.

### `frontend/src/environments/development.environment.ts` file

```typescript
export const environment = {
  // Project ID: creative-studio-deploy
  firebase: {
    apiKey: "your-api-key",
    authDomain: "creative-studio-deploy.firebaseapp.com",
    projectId: "creative-studio-deploy",
    storageBucket: "creative-studio-deploy.firebasestorage.app",
    messagingSenderId: "your-messaging-sender-id",
    appId: "your-app-id",
    measurementId: "G-XXXXXXXX",
  },
  production: false,
  isLocal: true,
  GOOGLE_CLIENT_ID: "XXXX-XXXXXXXXXXX.apps.googleusercontent.com",
  backendURL: "http://localhost:8080/api",

  // Common env vars
  EMAIL_REGEX:
    /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/,
  ADMIN: "admin",
};
```

## 4. Running with Docker Compose

We use Docker to build and run both the frontend and backend containers, simplifying the setup process.

After installation and before running docker compose, be sure to set your default gcloud login:

```bash
# Set the target project for the deployment
gcloud config set project $PROJECT_ID

# Set up application-default credentials
gcloud auth application-default login
```

And also to give your account access to presign the urls you’ll get on your frontend:

```bash
export PROJECT_ID=$(gcloud config get project)
export USER_EMAIL=$(gcloud config get account)

gcloud iam service-accounts add-iam-policy-binding cs-development-read@$PROJECT_ID.iam.gserviceaccount.com --member="user:$USER_EMAIL" --role="roles/iam.serviceAccountTokenCreator"
```

You are all set, from the root of the project, run the following command:

```bash
docker compose up
```

### 💡 Seeding Initial Workspaces (Local Development/Testing)

If you are running this locally for the first time or your database is fresh, you might find that the Workspaces list is empty. You should run the bootstrap script once to seed default templates and verify access:

```bash
docker exec -t creative-studio-backend sh -c "PYTHONPATH=/app uv run python -m bootstrap.bootstrap"
```

As this uses volumes, and we use hot reload to start the services, every time you change something on the files the container will be refreshed with the changes.

## 5. Code Quality & Pre-commit Hooks

To maintain code quality and consistency, we use a fully containerized `pre-commit` pipeline. **DO NOT** run linters locally on your host machine.

### Setup Git Hook

Run once from the root of the project:

```bash
cp pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

This will link the pre-commit hook to your git workflow. Now, every time you commit, the hooks will run automatically inside a Docker container.

### Manual Run

To format and lint the **entire repository** at once:

```bash
docker compose run --rm pre-commit run --all-files
```

### Linters Used

- **Backend**: `black` (formatting), `pylint` (linting).
- **Frontend**: `gts` (ESLint + Prettier).
- **License**: `addlicense` (adds headers).
