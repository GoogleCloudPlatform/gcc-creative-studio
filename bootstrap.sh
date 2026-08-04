#!/bin/bash
# Copyright 2025 Google LLC
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


# ==============================================================================
# Creative Studio Infrastructure Bootstrap Script (Resumable)
#
# This interactive script guides a user through the entire process of setting
# up the Creative Studio infrastructure in a new or existing Google Cloud project.
# It saves progress and can be safely restarted if it fails.
# ==============================================================================

set -e

# --- Configuration ---
REQUIRED_TERRAFORM_VERSION="1.14.1"
UPSTREAM_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio"
TEMPLATE_ENV_DIR="environments/dev-infra-example"
DEFAULT_ENV_NAME="dev-infra"
DEFAULT_BRANCH_NAME="main"
GCS_BUCKET_SUFFIX_FORMAT="cstudio-%s-tfstate"
GCS_BUCKET_PREFIX_FORMAT="infra/%s/state"
BE_SERVICE_NAME="cstudio-be"
FE_SERVICE_NAME="cstudio-fe"

# script will automatically set these
AUTO_FIREBASE_API_KEY=""           # Your Firebase Web API Key
AUTO_FIREBASE_AUTH_DOMAIN=""       # Your Firebase Auth Domain (e.g., project-id.firebaseapp.com)
AUTO_FIREBASE_PROJECT_ID=""        # Your Firebase Project ID
AUTO_FIREBASE_STORAGE_BUCKET=""    # Your Firebase Storage Bucket (e.g., project-id.appspot.com)
AUTO_FIREBASE_MESSAGING_SENDER_ID="" # Your Firebase Cloud Messaging Sender ID
AUTO_FIREBASE_APP_ID=""            # Your Firebase Web App ID
AUTO_FIREBASE_MEASUREMENT_ID=""    # Your Google Analytics Measurement ID
AUTO_OAUTH_CLIENT_ID=""
AUTO_FIREBASE_SITE_ID=""           # The discovered Firebase Hosting Site ID

STATE_FILE=""
REPO_ROOT=""

# --- Color Definitions (High Contrast) ---
C_RESET='\033[0m'
C_RED='\033[1;31m'     # Bold/Bright Red for errors
C_GREEN='\033[1;32m'   # Bold/Bright Green for success
C_YELLOW='\033[1;33m'  # Bold/Bright Yellow for warnings and URLs
C_BLUE='\033[1;34m'    # Bold/Bright Blue for steps and prompts
C_CYAN='\033[1;36m'    # Bold/Bright Cyan for general info

# --- Helper Functions ---
info() { echo -e "${C_CYAN}➡️  $1${C_RESET}"; }
prompt() { echo -e "${C_BLUE}🤔  $1${C_RESET}"; }
warn() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
fail() { echo -e "${C_RED}❌  $1${C_RESET}" >&2; exit 1; }
success() { echo -e "${C_GREEN}✅  $1${C_RESET}"; }
step() { echo -e "\n${C_BLUE}--- Step $1: $2 ---${C_RESET}"; }

# --- Pre-flight Checks & Auto-configuration ---

# Function to automatically determine and set the Firebase Site ID in the .tfvars file
configure_firebase_site_id() {
  info "Checking Firebase Hosting Site configuration..."
  local tfvars_file=$1
  local project_id=$2

  # Check if the site ID is still the placeholder value
  if grep -q "YOUR_FIREBASE_SITE_ID" "$tfvars_file"; then
    warn "Placeholder 'YOUR_FIREBASE_SITE_ID' found in ${tfvars_file}."
    if [ -n "$AUTO_FIREBASE_SITE_ID" ] && [ "$AUTO_FIREBASE_SITE_ID" != "null" ]; then
      info "Using confirmed Firebase Hosting Site ID from deployment profile: ${C_YELLOW}${AUTO_FIREBASE_SITE_ID}${C_RESET}"
      sed -i.bak "s/YOUR_FIREBASE_SITE_ID/${AUTO_FIREBASE_SITE_ID}/" "$tfvars_file" && rm -f "${tfvars_file}.bak"
      return
    fi
    info "Querying Firebase for an existing default hosting site..."

    # Query Firebase for sites and find the one marked as default (or the first one if none are default)
    local default_site_name
    # The `jq` filter first looks for a site with type "DEFAULT_SITE". If not found, it takes the first site in the list.
    # The result is the full resource name, e.g., "projects/my-proj/sites/my-site-id".
    default_site_name=$( (firebase hosting:sites:list --project "$project_id" --json 2>/dev/null || echo "{}") | jq -r 'try ((.result.sites // []) | (map(select(.type == "DEFAULT_SITE"))[0].name // .[0].name // "")) catch ""' 2>/dev/null || echo "" )

    # If a site was found, extract the site ID from the name. Otherwise, fall back to the project ID.
    local site_id_to_use=$project_id
    [ -n "$default_site_name" ] && site_id_to_use=$(basename "$default_site_name")

    info "Setting 'firebase_site_id' to '${C_YELLOW}${site_id_to_use}${C_RESET}' in ${tfvars_file}."
    sed -i.bak "s/YOUR_FIREBASE_SITE_ID/${site_id_to_use}/" "$tfvars_file" && rm "${tfvars_file}.bak"
    AUTO_FIREBASE_SITE_ID="$site_id_to_use"
    write_state "AUTO_FIREBASE_SITE_ID" "$AUTO_FIREBASE_SITE_ID"
  fi
}


# A reusable function to prompt for a value and update the .tfvars file
prompt_and_update_tfvar() {
    local prompt_text=$1
    local default_value=$2
    local tfvar_name=$3
    local var_to_set_ref=$4

    read -p "   $prompt_text [default value: $default_value]: " user_input < /dev/tty
    local final_value=${user_input:-$default_value}

	sed -i.bak "s|^[#[:space:]]*${tfvar_name}[[:space:]]*=.*|${tfvar_name} = \"${final_value}\"|g" "$TFVARS_FILE_PATH"

    # Set the variable in the script's global scope
    eval "$var_to_set_ref='$final_value'"
}

# --- State Management ---
write_state() {
    if [ -z "$STATE_FILE" ]; then return; fi
    if ! (
        mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
        touch "$STATE_FILE"
        TMP_STATE_FILE=$(mktemp)
        grep -v "^$1=" "$STATE_FILE" > "$TMP_STATE_FILE" || true
        echo "$1=$2" >> "$TMP_STATE_FILE"
        mv "$TMP_STATE_FILE" "$STATE_FILE"
    ); then
        warn "Could not write to state file: $STATE_FILE. Resuming will not be possible from this point."
    fi
}
read_state() {
    if [ -f "$STATE_FILE" ]; then
        info "Found previous state file. Resuming..."
        set -a; source "$STATE_FILE"; set +a
    fi
}

# --- Script Functions ---
check_prerequisites() {
    step 1 "Checking Prerequisites"
    command -v gcloud >/dev/null || fail "gcloud CLI not found. Please install from https://cloud.google.com/sdk/docs/install"
    command -v git >/dev/null || fail "git not found. Please install it."
    if ! command -v jq &> /dev/null; then
        warn "The 'jq' command is required but not found."
        prompt "Would you like to try and install it now? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            warn "This may require sudo privileges."
			if command -v apt-get &>/dev/null; then sudo apt-get update && sudo apt-get install -y jq
			elif command -v brew &>/dev/null; then brew install jq
			elif command -v yum &>/dev/null; then sudo yum install -y jq
			else fail "Cannot automatically install jq on this OS. Please install it manually and run again."
			fi
        else fail "Please install jq and run this script again.";
		fi
    fi
    if ! command -v firebase &> /dev/null; then
        warn "Firebase CLI ('firebase-tools') is not installed. It is required for automation."
        prompt "Would you like to try and install it now via npm? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! command -v npm &> /dev/null; then fail "npm is required to install firebase-tools. Please install Node.js and npm first."; fi
            info "Installing firebase-tools globally..."; sudo npm install -g firebase-tools
        else
            fail "Please install firebase-tools (npm install -g firebase-tools) and run this script again."
        fi
    fi
    check_and_install_uv
    success "Prerequisites met. gcloud, git, jq, firebase and uv"
}

check_and_install_uv() {
    if command -v uv >/dev/null; then
        info "uv is already installed."
        return
    fi
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
}

