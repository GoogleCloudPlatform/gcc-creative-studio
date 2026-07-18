#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -e

# --- Argument Parsing ---
TARGET_VERSION="latest"
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -v|--version) TARGET_VERSION="$2"; shift ;;
        *) warn "Unknown parameter: $1"; echo "Usage: ./deploy.sh [--version v1.2.0]"; exit 1 ;;
    esac
    shift
done

info "Target Release Version: ${C_YELLOW}${TARGET_VERSION}${C_RESET}"

# --- Configuration ---
REQUIRED_TERRAFORM_VERSION="1.15.5"
UPSTREAM_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio"
TEMPLATE_ENV_DIR="environments/example"
DEFAULT_ENV_NAME="dev"
DEFAULT_BRANCH_NAME="main"
GCS_BUCKET_SUFFIX_FORMAT="cstudio-%s-tfstate"
GCS_BUCKET_PREFIX_FORMAT="terraform/state/%s"
BE_SERVICE_NAME="cstudio-backend"
FE_SERVICE_NAME="cstudio-frontend"

# script will automatically set these
AUTO_FIREBASE_API_KEY=""           # Your Firebase Web API Key
AUTO_FIREBASE_AUTH_DOMAIN=""       # Your Firebase Auth Domain
AUTO_FIREBASE_PROJECT_ID=""        # Your Firebase Project ID
AUTO_FIREBASE_STORAGE_BUCKET=""    # Your Firebase Storage Bucket
AUTO_FIREBASE_MESSAGING_SENDER_ID="" # Your Firebase FCM Sender ID
AUTO_FIREBASE_APP_ID=""            # Your Firebase Web App ID
AUTO_FIREBASE_MEASUREMENT_ID=""    # Your Analytics ID
AUTO_OAUTH_CLIENT_ID=""
AUTO_FIREBASE_SITE_ID=""           # Dynamic discovered Firebase site

STATE_FILE=""
REPO_ROOT=""

# --- Color Definitions (High Contrast) ---
C_RESET='\033[0m'
C_RED='\033[1;31m'     # Bold/Bright Red for errors
C_GREEN='\033[1;32m'   # Bold/Bright Green for success
C_YELLOW='\033[1;33m'  # Bold/Bright Yellow for warnings
C_BLUE='\033[1;34m'    # Bold/Bright Blue for steps and prompts
C_CYAN='\033[1;36m'    # Bold/Bright Cyan for general info

# --- Helper Functions ---
info() { echo -e "${C_CYAN}➡️  $1${C_RESET}"; }
prompt() { echo -e "${C_BLUE}🤔  $1${C_RESET}"; }
warn() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
fail() { echo -e "${C_RED}❌  $1${C_RESET}" >&2; exit 1; }
success() { echo -e "${C_GREEN}✅  $1${C_RESET}"; }
step() { echo -e "\n${C_BLUE}--- Step $1: $2 ---${C_RESET}"; }

# --- Terminal Spinner ---
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    tput civis # Hide cursor
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " ${C_CYAN}[%c]${C_RESET}  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "      \b\b\b\b\b\b"
    tput cnorm # Show cursor
}

# --- State Management ---
write_state() {
    if [ -z "$STATE_FILE" ]; then return; fi
    if ! (
        touch "$STATE_FILE"
        TMP_STATE_FILE=$(mktemp)
        grep -v "^$1=" "$STATE_FILE" > "$TMP_STATE_FILE" || true
        echo "$1=$2" >> "$TMP_STATE_FILE"
        mv "$TMP_STATE_FILE" "$STATE_FILE"
    ); then
        warn "Could not write to state file: $STATE_FILE. Resuming will not be possible."
    fi
}
read_state() {
    if [ -f "$STATE_FILE" ]; then
        info "Found previous state file. Resuming..."
        set -a; source "$STATE_FILE"; set +a
    fi
}

