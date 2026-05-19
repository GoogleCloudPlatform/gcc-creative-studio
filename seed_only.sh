#!/bin/bash
# A standalone script to run database seeding directly from the private jump box VM.
# It bypasses Terraform, Node.js, and Firebase requirements, needing only gcloud and python.

set -e

# Helper colors
C_RESET='\033[0m'
C_GREEN='\033[1;32m'
C_RED='\033[1;31m'
C_CYAN='\033[1;36m'
C_YELLOW='\033[1;33m'

info() { echo -e "${C_CYAN}➡️  $1${C_RESET}"; }
success() { echo -e "${C_GREEN}✅  $1${C_RESET}"; }
fail() { echo -e "${C_RED}❌  $1${C_RESET}" >&2; exit 1; }
warn() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }

# Detect Project ID
GCP_PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$GCP_PROJECT_ID" ]; then
    fail "Could not determine active gcloud project. Please run 'gcloud config set project [ID]' first."
fi

info "Using Project: ${C_YELLOW}${GCP_PROJECT_ID}${C_RESET}"

# 1. Resolve Cloud SQL connection name using gcloud
info "Locating Cloud SQL private instance..."
DB_INSTANCE_NAME=$(gcloud sql instances list --format="value(connectionName)" --filter="name:creative-studio-db*" --project="$GCP_PROJECT_ID" | head -n 1)

if [ -z "$DB_INSTANCE_NAME" ]; then
    fail "Could not find active Cloud SQL instance in project $GCP_PROJECT_ID."
fi
info "Found database instance: ${C_YELLOW}${DB_INSTANCE_NAME}${C_RESET}"

# 2. Fetch password from Secret Manager
info "Retrieving database password..."
DB_PASS=$(gcloud secrets versions access latest --secret="creative-studio-db-password" --project="$GCP_PROJECT_ID" || fail "Failed to read secret 'creative-studio-db-password' from Secret Manager.")

export DB_USER="studio_user"
export DB_PASS="$DB_PASS"
export DB_NAME="creative_studio"
export DB_HOST="127.0.0.1" 
export DB_PORT="5432"
export USE_CLOUD_SQL_AUTH_PROXY=true

# 3. Start Cloud SQL Auth Proxy
if [ ! -f "cloud-sql-proxy" ]; then
    info "Downloading Cloud SQL Auth Proxy..."
    curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.linux.amd64
    chmod +x cloud-sql-proxy
fi

info "Starting Cloud SQL Proxy (Private IP)..."
./cloud-sql-proxy --address 0.0.0.0 --port 5432 --private-ip "$DB_INSTANCE_NAME" > /dev/null 2>&1 &
PROXY_PID=$!
export PROXY_PID

# Ensure proxy stops on exit
stop_proxy() {
    if [ -n "$PROXY_PID" ]; then
        info "Stopping Cloud SQL Proxy..."
        kill "$PROXY_PID" 2>/dev/null || true
    fi
}
trap stop_proxy EXIT

# Wait for proxy readiness
echo -n "   Waiting for proxy connection..."
for i in {1..30}; do
    if (echo > /dev/tcp/127.0.0.1/5432) >/dev/null 2>&1; then
        echo " Connected!"
        break
    fi
    echo -n "."
    sleep 1
done

# 4. Setup Environment and run Python Seeding Script
CURRENT_USER=$(gcloud config get-value account 2>/dev/null || echo "system")
ASSET_BUCKET_NAME="${GCP_PROJECT_ID}-cs-development-bucket"

export GOOGLE_CLOUD_PROJECT=$GCP_PROJECT_ID
export ADMIN_USER_EMAIL=$CURRENT_USER
export GENMEDIA_BUCKET=$ASSET_BUCKET_NAME

# Install uv if missing
if ! command -v uv >/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

info "Setting up Python virtual environment..."
VENV_DIR="backend/.venv"
uv venv "$VENV_DIR" --python 3.12 --clear

info "Installing dependencies from pyproject.toml..."
uv pip install --python "$VENV_DIR/bin/python" -e backend

info "Running seeding script..."
if (cd backend && "$VENV_DIR/bin/python" -m bootstrap.bootstrap); then
    success "Database seeded successfully."
else
    fail "Database seeding failed."
fi