get_platform_arch() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case $ARCH in
        x86_64) ARCH="amd64" ;; aarch64) ARCH="arm64" ;; arm64) ARCH="arm64" ;;
    esac
    echo "${OS}_${ARCH}"
}

check_and_install_terraform() {
    step 2 "Checking Terraform Installation"
    if ! command -v terraform &> /dev/null; then
        warn "Terraform is not installed."
        install_terraform
        return
    fi
    INSTALLED_VERSION=$( (terraform version -json 2>/dev/null || echo "{}") | jq -r 'try .terraform_version catch ""' 2>/dev/null || echo "" )
    if [[ "$(printf '%s\n' "$REQUIRED_TERRAFORM_VERSION" "$INSTALLED_VERSION" | sort -V | head -n1)" != "$REQUIRED_TERRAFORM_VERSION" ]]; then
        warn "Your Terraform version ($INSTALLED_VERSION) is older than the required version ($REQUIRED_TERRAFORM_VERSION)."
        install_terraform
    else
        success "Terraform version $INSTALLED_VERSION is sufficient."
    fi
}

install_terraform() {
    warn "Terraform is missing or outdated. The required version ($REQUIRED_TERRAFORM_VERSION) will be installed now."
    PLATFORM_ARCH=$(get_platform_arch)
    TF_ZIP_FILENAME="terraform_${REQUIRED_TERRAFORM_VERSION}_${PLATFORM_ARCH}.zip"
    TF_DOWNLOAD_URL="https://releases.hashicorp.com/terraform/${REQUIRED_TERRAFORM_VERSION}/${TF_ZIP_FILENAME}"
    info "Downloading Terraform for your platform (${PLATFORM_ARCH})..."
    curl -Lo terraform.zip "$TF_DOWNLOAD_URL"
    unzip -o terraform.zip
    info "Installing Terraform into the persistent ~/bin directory..."
    mkdir -p "$HOME/bin"
    mv terraform "$HOME/bin/"
    if ! grep -q 'export PATH="$HOME/bin:$PATH"' ~/.bashrc; then
        info "Adding ~/bin to your PATH in ~/.bashrc for future sessions..."
        echo -e '\n# Add local bin to PATH\nexport PATH="$HOME/bin:$PATH"' >> ~/.bashrc
    fi
    export PATH="$HOME/bin:$PATH"
    hash -r
    rm terraform.zip LICENSE.txt
    if command -v terraform &> /dev/null && [[ "$( (terraform version -json 2>/dev/null || echo "{}") | jq -r 'try .terraform_version catch ""' 2>/dev/null || echo "" )" == "$REQUIRED_TERRAFORM_VERSION" ]]; then
        success "Terraform v$(terraform -version | head -n 1) is now active."
    else
        fail "Terraform installation failed. Please open a new terminal and run this script again."
    fi
}

setup_project() {
    step 3 "Configuring Google Cloud Project"

    # try detecting current project on the current terminal
    CURRENT_GCLOUD_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")

    if [ -n "$GCP_PROJECT_ID" ] && [ "$GCP_PROJECT_ID" != "unassigned" ]; then
        info "Using Google Cloud Project ID from confirmed profile: ${C_YELLOW}${GCP_PROJECT_ID}${C_RESET}"
        gcloud config set project "$GCP_PROJECT_ID" 2>/dev/null || true
        write_state "GCP_PROJECT_ID" "$GCP_PROJECT_ID"
        success "Project '$GCP_PROJECT_ID' is configured."
        return 0
    elif [ -n "$CURRENT_GCLOUD_PROJECT" ]; then
        prompt "Detected active gcloud project '$CURRENT_GCLOUD_PROJECT'. Use this project? (y/n)"
        read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            GCP_PROJECT_ID=$CURRENT_GCLOUD_PROJECT
            info "Using existing project '$GCP_PROJECT_ID'."
            gcloud config set project "$GCP_PROJECT_ID"
            write_state "GCP_PROJECT_ID" "$GCP_PROJECT_ID"
            success "Project '$GCP_PROJECT_ID' is configured."
            return
        fi
    fi
    prompt "Do you already have a Google Cloud Project to use? (y/n)"; read -r REPLY < /dev/tty
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        prompt "Please enter your existing Google Cloud Project ID:"; read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
    else
        prompt "What is the desired new Google Cloud Project ID? (e.g., my-creative-studio)"; read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
        prompt "What is your Google Cloud Billing Account ID? (Find it with 'gcloud beta billing accounts list')"; read -p "   Billing Account ID: " BILLING_ACCOUNT_ID < /dev/tty
        info "Creating project '$GCP_PROJECT_ID'..."; gcloud projects create "$GCP_PROJECT_ID" || warn "Project '$GCP_PROJECT_ID' may already exist. Continuing..."
        info "Linking billing account '$BILLING_ACCOUNT_ID'..."; gcloud beta billing projects link "$GCP_PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
    fi
    info "Setting gcloud config to use project '$GCP_PROJECT_ID'..."; gcloud config set project "$GCP_PROJECT_ID"
    write_state "GCP_PROJECT_ID" "$GCP_PROJECT_ID"
    success "Project '$GCP_PROJECT_ID' is configured."
}

setup_repo() {
    step 4 "Configuring Git Repository"

    if [ -n "$GITHUB_REPO_URL" ] && [ "$GITHUB_REPO_URL" != "unassigned" ]; then
        info "Using stored repository URL from profile: ${C_YELLOW}${GITHUB_REPO_URL}${C_RESET}"
    else
        # Since the script is run via curl, it never starts inside a repo. We must clone it.
        warn "Please fork the main repository first: ${UPSTREAM_REPO_URL}/fork"
        while true; do
            prompt "What is the git URL of YOUR forked repository? (e.g., https://github.com/user/repo.git)"
            read -p "   Git URL: " GITHUB_REPO_URL < /dev/tty
            if [ -z "$GITHUB_REPO_URL" ]; then warn "Repository URL cannot be empty."; continue; fi
            info "Validating repository URL..."
            if git ls-remote --exit-code -h "$GITHUB_REPO_URL" > /dev/null 2>&1; then
                success "Repository found."; break
            else warn "Repository not found at that URL. Please check for typos and try again."; fi
        done
        write_state "GITHUB_REPO_URL" "$GITHUB_REPO_URL"
    fi

    # --- Ask for Branch ---
    if [ -n "$GITHUB_BRANCH" ] && [ "$GITHUB_BRANCH" != "unassigned" ]; then
        SELECTED_BRANCH="$GITHUB_BRANCH"
        info "Using stored Git branch from profile: ${C_YELLOW}${SELECTED_BRANCH}${C_RESET}"
    else
        prompt "Which git branch would you like to use? (default: main)"
        read -p "   Branch Name: " SELECTED_BRANCH < /dev/tty
        SELECTED_BRANCH=${SELECTED_BRANCH:-main}
        GITHUB_BRANCH="$SELECTED_BRANCH"
        write_state "GITHUB_BRANCH" "$GITHUB_BRANCH"
    fi
    DEFAULT_BRANCH_NAME="$SELECTED_BRANCH"

    if [ -d "infrastructure" ] && [ -f "bootstrap.sh" ] && [ -d "backend" ] && [ -d "frontend" ]; then
        info "Currently executing inside active repository root $(pwd). Bypassing sparse git clone..."
        REPO_ROOT=$(pwd)
        export REPO_ROOT
        write_state "REPO_ROOT" "$REPO_ROOT"
        success "Project root successfully verified at: $REPO_ROOT"
        GITHUB_REPO_OWNER=$(git remote get-url origin 2>/dev/null | sed -n 's/.*github.com[:\/]\([^/]*\)\/.*/\1/p' || echo "GoogleCloudPlatform")
        GITHUB_REPO_NAME=$(basename "$(pwd)" .git)
        info "Detected GitHub owner: $GITHUB_REPO_OWNER"
        info "Detected GitHub repo name: $GITHUB_REPO_NAME"
        return 0
    fi

    local REPO_CLONE_DIR=$(basename "$GITHUB_REPO_URL" .git)

    if [[ -d "$REPO_CLONE_DIR" ]]; then
        warn "Directory '$REPO_CLONE_DIR' already exists."
        if [ "$TF_AUTO_APPROVE" = "true" ]; then
            info "Auto-approve flag detected. Reusing existing repository directory '$REPO_CLONE_DIR'."
            REPLY="y"
        else
            prompt "Do you want to use this existing directory? (y/n)"; read -r REPLY < /dev/tty
        fi
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then fail "Please remove the directory or run the script from a different location."; fi
    else
        info "Performing a sparse checkout of '$REPO_CLONE_DIR' (Branch: $SELECTED_BRANCH)..."
        
        # 1. Clone with -b branch_name
        git clone --filter=blob:none --no-checkout --depth 1 --sparse -b "$SELECTED_BRANCH" "$GITHUB_REPO_URL" "$REPO_CLONE_DIR"
        
        cd "$REPO_CLONE_DIR"
        
        # 2. Sparse checkout for ROOT folders only
        git sparse-checkout set "infrastructure" "backend" "frontend" "bootstrap.sh"
        
        git checkout
        cd ..

        success "Repository cloned successfully."
    fi

    # --- Project Path Verification ---
    info "Verifying project structure..."

    # Check if the project is at the top level
    if [[ -d "$REPO_CLONE_DIR/infrastructure" && -f "$REPO_CLONE_DIR/bootstrap.sh" ]]; then
        info "Detected project structure."
    else
        warn "Directory listing of clone:"
        ls -F "$REPO_CLONE_DIR/"
        fail "Could not find a valid project structure. The script requires an 'infrastructure' directory and 'bootstrap.sh' file at the root."
    fi

    cd "$REPO_CLONE_DIR"

    REPO_ROOT=$(pwd)
    export REPO_ROOT
    write_state "REPO_ROOT" "$REPO_ROOT"
    success "Project root successfully set to: $REPO_ROOT"

    GITHUB_REPO_OWNER=$(git remote get-url origin 2>/dev/null | sed -n 's/.*github.com[:\/]\([^/]*\)\/.*/\1/p' || echo "")
    GITHUB_REPO_NAME=$REPO_CLONE_DIR

    info "Detected GitHub owner: $GITHUB_REPO_OWNER"
    info "Detected GitHub repo name: $GITHUB_REPO_NAME"
}