# --- Firebase Discovery ---
configure_firebase_site_id() {
    info "Checking Firebase Hosting Site configuration..."
    local tfvars_file=$1
    local project_id=$2

    if grep -q "YOUR_FIREBASE_SITE_ID" "$tfvars_file" 2>/dev/null || grep -q "firebase_site_id[[:space:]]*=" "$tfvars_file" 2>/dev/null; then
        local current_site_val=$(grep 'firebase_site_id' "$tfvars_file" | awk -F'"' '{print $2}' 2>/dev/null || echo "")
        if [ -z "$current_site_val" ] || [ "$current_site_val" == "YOUR_FIREBASE_SITE_ID" ]; then
            warn "Placeholder or empty 'firebase_site_id' found in ${tfvars_file}."
            info "Querying Firebase for an existing default hosting site..."

            local default_site_name
            default_site_name=$(firebase hosting:sites:list --project "$project_id" --json | jq -r 'first(.result.sites[] | select(.type == "DEFAULT_SITE") | .name) // first(.result.sites[].name) // ""' 2>/dev/null || echo "")

            local site_id_to_use=$project_id
            [ -n "$default_site_name" ] && site_id_to_use=$(basename "$default_site_name")

            info "Setting 'firebase_site_id' to '${C_YELLOW}${site_id_to_use}${C_RESET}' in ${tfvars_file}."
            
            if grep -q "firebase_site_id" "$tfvars_file"; then
                sed -i.bak "s|^[#[:space:]]*firebase_site_id[[:space:]]*=.*|firebase_site_id = \"${site_id_to_use}\"|g" "$tfvars_file" && rm -f "${tfvars_file}.bak"
            else
                echo -e "\nfirebase_site_id = \"${site_id_to_use}\"" >> "$tfvars_file"
            fi
        fi
    else
        # Append if missing
        info "Querying default Firebase site..."
        local default_site_name
        default_site_name=$(firebase hosting:sites:list --project "$project_id" --json | jq -r 'first(.result.sites[] | select(.type == "DEFAULT_SITE") | .name) // first(.result.sites[].name) // ""' 2>/dev/null || echo "")
        local site_id_to_use=$project_id
        [ -n "$default_site_name" ] && site_id_to_use=$(basename "$default_site_name")
        echo -e "\nfirebase_site_id = \"${site_id_to_use}\"" >> "$tfvars_file"
    fi
}

prompt_and_update_tfvar() {
    local prompt_text=$1
    local default_value=$2
    local tfvar_name=$3
    local var_to_set_ref=$4

    read -p "   $prompt_text [default value: $default_value]: " user_input < /dev/tty
    local final_value=${user_input:-$default_value}

    sed -i.bak "s|^[#[:space:]]*${tfvar_name}[[:space:]]*=.*|${tfvar_name} = \"${final_value}\"|g" "$TFVARS_FILE_PATH" && rm -f "${TFVARS_FILE_PATH}.bak"
    eval "$var_to_set_ref='$final_value'"
}

# --- Script Core Phases ---

check_prerequisites() {
    step 1 "Checking Prerequisites"
    command -v gcloud >/dev/null || fail "gcloud CLI not found. Please install."
    command -v git >/dev/null || fail "git not found. Please install it."
    if ! command -v jq &> /dev/null; then
        fail "The 'jq' command is required but not found. Please install it."
    fi
    if ! command -v firebase &> /dev/null; then
        fail "Firebase CLI ('firebase-tools') is not installed. Please run 'npm install -g firebase-tools'."
    fi
    if ! command -v node &> /dev/null; then
        fail "Node.js is not found. Please install it."
    fi
    if ! command -v npm &> /dev/null; then
        fail "npm is not found. Please install it."
    fi
    success "Prerequisites met: gcloud, git, jq, firebase, node, npm."
}

check_and_install_terraform() {
    step 2 "Checking Terraform Installation"
    if ! command -v terraform &> /dev/null; then
        warn "Terraform is not installed."
        install_terraform
        return
    fi
    INSTALLED_VERSION=$(terraform version -json | jq -r .terraform_version)
    if [[ "$(printf '%s\n' "$REQUIRED_TERRAFORM_VERSION" "$INSTALLED_VERSION" | sort -V | head -n1)" != "$REQUIRED_TERRAFORM_VERSION" ]]; then
        warn "Your Terraform version ($INSTALLED_VERSION) is older than required ($REQUIRED_TERRAFORM_VERSION)."
        install_terraform
    else
        success "Terraform version $INSTALLED_VERSION is sufficient."
    fi
}

