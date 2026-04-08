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
set -o pipefail

# --- Configuration ---
REQUIRED_TERRAFORM_VERSION="1.14.8"
UPSTREAM_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio"
TEMPLATE_ENV_DIR="environments/env-template"
DEFAULT_ENV_NAME="dev-infra"
DEFAULT_BRANCH_NAME="main"
GCS_BUCKET_SUFFIX_FORMAT="cstudio-%s-tfstate"
GCS_BUCKET_PREFIX_FORMAT="infrastructure/%s/state"
BE_SERVICE_NAME="cstudio-be"
FE_SERVICE_NAME="cstudio-fe"

STATE_FILE=""
REPO_ROOT=""

# --- Color Definitions (High Contrast) ---
C_RESET='\033[0m'
C_RED='\033[1;31m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_BLUE='\033[1;34m'
C_CYAN='\033[1;36m'

# --- Helper Functions ---
info() { echo -e "${C_CYAN}➡️  $1${C_RESET}"; }
prompt() { echo -e "${C_BLUE}🤔  $1${C_RESET}"; }
warn() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
fail() { echo -e "${C_RED}❌  $1${C_RESET}" >&2; exit 1; }
success() { echo -e "${C_GREEN}✅  $1${C_RESET}"; }
step() { echo -e "\n${C_BLUE}--- Step $1: $2 ---${C_RESET}"; }

# Spinner helper
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

configure_firebase_site_id() {
  info "Checking Firebase Hosting Site configuration..."
  local tfvars_file=$1
  local project_id=$2

  if grep -q "YOUR_FIREBASE_SITE_ID" "$tfvars_file"; then
    warn "Placeholder 'YOUR_FIREBASE_SITE_ID' found in ${tfvars_file}."
    info "Querying Firebase for an existing default hosting site..."
    local default_site_name
    default_site_name=$(firebase hosting:sites:list --project "$project_id" --json | jq -r 'first(.result.sites[] | select(.type == "DEFAULT_SITE") | .name) // first(.result.sites[].name) // ""')
    local site_id_to_use=$project_id
    [ -n "$default_site_name" ] && site_id_to_use=$(basename "$default_site_name")
    info "Setting 'firebase_site_id' to '${C_YELLOW}${site_id_to_use}${C_RESET}' in ${tfvars_file}."
    sed -i.bak "s/YOUR_FIREBASE_SITE_ID/${site_id_to_use}/" "$tfvars_file" && rm "${tfvars_file}.bak"
  fi
}

prompt_and_update_tfvar() {
    local prompt_text=$1
    local default_value=$2
    local tfvar_name=$3
    local var_to_set_ref=$4

    read -p "   $prompt_text [default value: $default_value]: " user_input < /dev/tty
    local final_value=${user_input:-$default_value}
    sed -i.bak "s|^[#[:space:]]*${tfvar_name}[[:space:]]*=.*|${tfvar_name} = \"${final_value}\"|g" "$TFVARS_FILE_PATH"
    eval "$var_to_set_ref='$final_value'"
}

write_state() {
    if [ -z "$STATE_FILE" ]; then return; fi
    if ! (
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

check_prerequisites() {
    step 1 "Checking Prerequisites"
    command -v gcloud >/dev/null || fail "gcloud CLI not found."
    command -v git >/dev/null || fail "git not found."
    command -v jq >/dev/null || fail "jq not found."
    command -v firebase >/dev/null || fail "Firebase CLI not found."
    success "Prerequisites met."
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
        install_terraform
        return
    fi
    INSTALLED_VERSION=$(terraform version -json | jq -r .terraform_version)
    if [[ "$(printf '%s\n' "$REQUIRED_TERRAFORM_VERSION" "$INSTALLED_VERSION" | sort -V | head -n1)" != "$REQUIRED_TERRAFORM_VERSION" ]]; then
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
    curl -Lo terraform.zip "$TF_DOWNLOAD_URL"
    unzip -o terraform.zip
    mkdir -p "$HOME/bin"
    mv terraform "$HOME/bin/"
    export PATH="$HOME/bin:$PATH"
    hash -r
    rm terraform.zip LICENSE.txt
    success "Terraform installed."
}

setup_project() {
    step 3 "Configuring Google Cloud Project"
    CURRENT_GCLOUD_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
    if [ -n "$GCP_PROJECT_ID" ]; then
        gcloud config set project "$GCP_PROJECT_ID"
    elif [ -n "$CURRENT_GCLOUD_PROJECT" ]; then
        GCP_PROJECT_ID=$CURRENT_GCLOUD_PROJECT
        gcloud config set project "$GCP_PROJECT_ID"
    else
        prompt "Please enter your Google Cloud Project ID:"
        read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
        gcloud config set project "$GCP_PROJECT_ID"
    fi
    write_state "GCP_PROJECT_ID" "$GCP_PROJECT_ID"
    success "Project '$GCP_PROJECT_ID' is configured."
}

setup_repo() {
    step 4 "Configuring Git Repository"
    REPO_ROOT=$(pwd)
    export REPO_ROOT
    write_state "REPO_ROOT" "$REPO_ROOT"
    
    GITHUB_REPO_OWNER=$(git remote get-url origin | sed -n 's/.*github.com\/\(.*\)\/.*/\1/p' | cut -d/ -f1)
    GITHUB_REPO_NAME=$(basename `git rev-parse --show-toplevel`)
    
    write_state "GITHUB_REPO_OWNER" "$GITHUB_REPO_OWNER"
    write_state "GITHUB_REPO_NAME" "$GITHUB_REPO_NAME"
    success "Repository configured."
}

configure_environment() {
    step 5 "Configuring Terraform Environment"
    cd "$REPO_ROOT/infrastructure"
    if [ -z "$ENV_NAME" ]; then
        prompt "What would you like to call this deployment environment?"
        read -p "   Environment Name [default: $DEFAULT_ENV_NAME]: " ENV_NAME < /dev/tty
        ENV_NAME=${ENV_NAME:-$DEFAULT_ENV_NAME}
    fi
    ENV_DIR="environments/$ENV_NAME"
    TFVARS_FILE_PATH="$REPO_ROOT/infrastructure/$ENV_DIR/$ENV_NAME.tfvars"
    STATE_FILE="$REPO_ROOT/infrastructure/$ENV_DIR/.bootstrap_state"
    
    if [ ! -d "$ENV_DIR" ]; then
        info "Creating environment directory from template..."
        cp -r "$TEMPLATE_ENV_DIR" "$ENV_DIR"
        
        BUCKET_NAME="${GCP_PROJECT_ID}-tfstate"
        info "Creating GCS bucket '$BUCKET_NAME' for Terraform state..."
        gsutil mb -p "$GCP_PROJECT_ID" "gs://${BUCKET_NAME}" > /dev/null 2>&1 &
        spinner $!
        
        echo "terraform {
  backend \"gcs\" {
    bucket = \"$BUCKET_NAME\"
    prefix = \"infrastructure/$ENV_NAME/state\"
  }
}" > "$ENV_DIR/backend.tf"

        mv "$ENV_DIR/dev.tfvars" "$TFVARS_FILE_PATH"
        sed -i.bak "s|YOUR_GCP_PROJECT_ID|$GCP_PROJECT_ID|g" "$TFVARS_FILE_PATH"
        rm -f "$TFVARS_FILE_PATH.bak"
        
        write_state "ENV_NAME" "$ENV_NAME"
    fi
    success "Environment '$ENV_NAME' configured."
}

main() {
    echo -e "${C_GREEN}============================================================${C_RESET}"
    echo -e "${C_GREEN} 🚀  Welcome to the Creative Studio Infrastructure Setup 🚀 ${C_RESET}"
    echo -e "${C_GREEN}============================================================${C_RESET}"

    read_state
    LAST_COMPLETED_STEP=${LAST_COMPLETED_STEP:-0}
    
    declare -a steps_to_run=(
        "check_prerequisites"
        "check_and_install_terraform"
        "setup_project"
        "setup_repo"
        "configure_environment"
    )
    
    for i in "${!steps_to_run[@]}"; do
        step_num=$((i + 1))
        if (( LAST_COMPLETED_STEP < step_num )); then
            if [ -z "$STATE_FILE" ] && [ "$step_num" -gt 4 ]; then
                STATE_FILE="$REPO_ROOT/infrastructure/environments/$ENV_NAME/.bootstrap_state"
                write_state "REPO_ROOT" "$REPO_ROOT"
            fi
            ${steps_to_run[$i]}
            write_state "LAST_COMPLETED_STEP" "$step_num"
        fi
    done

    info "Handing off to deploy.sh in the environment directory..."
    cd "$REPO_ROOT/infrastructure/environments/$ENV_NAME"
    if [ -f "./deploy.sh" ]; then
        bash ./deploy.sh
    else
        fail "deploy.sh not found in the environment directory."
    fi
}

main "$@"