configure_environment() {
    step 5 "Configuring Terraform Environment";
    cd "$REPO_ROOT/infrastructure"
    if [ -z "$ENV_NAME" ]; then
        prompt "What would you like to call this deployment environment?"; read -p "   Environment Name [default value: $DEFAULT_ENV_NAME]: " ENV_NAME < /dev/tty
        ENV_NAME=${ENV_NAME:-$DEFAULT_ENV_NAME}
    else info "Using previously configured environment: $ENV_NAME"; fi
    # Use flattened structure directly under infrastructure/
    ENV_DIR="$REPO_ROOT/infrastructure"
    TFVARS_FILE_PATH="$ENV_DIR/$ENV_NAME.tfvars"
    if [ ! -s "$TFVARS_FILE_PATH" ] || ! grep -q "project_id[[:space:]]*=" "$TFVARS_FILE_PATH"; then
        info "Configuring environment files in flattened infrastructure directory..."
        if [ "$TF_AUTO_APPROVE" = "true" ]; then
            info "Auto-approve flag detected. Defaulting to creating a GCS storage bucket automatically."
            REPLY="n"
        else
            prompt "Do you have an existing GCS bucket for Terraform state? (y/n)"; read -r REPLY < /dev/tty
        fi
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            prompt "Please enter the name of your GCS bucket:"; read -p "   Bucket Name: " BUCKET_NAME < /dev/tty
        else
            BUCKET_SUFFIX=$(printf "$GCS_BUCKET_SUFFIX_FORMAT" "$ENV_NAME"); BUCKET_NAME="${GCP_PROJECT_ID}-${BUCKET_SUFFIX}"
            info "Creating GCS bucket '$BUCKET_NAME' for Terraform state..."; gsutil mb -p "$GCP_PROJECT_ID" "gs://${BUCKET_NAME}" || warn "Bucket 'gs://${BUCKET_NAME}' may already exist. Continuing..."
        fi
        BUCKET_PREFIX=$(printf "$GCS_BUCKET_PREFIX_FORMAT" "$ENV_NAME")
        info "Creating backend config file ${ENV_NAME}.backend.tfvars..."; echo -e "bucket = \"$BUCKET_NAME\"\nprefix = \"$BUCKET_PREFIX\"" > "$ENV_DIR/${ENV_NAME}.backend.tfvars"
        info "Creating or repairing $TFVARS_FILE_PATH with required root parameters..."
        cat <<EOF > "$TFVARS_FILE_PATH"
project_id       = "$GCP_PROJECT_ID"
region           = "us-central1"
environment      = "$ENV_NAME"
resource_prefix  = "cs"
firebase_site_id = "YOUR_FIREBASE_SITE_ID"
EOF
        info "Default service names will be '$BE_SERVICE_NAME' and '$FE_SERVICE_NAME'."
        write_state "ENV_NAME" "$ENV_NAME"; write_state "BE_SERVICE_NAME" "$BE_SERVICE_NAME"; write_state "FE_SERVICE_NAME" "$FE_SERVICE_NAME"; write_state "GITHUB_BRANCH" "$GITHUB_BRANCH"
    else info "Environment directory '$ENV_DIR' already configured."; fi
    success "Configuration files for '$ENV_NAME' environment are ready."
}

handle_manual_steps() {
    step 6 "Manual Steps Required"; cd "$REPO_ROOT/infrastructure"; TFVARS_FILE_PATH="$ENV_DIR/$ENV_NAME.tfvars"
    info "Enabling required Google Cloud APIs..."; gcloud services enable cloudbuild.googleapis.com secretmanager.googleapis.com firebase.googleapis.com iap.googleapis.com identitytoolkit.googleapis.com texttospeech.googleapis.com workflows.googleapis.com sqladmin.googleapis.com --project="$GCP_PROJECT_ID"
    if [ -z "$GITHUB_CONN_NAME" ]; then
        prompt "\nDo you already have a Cloud Build Host Connection for GitHub in this project? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then prompt "Please enter the existing connection name:"; read -p "   Connection Name: " GITHUB_CONN_NAME < /dev/tty
        else
            warn "You will now be guided to create a new GitHub connection."; info "Please perform the following manual steps:"
            echo "1. Open this URL in your browser:"; echo -e "   ${C_YELLOW}https://console.cloud.google.com/cloud-build/connections/create?project=${GCP_PROJECT_ID}${C_RESET}"
            echo "2. Select 'GitHub (Cloud Build GitHub App)' and click 'CONTINUE'."
            echo "3. Follow the prompts to authorize the app on your GitHub account."; 
            echo "4. Grant access to your forked repository: '${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}'."
            echo "5. After creating the connection, copy its name (e.g., 'gh-yourname-con')."
            prompt "Paste the new Cloud Build Connection Name here:"; read -p "   Connection Name: " GITHUB_CONN_NAME < /dev/tty
        fi
        sed -i.bak "s|^[#[:space:]]*github_conn_name[[:space:]]*=.*|github_conn_name = \"$GITHUB_CONN_NAME\"|g" "$TFVARS_FILE_PATH"
        write_state "GITHUB_CONN_NAME" "$GITHUB_CONN_NAME"
    fi
    warn "\nTerraform cannot accept legal terms on your behalf."; info "Please perform this one-time manual step for Firebase:"
    echo "1. Open this URL in your browser:"; echo -e "   ${C_YELLOW}https://console.firebase.google.com/?project=${GCP_PROJECT_ID}${C_RESET}"
    echo "2. You should be prompted to 'Add Firebase' to your existing project."; echo "3. Follow the prompts and accept the terms."
    if [ "$TF_AUTO_APPROVE" != "true" ]; then
        prompt "Press [Enter] to continue after you have linked the project."; read -r < /dev/tty
    else
        info "Auto-approve flag detected. Bypassing interactive pause for Firebase project linking."
    fi
    rm -f "$TFVARS_FILE_PATH.bak"

    # --- Automate .tfvars placeholder replacement ---
    info "\nConfiguring OAuth Client ID and Project ID in .tfvars file..."
    if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then
        warn "The OAuth Client ID is required for the .tfvars file."
        echo "1. Open this URL in your browser to find your OAuth Client ID:"
        echo -e "   ${C_YELLOW}https://console.cloud.google.com/apis/credentials?project=${GCP_PROJECT_ID}${C_RESET}"
        echo "2. Find the OAuth 2.0 Client ID of type 'Web application'."
        prompt "Paste the OAuth Client ID here:"
        read -p "   Client ID: " AUTO_OAUTH_CLIENT_ID < /dev/tty
        if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then fail "OAuth Client ID is required to proceed."; fi
        write_state "AUTO_OAUTH_CLIENT_ID" "$AUTO_OAUTH_CLIENT_ID"
    fi

    sed -i.bak "s|YOUR_OAUTH_WEB_CLIENT_ID_HERE|$AUTO_OAUTH_CLIENT_ID|g" "$TFVARS_FILE_PATH"
    sed -i.bak "s|YOUR_GCP_PROJECT_ID|$GCP_PROJECT_ID|g" "$TFVARS_FILE_PATH"
    success "Replaced placeholders in $TFVARS_FILE_PATH."
}