install_terraform() {
    warn "Terraform is missing or outdated. Installing version $REQUIRED_TERRAFORM_VERSION..."
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case $ARCH in
        x86_64) ARCH="amd64" ;; aarch64) ARCH="arm64" ;; arm64) ARCH="arm64" ;;
    esac
    PLATFORM_ARCH="${OS}_${ARCH}"
    TF_ZIP_FILENAME="terraform_${REQUIRED_TERRAFORM_VERSION}_${PLATFORM_ARCH}.zip"
    TF_DOWNLOAD_URL="https://releases.hashicorp.com/terraform/${REQUIRED_TERRAFORM_VERSION}/${TF_ZIP_FILENAME}"
    
    info "Downloading Terraform..."
    curl -Lo terraform.zip "$TF_DOWNLOAD_URL"
    unzip -o terraform.zip
    mkdir -p "$HOME/bin"
    mv terraform "$HOME/bin/"
    if ! grep -q 'export PATH="$HOME/bin:$PATH"' ~/.bashrc; then
        echo -e '\n# Add local bin to PATH\nexport PATH="$HOME/bin:$PATH"' >> ~/.bashrc
    fi
    export PATH="$HOME/bin:$PATH"
    hash -r
    rm -f terraform.zip LICENSE.txt
    
    if command -v terraform &> /dev/null && [[ "$(terraform version -json | jq -r .terraform_version)" == "$REQUIRED_TERRAFORM_VERSION" ]]; then
        success "Terraform v$(terraform -version | head -n 1) is active."
    else
        fail "Terraform installation failed."
    fi
}

setup_project() {
    step 3 "Configuring Google Cloud Project"
    CURRENT_GCLOUD_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")

    if [ -n "$GCP_PROJECT_ID" ]; then
        prompt "Found project '$GCP_PROJECT_ID' from previous run. Use this project? (y/n)"
        read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            gcloud config set project "$GCP_PROJECT_ID"
            success "Project '$GCP_PROJECT_ID' configured."
            return
        fi
    elif [ -n "$CURRENT_GCLOUD_PROJECT" ]; then
        prompt "Detected active gcloud project '$CURRENT_GCLOUD_PROJECT'. Use this? (y/n)"
        read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            GCP_PROJECT_ID=$CURRENT_GCLOUD_PROJECT
            gcloud config set project "$GCP_PROJECT_ID"
            success "Project '$GCP_PROJECT_ID' configured."
            return
        fi
    fi

    prompt "Do you already have a Google Cloud Project to use? (y/n)"
    read -r REPLY < /dev/tty
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        prompt "Please enter your Google Cloud Project ID:"
        read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
    else
        prompt "What is the desired new Google Cloud Project ID? (e.g., my-creative-studio)"
        read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
        prompt "What is your Google Cloud Billing Account ID? (Find with 'gcloud beta billing accounts list')"
        read -p "   Billing Account ID: " BILLING_ACCOUNT_ID < /dev/tty
        
        info "Creating project '$GCP_PROJECT_ID'..."
        gcloud projects create "$GCP_PROJECT_ID" || warn "Project may already exist. Continuing..."
        info "Linking billing account..."
        gcloud beta billing projects link "$GCP_PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
    fi
    gcloud config set project "$GCP_PROJECT_ID"
    success "Project '$GCP_PROJECT_ID' is ready."
}

setup_repo() {
    step 4 "Configuring Git Repository Context"
    if [[ -f "bootstrap.sh" && -d "infrastructure" && -d "frontend" && -d "backend" ]]; then
        REPO_ROOT=$(pwd)
        export REPO_ROOT
        
        GITHUB_REPO_OWNER=$(git remote get-url origin 2>/dev/null | sed -n 's/.*github.com\/\(.*\)\/.*/\1/p' || echo "")
        if [ -z "$GITHUB_REPO_OWNER" ]; then
            GITHUB_REPO_OWNER="GoogleCloudPlatform"
        fi
        GITHUB_REPO_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
        GITHUB_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
        
        success "Verified repository directory: $GITHUB_REPO_NAME ($GITHUB_BRANCH)"
        return
    fi
    fail "This script must be executed from the root directory of your cloned creative-studio repository."
}