setup_firebase_app() {
    step 7 "Automating Firebase Web App Configuration"; cd "$REPO_ROOT"

    info "Checking for existing Firebase web app named '$FE_SERVICE_NAME'...";
    if ! firebase apps:list --project="$GCP_PROJECT_ID" | grep -q "$FE_SERVICE_NAME"; then
        info "No existing app found. Creating a new Firebase web app...";
		firebase apps:create WEB "$FE_SERVICE_NAME" --project="$GCP_PROJECT_ID"
    else info "Firebase web app '$FE_SERVICE_NAME' already exists."; fi

    info "Fetching Firebase SDK configuration to store in memory...";
	local APP_ID=$( (firebase apps:list --project="$GCP_PROJECT_ID" --json 2>/dev/null || echo "{}") | jq -r --arg name "$FE_SERVICE_NAME" 'try (.result[]? | select(.displayName == $name) | .appId) catch ""' 2>/dev/null || echo "" )
    local SDK_CONFIG_JSON=$(firebase apps:sdkconfig WEB "$APP_ID" --project="$GCP_PROJECT_ID" --json 2>/dev/null || echo "{}")

    AUTO_FIREBASE_API_KEY=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.apiKey // "") catch ""' 2>/dev/null || echo "" )
    AUTO_FIREBASE_AUTH_DOMAIN=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.authDomain // "") catch ""' 2>/dev/null || echo "" )
    AUTO_FIREBASE_PROJECT_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.projectId // "") catch ""' 2>/dev/null || echo "" )
    AUTO_FIREBASE_STORAGE_BUCKET=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.storageBucket // "") catch ""' 2>/dev/null || echo "" )
    AUTO_FIREBASE_MESSAGING_SENDER_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.messagingSenderId // "") catch ""' 2>/dev/null || echo "" )
    AUTO_FIREBASE_APP_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.appId // "") catch ""' 2>/dev/null || echo "" )
    AUTO_FIREBASE_MEASUREMENT_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.measurementId // "") catch ""' 2>/dev/null || echo "" )

    if [ -z "$AUTO_FIREBASE_API_KEY" ]; then fail "Could not automatically fetch Firebase API Key. Please check your Firebase setup."; fi
    
    info "Resolving Firebase Hosting Site ID for project '$GCP_PROJECT_ID'..."
    if [ -n "$AUTO_FIREBASE_SITE_ID" ] && [ "$AUTO_FIREBASE_SITE_ID" != "null" ] && [ "$AUTO_FIREBASE_SITE_ID" != "unassigned" ]; then
        info "Using confirmed Firebase Hosting Site ID from profile: ${C_YELLOW}${AUTO_FIREBASE_SITE_ID}${C_RESET}"
    else
        local default_site_name=$( (firebase hosting:sites:list --project "$GCP_PROJECT_ID" --json 2>/dev/null || echo "{}") | jq -r 'try ((.result.sites // []) | (map(select(.type == "DEFAULT_SITE"))[0].name // .[0].name // "")) catch ""' 2>/dev/null || echo "" )
        AUTO_FIREBASE_SITE_ID=$GCP_PROJECT_ID
        [ -n "$default_site_name" ] && AUTO_FIREBASE_SITE_ID=$(basename "$default_site_name")
        info "Discovered Firebase Hosting Site ID: ${C_YELLOW}${AUTO_FIREBASE_SITE_ID}${C_RESET}"
        write_state "AUTO_FIREBASE_SITE_ID" "$AUTO_FIREBASE_SITE_ID"
    fi

    local TFVARS_FILE_PATH="$REPO_ROOT/infrastructure/$ENV_NAME.tfvars"
    if [ -f "$TFVARS_FILE_PATH" ]; then
        sed -i.bak "s/YOUR_FIREBASE_SITE_ID/${AUTO_FIREBASE_SITE_ID}/" "$TFVARS_FILE_PATH" 2>/dev/null && rm -f "${TFVARS_FILE_PATH}.bak"
    fi
    
    success "Firebase secrets have been fetched and will be populated automatically after Terraform runs."
}

populate_oauth_secrets() {
    step 8 "Automating OAuth Secret Population"
    cd "$REPO_ROOT"
    
    if [ -n "$AUTO_OAUTH_CLIENT_ID" ] && [ "$AUTO_OAUTH_CLIENT_ID" != "null" ]; then
        info "Using confirmed OAuth Client ID from deployment profile: ${C_YELLOW}${AUTO_OAUTH_CLIENT_ID}${C_RESET}"
    else
        info "Looking for the OAuth 2.0 Web Client ID using the Firebase Management API..."

        local AUTH_TOKEN=$(gcloud auth print-access-token)
        local APP_ID=$( (firebase apps:list --project="$GCP_PROJECT_ID" --json 2>/dev/null || echo "{}") | jq -r --arg name "$FE_SERVICE_NAME" 'try (.result[]? | select(.displayName == $name) | .appId) catch ""' 2>/dev/null || echo "" )

        if [ -z "$APP_ID" ]; then
            warn "Could not find Firebase App ID for '$FE_SERVICE_NAME'. Skipping OAuth secret population."
            return
        fi

        # Use the Firebase Management API to get the auth config, which includes the client ID.
        local API_RESPONSE=$(curl -s -X GET \
            -H "Authorization: Bearer $AUTH_TOKEN" \
            "https://firebase.googleapis.com/v1beta1/projects/$GCP_PROJECT_ID/webApps/$APP_ID/config")

        # The client ID is the one NOT associated with the API key.
        AUTO_OAUTH_CLIENT_ID=$( (echo "$API_RESPONSE" 2>/dev/null || echo "{}") | jq -r 'try (.oauthClientId // "") catch ""' 2>/dev/null || echo "" )

        if [ -z "$AUTO_OAUTH_CLIENT_ID" ] || [ "$AUTO_OAUTH_CLIENT_ID" == "null" ]; then
            warn "Could not automatically find the OAuth Client ID via API."
            info "Please perform the following manual steps:"
            echo "1. Open this URL in your browser to find your OAuth Client ID:"
            echo -e "   ${C_YELLOW}https://console.cloud.google.com/apis/credentials?project=${GCP_PROJECT_ID}${C_RESET}"
            echo "2. Find the OAuth 2.0 Client ID of type 'Web application'."
            prompt "Paste the OAuth Client ID here:"
            read -p "   Client ID: " AUTO_OAUTH_CLIENT_ID < /dev/tty
            if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then
                fail "OAuth Client ID is required to proceed. Please restart the script."
            fi
        else
            info "Found OAuth Client ID via Firebase API."
        fi
        write_state "AUTO_OAUTH_CLIENT_ID" "$AUTO_OAUTH_CLIENT_ID"
    fi

    info "Populating secrets with Client ID: ${C_YELLOW}${AUTO_OAUTH_CLIENT_ID}${C_RESET}"
    echo -n "$AUTO_OAUTH_CLIENT_ID" | gcloud secrets versions add GOOGLE_CLIENT_ID --data-file="-" --project="$GCP_PROJECT_ID" --quiet
    echo -n "$AUTO_OAUTH_CLIENT_ID" | gcloud secrets versions add GOOGLE_TOKEN_AUDIENCE --data-file="-" --project="$GCP_PROJECT_ID" --quiet
    success "Secrets 'GOOGLE_CLIENT_ID' and 'GOOGLE_TOKEN_AUDIENCE' have been populated."

    info "Updating audiences in $TFVARS_FILE_PATH..."
    sed -i.bak "s|your-custom-audience.apps.googleusercontent.com|$AUTO_OAUTH_CLIENT_ID|g" "$TFVARS_FILE_PATH"
    rm -f "$TFVARS_FILE_PATH.bak"
    success "Audiences updated in .tfvars file."
}