configure_environment() {
    step 5 "Configuring Terraform Environment"
    cd "$REPO_ROOT/infrastructure"
    if [ -z "$ENV_NAME" ]; then
        prompt "What would you like to call this deployment environment?"
        read -p "   Environment Name [default: $DEFAULT_ENV_NAME]: " ENV_NAME < /dev/tty
        ENV_NAME=${ENV_NAME:-$DEFAULT_ENV_NAME}
    else
        info "Using active environment: $ENV_NAME"
    fi
    
    ENV_DIR="environments/$ENV_NAME"
    TFVARS_FILE_PATH="$REPO_ROOT/infrastructure/$ENV_DIR/terraform.tfvars"
    STATE_FILE="$REPO_ROOT/infrastructure/$ENV_DIR/.deploy_state"
    read_state

    if [ ! -d "$ENV_DIR" ]; then
        info "Creating new environment folder from template: $TEMPLATE_ENV_DIR"
        cp -r "$TEMPLATE_ENV_DIR" "$ENV_DIR"
        
        prompt "Do you have an existing GCS bucket for Terraform state? (y/n)"
        read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            prompt "Please enter GCS bucket name:"
            read -p "   Bucket Name: " BUCKET_NAME < /dev/tty
        else
            BUCKET_SUFFIX=$(printf "$GCS_BUCKET_SUFFIX_FORMAT" "$ENV_NAME")
            BUCKET_NAME="${GCP_PROJECT_ID}-${BUCKET_SUFFIX}"
            info "Creating GCS bucket '$BUCKET_NAME' for state..."
            gsutil mb -p "$GCP_PROJECT_ID" "gs://${BUCKET_NAME}" || warn "Bucket may already exist. Continuing..."
        fi
        
        BUCKET_PREFIX=$(printf "$GCS_BUCKET_PREFIX_FORMAT" "$ENV_NAME")
        info "Updating backend.tfvars with: $BUCKET_PREFIX"
        echo -e "bucket = \"$BUCKET_NAME\"\nprefix = \"$BUCKET_PREFIX\"" > "$ENV_DIR/backend.tfvars"
        
        # Populate tfvars file
        info "Configuring terraform.tfvars..."
        sed -i.bak "s|^[#[:space:]]*project_id[[:space:]]*=.*|project_id = \"$GCP_PROJECT_ID\"|g" "$TFVARS_FILE_PATH"
        sed -i.bak "s|^[#[:space:]]*environment[[:space:]]*=.*|environment = \"$ENV_NAME\"|g" "$TFVARS_FILE_PATH"

        # Ensure the target version is passed to Terraform
        if grep -q "app_version" "$TFVARS_FILE_PATH"; then
            sed -i.bak "s|^[#[:space:]]*app_version[[:space:]]*=.*|app_version = \"$TARGET_VERSION\"|g" "$TFVARS_FILE_PATH" && rm -f "${TFVARS_FILE_PATH}.bak"
        else
            echo -e "\napp_version = \"$TARGET_VERSION\"" >> "$TFVARS_FILE_PATH"
        fi
        
        prompt_and_update_tfvar "Region to deploy resources into" "us-central1" "region" "DEPLOY_REGION"
        prompt_and_update_tfvar "Resource naming prefix" "cs" "resource_prefix" "RES_PREFIX"
        prompt_and_update_tfvar "Custom domain name (Load Balancer SSL)" "${GCP_PROJECT_ID}.example.com" "domain_name" "LB_DOMAIN"
        
        # Discover and Set Firebase Site ID
        configure_firebase_site_id "$TFVARS_FILE_PATH" "$GCP_PROJECT_ID"
        AUTO_FIREBASE_SITE_ID=$(grep 'firebase_site_id' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')

        write_state "ENV_NAME" "$ENV_NAME"
        write_state "DEPLOY_REGION" "$DEPLOY_REGION"
        write_state "RES_PREFIX" "$RES_PREFIX"
        write_state "LB_DOMAIN" "$LB_DOMAIN"
        write_state "AUTO_FIREBASE_SITE_ID" "$AUTO_FIREBASE_SITE_ID"
    else
        info "Environment '$ENV_NAME' directory already exists."
    fi
    success "Configuration files for environment '$ENV_NAME' are ready."
}

handle_manual_steps() {
    step 6 "Enabling Google APIs & Accepting Terms"
    cd "$REPO_ROOT/infrastructure"
    info "Enabling required GCP Service APIs..."
    gcloud services enable \
        cloudbuild.googleapis.com \
        secretmanager.googleapis.com \
        firebase.googleapis.com \
        iap.googleapis.com \
        identitytoolkit.googleapis.com \
        texttospeech.googleapis.com \
        workflows.googleapis.com \
        sqladmin.googleapis.com \
        compute.googleapis.com \
        vpcaccess.googleapis.com \
        --project="$GCP_PROJECT_ID"

    warn "\nTerraform cannot accept Google legal terms on your behalf."
    info "Please guarantee Firebase integration manually:"
    echo "1. Open URL in browser: ${C_YELLOW}https://console.firebase.google.com/?project=${GCP_PROJECT_ID}${C_RESET}"
    echo "2. Confirm linking/adding Firebase to your project."
    echo "3. Accept terms."
    prompt "Press [Enter] after Firebase has been successfully linked..."
    read -r < /dev/tty
}

setup_firebase_app() {
    step 7 "Configuring Firebase Web Application"
    cd "$REPO_ROOT"
    info "Checking for existing Firebase Web App '$FE_SERVICE_NAME'..."
    if ! firebase apps:list --project="$GCP_PROJECT_ID" | grep -q "$FE_SERVICE_NAME"; then
        info "Creating web app inside Firebase..."
        firebase apps:create WEB "$FE_SERVICE_NAME" --project="$GCP_PROJECT_ID"
    else
        info "Firebase Web App already registered."
    fi

    info "Querying Web App SDK config metadata..."
    local APP_ID=$(firebase apps:list --project="$GCP_PROJECT_ID" --json | jq -r --arg name "$FE_SERVICE_NAME" '.result[] | select(.displayName == $name) | .appId')
    local SDK_CONFIG_JSON=$(firebase apps:sdkconfig WEB "$APP_ID" --project="$GCP_PROJECT_ID" --json)

    AUTO_FIREBASE_API_KEY=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.apiKey // empty')
    AUTO_FIREBASE_AUTH_DOMAIN=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.authDomain // empty')
    AUTO_FIREBASE_PROJECT_ID=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.projectId // empty')
    AUTO_FIREBASE_STORAGE_BUCKET=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.storageBucket // empty')
    AUTO_FIREBASE_MESSAGING_SENDER_ID=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.messagingSenderId // empty')
    AUTO_FIREBASE_APP_ID=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.appId // empty')
    AUTO_FIREBASE_MEASUREMENT_ID=$(echo "$SDK_CONFIG_JSON" | jq -r '.result.sdkConfig.measurementId // empty')

    if [ -z "$AUTO_FIREBASE_API_KEY" ]; then 
        fail "Failed to query Firebase credentials automatically. Verify Firebase project Console settings."
    fi
    success "Firebase configuration details successfully discovered."
}

populate_oauth_secrets() {
    step 8 "Configuring OAuth Web Client ID"
    cd "$REPO_ROOT"
    info "Resolving Google Client ID for secure frontend/backend token transactions..."
    
    local APP_ID=$(firebase apps:list --project="$GCP_PROJECT_ID" --json | jq -r --arg name "$FE_SERVICE_NAME" '.result[] | select(.displayName == $name) | .appId')
    local AUTH_TOKEN=$(gcloud auth print-access-token)
    local API_RESPONSE=$(curl -s -X GET -H "Authorization: Bearer $AUTH_TOKEN" "https://firebase.googleapis.com/v1beta1/projects/$GCP_PROJECT_ID/webApps/$APP_ID/config")
    AUTO_OAUTH_CLIENT_ID=$(echo "$API_RESPONSE" | jq -r '.oauthClientId // empty')

    if [ -z "$AUTO_OAUTH_CLIENT_ID" ] || [ "$AUTO_OAUTH_CLIENT_ID" == "null" ]; then
        warn "Could not resolve OAuth client ID via APIs automatically."
        echo "1. Open URL in browser: ${C_YELLOW}https://console.cloud.google.com/apis/credentials?project=${GCP_PROJECT_ID}${C_RESET}"
        echo "2. Locate the Web Application client under 'OAuth 2.0 Client IDs'."
        prompt "Paste the OAuth 2.0 Client ID here:"
        read -p "   Client ID: " AUTO_OAUTH_CLIENT_ID < /dev/tty
        if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then fail "OAuth Client ID is required."; fi
    fi

    info "Writing client ID secrets directly to Google Secret Manager..."
    # Ensure standard secret names exist before adding versions (handled by Terraform, but we seed placeholders)
    if ! gcloud secrets describe GOOGLE_CLIENT_ID --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
        gcloud secrets create GOOGLE_CLIENT_ID --replication-policy="automatic" --project="$GCP_PROJECT_ID"
    fi
    if ! gcloud secrets describe GOOGLE_TOKEN_AUDIENCE --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
        gcloud secrets create GOOGLE_TOKEN_AUDIENCE --replication-policy="automatic" --project="$GCP_PROJECT_ID"
    fi
    
    echo -n "$AUTO_OAUTH_CLIENT_ID" | gcloud secrets versions add GOOGLE_CLIENT_ID --data-file="-" --project="$GCP_PROJECT_ID" --quiet
    echo -n "$AUTO_OAUTH_CLIENT_ID" | gcloud secrets versions add GOOGLE_TOKEN_AUDIENCE --data-file="-" --project="$GCP_PROJECT_ID" --quiet
    success "Secure OAuth environment bindings successfully populated."
}

run_terraform() {
    step 9 "Provisioning Google Cloud Infrastructure via Terraform"
    cd "$REPO_ROOT/infrastructure"
    ENV_DIR="environments/$ENV_NAME"
    
    info "Initializing Terraform with GCS Backend State config: $ENV_DIR/backend.tfvars..."
    terraform init -reconfigure -backend-config="$ENV_DIR/backend.tfvars"
    
    info "Running Terraform Plan..."
    terraform plan -var-file="$ENV_DIR/terraform.tfvars"
    
    prompt "\nReady to apply state modifications. Provision resources? (y/n)"
    read -r REPLY < /dev/tty
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then fail "Deployment halted by user."; fi
    
    info "Applying infrastructure deployment configuration..."
    terraform apply -auto-approve -var-file="$ENV_DIR/terraform.tfvars"
    success "Infrastructure provisioned successfully."
}

build_and_deploy_frontend() {
    step 10 "Compiling & Deploying Frontend App (Dynamic Config)"
    cd "$REPO_ROOT/frontend"
    
    info "Restoring backup of firebase.json if present..."
    [ -f "firebase.json.bak" ] && cp "firebase.json.bak" "firebase.json"

    # Resolve dynamic values from Terraform outputs
    info "Extracting deployed routing links from infrastructure..."
    cd "$REPO_ROOT/infrastructure"
    local BACKEND_URL=$(terraform output -raw backend_service_url 2>/dev/null || echo "")
    local BACKEND_SERVICE_NAME=$(terraform output -raw service_name 2>/dev/null || echo "")
    
    if [ -z "$BACKEND_URL" ] || [ -z "$BACKEND_SERVICE_NAME" ]; then
        fail "Failed to query backend outputs from Terraform. Ensure Terraform apply was complete and outputs exist."
    fi

    info "Discovered backend URL: $BACKEND_URL"
    info "Discovered backend name: $BACKEND_SERVICE_NAME"
    
    cd "$REPO_ROOT/frontend"
    info "Replacing template parameters inside firebase.json config..."
    cp "firebase.json" "firebase.json.bak"
    sed -i "s|SITE_ID_PLACEHOLDER|${AUTO_FIREBASE_SITE_ID}|g" firebase.json
    sed -i "s|BACKEND_SERVICE_ID_PLACEHOLDER|${BACKEND_SERVICE_NAME}|g" firebase.json

    # 1. Standard package installation
    info "Installing frontend npm packages..."
    npm ci
    
    # 2. Compile static web bundle
    info "Executing generic Angular production build..."
    npm run build -- --configuration=production
    
    # 3. Create the client runtime config.json file dynamically inside browser assets
    info "Generating dynamic assets/config.json runtime config..."
    local CONFIG_PATH="dist/creative-studio/browser/assets/config.json"
    mkdir -p "dist/creative-studio/browser/assets"
    
    jq -n \
        --argjson production true \
        --argjson isLocal false \
        --arg backendURL "${BACKEND_URL}" \
        --arg googleClientId "$AUTO_OAUTH_CLIENT_ID" \
        --arg apiKey "$AUTO_FIREBASE_API_KEY" \
        --arg authDomain "$AUTO_FIREBASE_AUTH_DOMAIN" \
        --arg projectId "$AUTO_FIREBASE_PROJECT_ID" \
        --arg storageBucket "$AUTO_FIREBASE_STORAGE_BUCKET" \
        --arg messagingSenderId "$AUTO_FIREBASE_MESSAGING_SENDER_ID" \
        --arg appId "$AUTO_FIREBASE_APP_ID" \
        --arg measurementId "$AUTO_FIREBASE_MEASUREMENT_ID" \
        '{
            production: $production,
            isLocal: $isLocal,
            backendURL: ($backendURL + "/api"),
            GOOGLE_CLIENT_ID: $googleClientId,
            firebase: {
                apiKey: $apiKey,
                authDomain: $authDomain,
                projectId: $projectId,
                storageBucket: $storageBucket,
                messagingSenderId: $messagingSenderId,
                appId: $appId,
                measurementId: $measurementId
            }
        }' > "$CONFIG_PATH"

    # 4. Deploy SPA statically to Firebase hosting site
    info "Deploying static assets to Firebase Hosting site: ${AUTO_FIREBASE_SITE_ID}..."
    npx firebase deploy --project="$GCP_PROJECT_ID" --only="hosting:${AUTO_FIREBASE_SITE_ID}" --non-interactive
    
    # Restore original firebase.json
    mv "firebase.json.bak" "firebase.json"
    success "Frontend built, dynamic client configuration created, and deployed."
}