setup_db_secrets() {
    step 9 "Configuring Database Secrets" # Renumber subsequent steps
    
    local SECRET_NAME="creative-studio-db-password"
    
    # 2. Check if the secret already exists
    if gcloud secrets describe "$SECRET_NAME" --project="$GCP_PROJECT_ID" > /dev/null 2>&1; then
        info "Secret '$SECRET_NAME' already exists. Skipping creation."
    else
        info "Creating new secret '$SECRET_NAME'..."
        
        # 3. Generate a secure random password (alphanumeric, no special chars that break URLs)
        # using openssl. We use base64 but strip non-alphanumeric chars to be safe for DB connection strings
        local DB_PASSWORD=$(openssl rand -base64 20 | tr -dc 'a-zA-Z0-9' | head -c 16)
        
        # 4. Create the secret and add the first version
        # We use printf to avoid trailing newlines
        printf "%s" "$DB_PASSWORD" | gcloud secrets create "$SECRET_NAME" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$GCP_PROJECT_ID" \
            --quiet

        success "Secret '$SECRET_NAME' created successfully."
    fi

    # 5. Configure Agent Engine Secrets
    local AGENT_TOKEN_SECRET="agent_engine_user_auth_token_key"
    if ! gcloud secrets describe "$AGENT_TOKEN_SECRET" --project="$GCP_PROJECT_ID" > /dev/null 2>&1; then
        info "Creating secret '$AGENT_TOKEN_SECRET' with generated auth token..."
        local AGENT_TOKEN=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
        printf "%s" "$AGENT_TOKEN" | gcloud secrets create "$AGENT_TOKEN_SECRET" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$GCP_PROJECT_ID" \
            --quiet
        success "Secret '$AGENT_TOKEN_SECRET' created."
    fi

    local AGENT_RES_SECRET="agent_engine_resource_name"
    if ! gcloud secrets describe "$AGENT_RES_SECRET" --project="$GCP_PROJECT_ID" > /dev/null 2>&1; then
        info "Creating empty secret shell '$AGENT_RES_SECRET'..."
        printf "" | gcloud secrets create "$AGENT_RES_SECRET" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$GCP_PROJECT_ID" \
            --quiet
        success "Secret '$AGENT_RES_SECRET' shell created."
    fi
}

run_terraform() {
    step 10 "Deploying Infrastructure with Terraform";
    local ENV_TF_DIR="$REPO_ROOT/infrastructure"
    TFVARS_FILE_PATH="$ENV_TF_DIR/$ENV_NAME.tfvars"; info "Navigating to $ENV_TF_DIR..."; cd "$ENV_TF_DIR"
    info "Initializing Terraform..."; terraform init -reconfigure -upgrade -backend-config="${ENV_NAME}.backend.tfvars"
    info "Planning Terraform changes..."
    
    set +e
    terraform plan -detailed-exitcode -var-file="$TFVARS_FILE_PATH" -out="tfplan"
    local PLAN_STATUS=$?
    set -e

    if [ $PLAN_STATUS -eq 0 ]; then
        success "Terraform plan detected zero required infrastructure modifications. Skipping apply step!"
        rm -f tfplan
        return 0
    elif [ $PLAN_STATUS -ne 2 ]; then
        rm -f tfplan
        fail "Terraform plan encountered an error (exit code $PLAN_STATUS)."
    fi

    if [ "$TF_AUTO_APPROVE" = "true" ]; then
        info "Auto-approve flag (--auto-approve) detected. Applying infrastructure modifications automatically..."
        terraform apply "tfplan" -parallelism=30
    else
        warn "ℹ️  Database Upgrade Notice: If upgrading an existing installation, Terraform will provision a new Private PostgreSQL instance while keeping your existing database online."
        warn "   After provisioning completes, the script will automatically transfer your data to the new private instance."
        prompt "\nTerraform is ready to apply the changes. This will create or update infrastructure."
        prompt "Do you want to proceed with 'terraform apply'? (y/n)"
        read -r REPLY < /dev/tty
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            rm -f tfplan
            warn "Apply cancelled by user."
            return 0
        fi
        terraform apply "tfplan" -parallelism=30
    fi
    rm -f tfplan
}

auto_migrate_database() {
    step 11 "Checking Database Migration Requirements"
    info "Checking if an existing database migration is required..."

    local ENV_TF_DIR="$REPO_ROOT/infrastructure"

    pushd "$ENV_TF_DIR" > /dev/null
    local TARGET_INSTANCE=$(terraform output -raw cloud_sql_connection_name 2>/dev/null | cut -d':' -f3 || echo "")
    popd > /dev/null

    if [ -z "$TARGET_INSTANCE" ]; then
        info "No active Cloud SQL instance found in Terraform outputs. Skipping migration."
        return 0
    fi

    local SOURCE_INSTANCE=$(gcloud sql instances list --project="$GCP_PROJECT_ID" --format="value(name)" | grep -v "$TARGET_INSTANCE" | head -n 1 || echo "")

    if [ -n "$SOURCE_INSTANCE" ]; then
        warn "Detected existing database instance: ${C_YELLOW}${SOURCE_INSTANCE}${C_RESET}"
        info "Checking if automatic data migration to target instance '${TARGET_INSTANCE}' is needed..."

        local ASSET_BUCKET="${GCP_PROJECT_ID}-cs-${ENV_NAME}-bucket"
        local MIGRATE_SCRIPT="$REPO_ROOT/infrastructure/migration/migrate_to_private_db.sh"
        if [ -f "$MIGRATE_SCRIPT" ]; then
            info "Starting automatic data migration from ${SOURCE_INSTANCE} to ${TARGET_INSTANCE}..."
            SOURCE_INSTANCE="$SOURCE_INSTANCE" \
            TARGET_INSTANCE="$TARGET_INSTANCE" \
            DATABASE_NAME="creative_studio" \
            BUCKET_NAME="$ASSET_BUCKET" \
            bash "$MIGRATE_SCRIPT" || warn "Automatic database migration produced warnings or skipped (target database may already contain data)."
        fi
    else
        info "No legacy database instance found. Proceeding with fresh deployment."
    fi
}

update_oauth_client() {
    step 11 "Configuring OAuth Client URIs"; cd "$REPO_ROOT"
    if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then warn "Could not find OAuth Client ID automatically. Skipping URI update."; return; fi
    info "Fetching full OAuth client name..."; local OAUTH_CLIENT_FULL_NAME=$( (gcloud iap oauth-clients list "$GCP_PROJECT_ID" --format="json" 2>/dev/null || echo "[]") | jq -r --arg clientid "$AUTO_OAUTH_CLIENT_ID" 'try (.[]? | select(.name | contains($clientid)) | .name) catch ""' 2>/dev/null || echo "" )
    if [ -z "$OAUTH_CLIENT_FULL_NAME" ]; then warn "Could not resolve the full name for the OAuth client. Skipping URI update."; return; fi
    info "Ensuring OAuth Client has all required origins and redirect URIs..."; local PROJECT_DOMAIN_BASE=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectId)')
    local FIREBASEAPP_ORIGIN="https://${PROJECT_DOMAIN_BASE}.firebaseapp.com"; local WEBAPP_ORIGIN="https://${PROJECT_DOMAIN_BASE}.web.app"
    local FIREBASEAPP_REDIRECT_URI="${FIREBASEAPP_ORIGIN}/__/auth/handler"; local WEBAPP_REDIRECT_URI="${WEBAPP_ORIGIN}/__/auth/handler"
    gcloud iap oauth-clients update "$OAUTH_CLIENT_FULL_NAME" --add-javascript-origins="$FIREBASEAPP_ORIGIN" --add-javascript-origins="$WEBAPP_ORIGIN" --add-redirect-uris="$FIREBASEAPP_REDIRECT_URI" --add-redirect-uris="$WEBAPP_REDIRECT_URI" --project="$GCP_PROJECT_ID" --quiet
    success "OAuth Client URIs configured automatically."
}

update_secrets() {
    step 12 "Updating Remaining Secrets"; info "Navigating to $REPO_ROOT/infrastructure..."; cd "$REPO_ROOT/infrastructure"
    info "Populating values in Secret Manager..."; local TERRAFORM_OUTPUTS=$(terraform output -json 2>/dev/null || echo "{}")
    local FRONTEND_SECRETS=$( (echo "$TERRAFORM_OUTPUTS" 2>/dev/null || echo "{}") | jq -r 'try (.frontend_secrets.value[]?) catch ""' 2>/dev/null || echo "" ); local BACKEND_SECRETS=$( (echo "$TERRAFORM_OUTPUTS" 2>/dev/null || echo "{}") | jq -r 'try (.backend_secrets.value[]?) catch ""' 2>/dev/null || echo "" )
    local ALL_SECRETS=$(echo "${FRONTEND_SECRETS} ${BACKEND_SECRETS}" | tr ' ' '\n' | sort -u | grep .)
    if [ -z "$ALL_SECRETS" ]; then success "No secrets defined in Terraform outputs. Nothing to do."; return; fi

    # --- Double-check for Firebase config if variables are not set ---
    # This handles cases where the script is resumed after step 7
    if [ -z "$AUTO_FIREBASE_API_KEY" ]; then
        info "Auto-discovered Firebase variables not set. Re-running discovery..."
        local FE_APP_NAME=$(grep 'frontend_service_name' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')
        if [ -z "$FE_APP_NAME" ]; then
            warn "Could not determine frontend service name from .tfvars. Cannot auto-discover Firebase secrets."
        else
            local APP_ID=$( (firebase apps:list --project="$GCP_PROJECT_ID" --json 2>/dev/null || echo "{}") | jq -r --arg name "$FE_SERVICE_NAME" 'try (.result[]? | select(.displayName == $name) | .appId) catch ""' 2>/dev/null || echo "" )
            if [ -n "$APP_ID" ]; then
                local SDK_CONFIG_JSON=$(firebase apps:sdkconfig WEB "$APP_ID" --project="$GCP_PROJECT_ID" --json 2>/dev/null || echo "{}")
				AUTO_FIREBASE_API_KEY=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.apiKey // "") catch ""' 2>/dev/null || echo "" )
                # ... (re-populate all other AUTO_... variables)
				AUTO_FIREBASE_AUTH_DOMAIN=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.authDomain // "") catch ""' 2>/dev/null || echo "" )
				AUTO_FIREBASE_PROJECT_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.projectId // "") catch ""' 2>/dev/null || echo "" )
				AUTO_FIREBASE_STORAGE_BUCKET=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.storageBucket // "") catch ""' 2>/dev/null || echo "" )
				AUTO_FIREBASE_MESSAGING_SENDER_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.messagingSenderId // "") catch ""' 2>/dev/null || echo "" )
				AUTO_FIREBASE_APP_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.appId // "") catch ""' 2>/dev/null || echo "" )
				AUTO_FIREBASE_MEASUREMENT_ID=$( (echo "$SDK_CONFIG_JSON" 2>/dev/null || echo "{}") | jq -r 'try (.result.sdkConfig.measurementId // "") catch ""' 2>/dev/null || echo "" )
                success "Successfully re-discovered Firebase configuration."
            fi
        fi
    fi

    for SECRET_NAME in $ALL_SECRETS; do
        info "Processing secret: ${C_YELLOW}${SECRET_NAME}${C_RESET}"

        SECRET_VALUE=""
        AUTO_DISCOVERED=false

        # Check if we have an auto-discovered value for the current secret
        case $SECRET_NAME in
            "FIREBASE_API_KEY")               SECRET_VALUE=$AUTO_FIREBASE_API_KEY; AUTO_DISCOVERED=true ;;
            "FIREBASE_AUTH_DOMAIN")           SECRET_VALUE=$AUTO_FIREBASE_AUTH_DOMAIN; AUTO_DISCOVERED=true ;;
            "FIREBASE_PROJECT_ID")            SECRET_VALUE=$AUTO_FIREBASE_PROJECT_ID; AUTO_DISCOVERED=true ;;
            "FIREBASE_STORAGE_BUCKET")        SECRET_VALUE=$AUTO_FIREBASE_STORAGE_BUCKET; AUTO_DISCOVERED=true ;;
            "FIREBASE_MESSAGING_SENDER_ID")   SECRET_VALUE=$AUTO_FIREBASE_MESSAGING_SENDER_ID; AUTO_DISCOVERED=true ;;
            "FIREBASE_APP_ID")                SECRET_VALUE=$AUTO_FIREBASE_APP_ID; AUTO_DISCOVERED=true ;;
            "FIREBASE_MEASUREMENT_ID")        SECRET_VALUE=$AUTO_FIREBASE_MEASUREMENT_ID; AUTO_DISCOVERED=true ;;
            # GOOGLE_CLIENT_ID is handled by populate_oauth_secrets, so we skip it here
            "GOOGLE_CLIENT_ID")               info "  Value is handled by the OAuth population step. Skipping."; continue ;;
            "GOOGLE_TOKEN_AUDIENCE")          info "  Value is handled by the OAuth population step. Skipping."; continue ;;
        esac

        if [ "$AUTO_DISCOVERED" = true ] && [ -n "$SECRET_VALUE" ]; then
            info "  Value was auto-detected from Firebase. Populating automatically."
            echo -n "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" --data-file="-" --project="$GCP_PROJECT_ID" --quiet
            success "  Successfully added new version for ${SECRET_NAME}."

        else
            # This fallback is now only for secrets that are not auto-discovered
            if [ "$TF_AUTO_APPROVE" = "true" ]; then
                info "  Auto-approve enabled. Skipping manual input for ${SECRET_NAME}."
                continue
            fi
            warn "  This secret requires manual input."
            echo -e "${C_CYAN}  It is safe to paste your secret. The value is read securely, not displayed, and not stored in history.${C_RESET}"
            read -s -p "  Enter new value: " SECRET_VALUE < /dev/tty; echo

            if [ -z "$SECRET_VALUE" ]; then warn "  No value provided. Skipping ${SECRET_NAME}."; continue; fi
            echo -n "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" --data-file="-" --project="$GCP_PROJECT_ID" --quiet
            success "  Successfully added new version for ${SECRET_NAME}."
        fi
    done; success "All secrets have been populated."
}

seed_database() {
    step 14 "Executing Database Migrations & Initial Seeding (Cloud Run Job)"
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

    # 2. Deduce target runtime image URL from local Artifact Registry repository
    local STABLE_IMAGE="${DEPLOY_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${RES_PREFIX}-${ENV_NAME}-repo/backend:latest"
    info "Target secure runtime image: ${C_YELLOW}${STABLE_IMAGE}${C_RESET}"
    
    info "Database: ${DB_CONN_NAME}"
    info "Subnetwork Egress: ${SUBNET_NAME}"

    info "Verifying backend container image in Artifact Registry..."
    local attempts=0
    while ! gcloud artifacts docker images describe "$STABLE_IMAGE" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ $attempts -gt 30 ]; then
            warn "Container image not ready after 15 minutes. Please verify Cloud Build completion."
            fail "Database seeding aborted because container image was not found."
        fi
        echo -n "." # waiting for Cloud Build
        sleep 30
    done
    echo ""
    success "Container image confirmed available in Artifact Registry!"

    local CURRENT_USER=$(gcloud config get-value account 2>/dev/null || echo "system")
    local BUCKET_ASSETS="${GCP_PROJECT_ID}-cs-${ENV_NAME}-bucket"

    # 3. Create a secure, temporary Google Cloud Run Job inside the VPC boundary
    info "Registering secure administrative Job inside VPC..."
    
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