seed_database() {
    step 11 "Executing Database Migrations & Initial Seeding"
    cd "$REPO_ROOT/infrastructure"

    # 1. Fetch secure outputs from Terraform
    info "Resolving secure database credentials..."
    local DB_CONN_NAME=$(terraform output -raw cloud_sql_connection_name 2>/dev/null || echo "")
    local DB_NAME=$(terraform output -raw db_name 2>/dev/null || echo "")
    local DB_USER=$(terraform output -raw db_user 2>/dev/null || echo "")
    local DB_PASS_SECRET=$(terraform output -raw db_secret_id 2>/dev/null || echo "")
    local SUBNET_NAME=$(terraform output -raw cloud_run_subnet_name 2>/dev/null || echo "")
    
    if [ -z "$DB_CONN_NAME" ] || [ -z "$DB_PASS_SECRET" ] || [ -z "$SUBNET_NAME" ]; then
        fail "Could not query network or database outputs. Verify Terraform apply ran successfully."
    fi

    # 2. Deduce dynamic billing proxy registry image URL
    local STABLE_IMAGE="${DEPLOY_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${RES_PREFIX}-${ENV_NAME}-ghcr-proxy/GoogleCloudPlatform/gcc-creative-studio/backend:latest"
    info "Target secure runtime image: ${C_YELLOW}${STABLE_IMAGE}${C_RESET}"
    
    info "Database: ${DB_CONN_NAME}"
    info "Subnetwork Egress: ${SUBNET_NAME}"

    local CURRENT_USER=$(gcloud config get-value account 2>/dev/null || echo "system")
    local BUCKET_ASSETS="${GCP_PROJECT_ID}-cs-${ENV_NAME}-bucket"

    # 3. Create a secure, temporary Google Cloud Run Job inside the VPC boundary
    info "Registering secure administrative Job..."
    
    # Delete temporary job if it exists from previous crashed runs
    gcloud run jobs delete temp-db-bootstrap-job --region="$DEPLOY_REGION" --project="$GCP_PROJECT_ID" --quiet >/dev/null 2>&1 || true

    gcloud run jobs create temp-db-bootstrap-job \
        --image="$STABLE_IMAGE" \
        --region="$DEPLOY_REGION" \
        --subnet="$SUBNET_NAME" \
        --command="python" \
        --args="-m,bootstrap.bootstrap" \
        --add-cloudsql-instances="$DB_CONN_NAME" \
        --set-env-vars="INSTANCE_CONNECTION_NAME=${DB_CONN_NAME},DB_HOST=/cloudsql/${DB_CONN_NAME},DB_NAME=${DB_NAME},DB_USER=${DB_USER},USE_CLOUD_SQL_AUTH_PROXY=true,PROJECT_ID=${GCP_PROJECT_ID},GENMEDIA_BUCKET=${BUCKET_ASSETS},ADMIN_USER_EMAIL=${CURRENT_USER},ENVIRONMENT=development" \
        --set-secrets="DB_PASS=${DB_PASS_SECRET}:latest" \
        --project="$GCP_PROJECT_ID" \
        --quiet

    # 4. Trigger Job execution serverless and wait for completion
    info "Triggering migration and seeding execution in Cloud Run Job..."
    if gcloud run jobs execute temp-db-bootstrap-job --region="$DEPLOY_REGION" --project="$GCP_PROJECT_ID" --wait --quiet; then
        success "Database migrations and initial database data seeding executed successfully!"
    else
        warn "Database seeding failed. Retrying in background or check logs inside Cloud Run Job console."
        gcloud run jobs delete temp-db-bootstrap-job --region="$DEPLOY_REGION" --project="$GCP_PROJECT_ID" --quiet >/dev/null 2>&1 || true
        fail "Database initialization aborted due to seeding job error."
    fi

    # 5. Clean up administrative Job
    info "Cleaning up temporary seeding job..."
    gcloud run jobs delete temp-db-bootstrap-job --region="$DEPLOY_REGION" --project="$GCP_PROJECT_ID" --quiet
    success "Temporary serverless seeding infrastructure securely dismantled."
}