trigger_builds() {
    step 13 "Triggering Initial Builds"; cd "$REPO_ROOT"
    if [ "$TF_AUTO_APPROVE" = "true" ]; then
        info "Auto-approve flag detected. Triggering initial container builds automatically."
        REPLY="y"
    else
        prompt "Would you like to trigger the initial builds for the frontend and backend now? (y/n)"; read -r REPLY < /dev/tty
    fi
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then info "You can trigger the builds manually later by pushing a commit or via the Cloud Build UI."; return; fi

    local BRANCH_TO_USE
    BRANCH_TO_USE=$(git branch --show-current 2>/dev/null)
    if [ -z "$BRANCH_TO_USE" ]; then
        BRANCH_TO_USE=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    fi

    if [ -z "$BRANCH_TO_USE" ] || [ "$BRANCH_TO_USE" = "HEAD" ]; then
        if [ -n "$GITHUB_BRANCH" ] && [ "$GITHUB_BRANCH" != "HEAD" ]; then
            BRANCH_TO_USE="$GITHUB_BRANCH"
        elif git show-ref --verify --quiet refs/heads/develop || git show-ref --verify --quiet refs/remotes/origin/develop; then
            BRANCH_TO_USE="develop"
        else
            BRANCH_TO_USE="main"
        fi
        info "Git HEAD is detached or branch unavailable. Falling back to branch: ${C_YELLOW}${BRANCH_TO_USE}${C_RESET}"
    else
        info "Detected current Git branch: ${C_YELLOW}${BRANCH_TO_USE}${C_RESET}"
    fi

    info "Triggering backend build..."; gcloud builds triggers run "${BE_SERVICE_NAME}-trigger" --branch="$BRANCH_TO_USE" --project="$GCP_PROJECT_ID" --region="us-central1"
    info "Triggering frontend build..."; gcloud builds triggers run "${GCP_PROJECT_ID}-trigger" --branch="$BRANCH_TO_USE" --project="$GCP_PROJECT_ID" --region="us-central1"

    success "Builds have been triggered."; info "You can monitor their progress in the Cloud Build console:"; echo -e "   ${C_YELLOW}https://console.cloud.google.com/cloud-build/builds?project=${GCP_PROJECT_ID}${C_RESET}"
}

deploy_izumi_agent() {
    step 15 "Automated Izumi Agent Deployment"
    info "Deploying Izumi Agent..."

    rm -rf /tmp/izumi-agent
    trap 'rm -rf /tmp/izumi-agent' EXIT INT TERM

    IZUMI_BRANCH="${IZUMI_AGENT_BRANCH:-feat/unified-mediagent-interface}"
    info "Cloning Izumi Agent repository (branch: ${IZUMI_BRANCH})..."
    git clone -b "$IZUMI_BRANCH" https://github.com/GoogleCloudPlatform/genmedia-izumi-agent.git /tmp/izumi-agent

    info "Setting up Python virtual environment and installing dependencies using uv..."
    pushd /tmp/izumi-agent > /dev/null
    uv venv .venv
    uv pip install --python .venv/bin/python -e .

    if [ "$MOCK_IZUMI_DEPLOY" = "true" ]; then
        info "MOCK_IZUMI_DEPLOY is set to true. Skipping real GCP connection."
        info "Mock execution of deploy_to_agent_engine.py successful."
    else
        info "Executing deployment script..."
        AGENT_SA_EMAIL=""
        local ENV_TF_DIR="$REPO_ROOT/infrastructure"
        if [ -d "$ENV_TF_DIR" ]; then
            AGENT_SA_EMAIL=$(cd "$ENV_TF_DIR" && terraform output -raw agent_service_account_email 2>/dev/null || echo "")
        fi

        # Fetch generated auth token secret from Secret Manager
        AGENT_AUTH_TOKEN=$(gcloud secrets versions access latest --secret="agent_engine_user_auth_token_key" --project="$GCP_PROJECT_ID" 2>/dev/null || echo "")
        if [ -n "$AGENT_AUTH_TOKEN" ]; then
            export AGENT_ENGINE_USER_AUTH_TOKEN_KEY="$AGENT_AUTH_TOKEN"
        fi

        CMD=".venv/bin/python scripts/deploy_to_agent_engine.py"
        if [ -n "$AGENT_SA_EMAIL" ] && [ "$AGENT_SA_EMAIL" != "null" ]; then
            info "Using dedicated AI Agent Service Account: $AGENT_SA_EMAIL"
            CMD="$CMD --service-account=$AGENT_SA_EMAIL"
        fi

        DEPLOY_LOG=$(mktemp)
        if $CMD 2>&1 | tee "$DEPLOY_LOG"; then
            RESOURCE_NAME=$(grep -oE "projects/[^/]+/locations/[^/]+/reasoningEngines/[0-9]+" "$DEPLOY_LOG" | tail -n 1 || echo "")
            if [ -n "$RESOURCE_NAME" ]; then
                info "Captured Agent Engine Resource Name: ${C_YELLOW}${RESOURCE_NAME}${C_RESET}"
                echo -n "$RESOURCE_NAME" | gcloud secrets versions add agent_engine_resource_name --data-file="-" --project="$GCP_PROJECT_ID" --quiet
                success "Stored agent_engine_resource_name in Secret Manager."
            fi
        else
            rm -f "$DEPLOY_LOG"
            fail "Izumi Agent deployment failed."
        fi
        rm -f "$DEPLOY_LOG"
    fi
    popd > /dev/null
    rm -rf /tmp/izumi-agent
    trap - EXIT INT TERM
    success "Izumi Agent deployed successfully."
}

select_deployment_profile() {
    step 2 "Selecting Deployment Configuration Profile"
    local PROFILE_DIR="${HOME}/.cstudio/profiles"
    mkdir -p "$PROFILE_DIR"

    if [ -n "$CLI_PROFILE" ]; then
        local PROFILE_NAME="${CLI_PROFILE%.cstudio_bootstrap.conf}.cstudio_bootstrap.conf"
        STATE_FILE="$PROFILE_DIR/$PROFILE_NAME"
        info "Loading targeted deployment profile via CLI flag: ${C_YELLOW}${STATE_FILE}${C_RESET}"
        read_state
        if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/infrastructure" ]; then
            local SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
            if [ -d "$SCRIPT_DIR/infrastructure" ]; then REPO_ROOT="$SCRIPT_DIR";
            elif [ -d "$(pwd)/gcc-creative-studio/infrastructure" ]; then REPO_ROOT="$(pwd)/gcc-creative-studio";
            elif [ -d "infrastructure" ]; then REPO_ROOT="$(pwd)"; fi
        fi
        if [ -n "$REPO_ROOT" ]; then export REPO_ROOT; write_state "REPO_ROOT" "$REPO_ROOT"; fi
        return 0
    fi

    local profiles=()
    while IFS= read -r file; do
        [ -f "$file" ] && profiles+=("$file")
    done < <(find "$PROFILE_DIR" -maxdepth 1 -name "*.cstudio_bootstrap.conf" 2>/dev/null | sort)

    if [ ${#profiles[@]} -eq 0 ]; then
        info "No persistent profiles detected in $PROFILE_DIR. Initializing 'default.cstudio_bootstrap.conf'..."
        STATE_FILE="$PROFILE_DIR/default.cstudio_bootstrap.conf"
        write_state "PROFILE_INITIALIZED" "true"
        return 0
    fi

    echo -e "${C_CYAN}➡️  Detected persistent deployment profiles in ${PROFILE_DIR}:${C_RESET}"
    for i in "${!profiles[@]}"; do
        local p_file="${profiles[$i]}"
        local p_name=$(basename "$p_file")
        local p_proj=$(grep "^GCP_PROJECT_ID=" "$p_file" | cut -d'=' -f2 || echo "unassigned")
        local p_branch=$(grep "^GITHUB_BRANCH=" "$p_file" | cut -d'=' -f2 || echo "main")
        echo -e "    [$((i + 1))] ${C_YELLOW}${p_name}${C_RESET} (Project: ${p_proj} | Branch: ${p_branch})"
    done
    echo "    [N] + Create a brand new deployment profile"

    prompt "Which deployment profile would you like to use? [Default: 1 / N for new]"
    read -p "   Select Profile [1]: " PROF_CHOICE < /dev/tty
    PROF_CHOICE=${PROF_CHOICE:-1}

    if [[ "$PROF_CHOICE" =~ ^[nN]$ ]]; then
        prompt "Enter a name for your new deployment profile (e.g. dev, staging, prod):"
        read -p "   Profile Name: " NEW_PROF_NAME < /dev/tty
        NEW_PROF_NAME=${NEW_PROF_NAME:-custom}
        NEW_PROF_NAME="${NEW_PROF_NAME%.cstudio_bootstrap.conf}.cstudio_bootstrap.conf"
        STATE_FILE="$PROFILE_DIR/$NEW_PROF_NAME"
        info "Created new deployment profile at: $STATE_FILE"
        write_state "PROFILE_INITIALIZED" "true"
        return 0
    fi

    local idx=$((PROF_CHOICE - 1))
    if [ -n "${profiles[$idx]}" ]; then
        STATE_FILE="${profiles[$idx]}"
        info "Loading deployment profile: ${C_YELLOW}${STATE_FILE}${C_RESET}"
        read_state
        
        if [ -z "$GCP_PROJECT_ID" ] && [ -z "$GITHUB_REPO_URL" ]; then
            info "Profile '${C_YELLOW}$(basename "$STATE_FILE" .cstudio_bootstrap.conf)${C_RESET}' is fresh or unassigned. Interactive prompts will now guide you to complete missing settings and automatically save them to this profile!"
            return 0
        fi

        echo -e "${C_CYAN}➡️  Loaded Profile Parameters:${C_RESET}"
        echo "    • GCP Project ID:         ${GCP_PROJECT_ID:-unassigned}"
        echo "    • Fork Repository URL:    ${GITHUB_REPO_URL:-unassigned}"
        echo "    • Deployment Branch:      ${GITHUB_BRANCH:-main}"
        echo "    • Environment Name:       ${ENV_NAME:-unassigned}"
        echo "    • Cloud Build Conn Name:  ${GITHUB_CONN_NAME:-unassigned}"
        echo "    • OAuth Web Client ID:    ${AUTO_OAUTH_CLIENT_ID:-unassigned}"
        echo "    • Firebase Site ID:       ${AUTO_FIREBASE_SITE_ID:-unassigned}"
        
        prompt "Use these stored deployment parameters? (Y/n / e to edit)"
        read -p "   Confirm [Y/n/e]: " CONFIRM_PROF < /dev/tty
        if [[ "$CONFIRM_PROF" =~ ^[nNeE]$ ]]; then
            info "You opted to edit or reset parameters. Interactive prompts will allow overriding values."
            if [[ "$CONFIRM_PROF" =~ ^[eE]$ ]]; then
                prompt "Would you like to reset OAuth Client ID, Firebase Site ID, and Cloud Build connection to be prompted again? (y/N)"
                read -p "   Reset OAuth/Conn [y/N]: " RESET_AUTH < /dev/tty
                if [[ "$RESET_AUTH" =~ ^[Yy]$ ]]; then
                    unset AUTO_OAUTH_CLIENT_ID GITHUB_CONN_NAME AUTO_FIREBASE_SITE_ID
                    sed -i.bak '/^AUTO_OAUTH_CLIENT_ID=/d;/^GITHUB_CONN_NAME=/d;/^AUTO_FIREBASE_SITE_ID=/d' "$STATE_FILE" 2>/dev/null && rm -f "${STATE_FILE}.bak"
                fi
            fi
        else
            success "Deployment parameters locked in from profile!"
        fi
    else
        warn "Invalid selection. Defaulting to first profile..."
        STATE_FILE="${profiles[0]}"
        read_state
    fi
}


# --- Main Execution ---
main() {
    TF_AUTO_APPROVE="false"
    CLI_PROFILE=""
    while [[ $# -gt 0 ]]; do
        case $1 in
            --profile|-p)
                CLI_PROFILE="$2"
                shift 2
                ;;
            --auto-approve|-a)
                TF_AUTO_APPROVE="true"
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [--profile <profile_name>] [--auto-approve]"
                exit 0
                ;;
            *)
                warn "Unknown parameter: $1. Ignoring."
                shift
                ;;
        esac
    done
    export TF_AUTO_APPROVE CLI_PROFILE
    echo -e "${C_GREEN}============================================================${C_RESET}"
    echo -e "${C_GREEN} 🚀  Welcome to the Creative Studio Infrastructure Setup 🚀 ${C_RESET}"
    echo -e "${C_GREEN}============================================================${C_RESET}"

    echo -e "${C_BLUE}"
    echo -e " ██████ ██████  ███████  █████  ████████ ██ ██    ██ ███████     ███████ ████████ ██    ██ ██████  ██  ██████  "
    echo -e "██      ██   ██ ██      ██   ██    ██    ██ ██    ██ ██          ██         ██    ██    ██ ██   ██ ██ ██    ██ "
    echo -e "██      ██████  █████   ███████    ██    ██ ██    ██ █████       ███████    ██    ██    ██ ██   ██ ██ ██    ██ "
    echo -e "██      ██   ██ ██      ██   ██    ██    ██  ██  ██  ██               ██    ██    ██    ██ ██   ██ ██ ██    ██ "
    echo -e " ██████ ██   ██ ███████ ██   ██    ██    ██   ████   ███████     ███████    ██     ██████  ██████  ██  ██████   "
    echo -e "${C_RESET}"

    info "ℹ️  Network & Database Update Notice: Creative Studio deploys PostgreSQL inside a Private VPC by default for enterprise security."
    info "   If upgrading an existing installation, data will be migrated automatically to the new private instance during deployment."
    echo ""

    read_state; LAST_COMPLETED_STEP=${LAST_COMPLETED_STEP:-0}
    if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/infrastructure" ]; then
        local SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [ -d "$SCRIPT_DIR/infrastructure" ]; then
            REPO_ROOT="$SCRIPT_DIR"
            write_state "REPO_ROOT" "$REPO_ROOT"
        elif [ -d "$(pwd)/gcc-creative-studio/infrastructure" ]; then
            REPO_ROOT="$(pwd)/gcc-creative-studio"
            write_state "REPO_ROOT" "$REPO_ROOT"
        elif [ -d "infrastructure" ]; then
            REPO_ROOT="$(pwd)"
            write_state "REPO_ROOT" "$REPO_ROOT"
        fi
    fi
    export REPO_ROOT
    declare -a steps_to_run=(
        "check_prerequisites"
        "select_deployment_profile"
        "check_and_install_terraform"
        "setup_project" "setup_repo"
        "configure_environment"
        "handle_manual_steps"
        "setup_firebase_app"
        "setup_db_secrets"
        "run_terraform"
        "auto_migrate_database"
        "populate_oauth_secrets"
        "update_oauth_client"
        "update_secrets"
        "trigger_builds"
        "seed_database"
        "deploy_izumi_agent"
    )
    for i in "${!steps_to_run[@]}"; do
        step_num=$((i + 1))
        if (( LAST_COMPLETED_STEP < step_num )); then
            ${steps_to_run[$i]}; write_state "LAST_COMPLETED_STEP" "$step_num"
        fi
    done

    step 16 "🎉 Deployment Complete! 🎉";
    info "Fetching your application URLs...";
    local ENV_TF_DIR="$REPO_ROOT/infrastructure"
    cd "$ENV_TF_DIR"

    # Try to get the frontend URL from terraform output, but handle the error
    FRONTEND_URL=$(terraform output -raw frontend_service_url 2>/dev/null || echo "")
    if [ -z "$FRONTEND_URL" ]; then
        warn "Could not find 'frontend_service_url' in Terraform outputs. Deducing from project ID."
        # Construct the default Firebase Hosting URL using the discovered site ID
        if [ -n "$AUTO_FIREBASE_SITE_ID" ]; then
            FRONTEND_URL="https://${AUTO_FIREBASE_SITE_ID}.web.app"
        else
            FRONTEND_URL="https://$(echo "$GCP_PROJECT_ID" | tr '[:upper:]' '[:lower:]').web.app"
        fi
    fi

    # Get the backend URL
    BACKEND_URL=$(terraform output -raw backend_service_url 2>/dev/null || echo "")
    if [ -z "$BACKEND_URL" ]; then
        warn "Could not find 'backend_service_url' in Terraform outputs."
    fi

    success "Your infrastructure is ready."
    echo "------------------------------------------------------------------"; echo -e "   Frontend URL: ${C_YELLOW}${FRONTEND_URL}${C_RESET}"; echo -e "   Backend URL:  ${C_YELLOW}${BACKEND_URL}${C_RESET}"; echo "------------------------------------------------------------------"
    info "It may take a few minutes for the builds to complete and the services to become available."

    echo # Add a blank line for spacing
    info "Thanks for using Creative Studio!"
    info "We'd love your feedback: ${C_YELLOW}https://docs.google.com/forms/d/e/1FAIpQLSceWvu7G354h-dTbOGvNGEraEjcUAgPE300WNY5qr-WJbh3Eg/viewform${C_RESET}"
    echo -e "${C_GREEN}============================================================${C_RESET}"
}

main "$@"