# --- Main Execution ---
main() {
    echo -e "${C_GREEN}============================================================${C_RESET}"
    echo -e "${C_GREEN}  🚀 Creative Studio Enterprise Deployer (Secure SPA) 🚀   ${C_RESET}"
    echo -e "${C_GREEN}============================================================${C_RESET}"

    check_prerequisites
    check_and_install_terraform
    setup_project
    setup_repo
    configure_environment
    handle_manual_steps
    setup_firebase_app
    populate_oauth_secrets
    run_terraform
    build_and_deploy_frontend
    seed_database

    step 12 "🎉 Deployment Completed Successfully! 🎉"
    
    cd "$REPO_ROOT/infrastructure"
    local FRONTEND_URL=$(terraform output -raw frontend_service_url 2>/dev/null || echo "")
    if [ -z "$FRONTEND_URL" ] || [ "$FRONTEND_URL" == "null" ]; then
        if [ -n "$AUTO_FIREBASE_SITE_ID" ]; then
            FRONTEND_URL="https://${AUTO_FIREBASE_SITE_ID}.web.app"
        else
            FRONTEND_URL="https://${GCP_PROJECT_ID}.web.app"
        fi
    fi
    local BACKEND_URL=$(terraform output -raw backend_service_url 2>/dev/null || echo "")

    echo "------------------------------------------------------------------"
    echo -e "   Frontend Portal URL:  ${C_YELLOW}${FRONTEND_URL}${C_RESET}"
    echo -e "   Backend API Endpoint: ${C_YELLOW}${BACKEND_URL}${C_RESET}"
    echo "------------------------------------------------------------------"
    info "The application services are secure, live, and fully operational."
    echo -e "${C_GREEN}============================================================${C_RESET}"
}

main "$@"
