#!/usr/bin/env bash
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

#
# test_bootstrap_offline.sh
# Automated offline unit test suite for Creative Studio bootstrap.sh.
# Simulates Google Cloud CLI, Firebase CLI, and Terraform commands using mocks
# to verify multi-profile workflows, self-healing parameter generation, and non-interactive execution.
#

set -eo pipefail

# --- Color Formatting ---
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_RESET='\033[0m'

info()    { echo -e "${C_BLUE}[TEST-INFO]${C_RESET} $*"; }
success() { echo -e "${C_GREEN}[TEST-PASS]${C_RESET} $*"; }
fail()    { echo -e "${C_RED}[TEST-FAIL]${C_RESET} $*" >&2; exit 1; }

# Locate repository root and target script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BOOTSTRAP_SCRIPT="${REPO_ROOT}/bootstrap.sh"

if [ ! -f "${BOOTSTRAP_SCRIPT}" ]; then
    fail "Could not find bootstrap.sh at ${BOOTSTRAP_SCRIPT}."
fi

# --- Initialize Temporary Test Workspace ---
TEST_WORKSPACE=$(mktemp -d /tmp/cstudio_bootstrap_test_XXXXXX)
info "Initialized temporary test workspace at: ${TEST_WORKSPACE}"

# Ensure cleanup on exit
cleanup() {
    info "Cleaning up temporary test workspace: ${TEST_WORKSPACE}"
    rm -rf "${TEST_WORKSPACE}"
}
trap cleanup EXIT INT TERM

# Create required folder structure inside test workspace
mkdir -p "${TEST_WORKSPACE}/gcc-creative-studio/infrastructure/modules/artifact"
mkdir -p "${TEST_WORKSPACE}/gcc-creative-studio/infrastructure/modules/compute"
mkdir -p "${TEST_WORKSPACE}/gcc-creative-studio/infrastructure/modules/database"
mkdir -p "${TEST_WORKSPACE}/gcc-creative-studio/infrastructure/modules/network"
mkdir -p "${TEST_WORKSPACE}/gcc-creative-studio/backend"
mkdir -p "${TEST_WORKSPACE}/gcc-creative-studio/frontend"
cp "${BOOTSTRAP_SCRIPT}" "${TEST_WORKSPACE}/gcc-creative-studio/bootstrap.sh"
chmod +x "${TEST_WORKSPACE}/gcc-creative-studio/bootstrap.sh"

# --- Create Mock Executables ---
MOCK_BIN="${TEST_WORKSPACE}/mock_bin"
mkdir -p "${MOCK_BIN}"

cat << 'EOF' > "${MOCK_BIN}/gcloud"
#!/usr/bin/env bash
if [[ "$*" == *"auth print-access-token"* ]]; then
    echo "mock-access-token-9999"
    exit 0
elif [[ "$*" == *"config get-value project"* ]]; then
    echo "creative-studio-mock-project"
    exit 0
elif [[ "$*" == *"config set project"* ]]; then
    exit 0
elif [[ "$*" == *"services enable"* ]]; then
    echo "Operation finished successfully."
    exit 0
elif [[ "$*" == *"secrets describe"* || "$*" == *"secrets versions"* || "$*" == *"secrets create"* ]]; then
    echo "Mock secret operation successful."
    exit 0
elif [[ "$*" == *"builds triggers run"* ]]; then
    echo "Trigger run simulated successfully."
    exit 0
elif [[ "$*" == *"artifacts docker images describe"* ]]; then
    echo "image: latest"
    exit 0
elif [[ "$*" == *"run jobs"* || "$*" == *"run deploy"* ]]; then
    echo "Mock cloud run execution successful."
    exit 0
fi
echo "gcloud mock executed: $*" >&2
exit 0
EOF
chmod +x "${MOCK_BIN}/gcloud"

cat << 'EOF' > "${MOCK_BIN}/firebase"
#!/usr/bin/env bash
if [[ "$*" == *"apps:list"* ]]; then
    echo '{"result":[{"displayName":"cstudio-fe","appId":"1:999:web:mock123"}]}'
    exit 0
elif [[ "$*" == *"apps:sdkconfig"* ]]; then
    echo '{"result":{"sdkConfig":{"apiKey":"mock-api-key-xyz","authDomain":"mock.firebaseapp.com","projectId":"creative-studio-mock-project","appId":"1:999:web:mock123"}}}'
    exit 0
elif [[ "$*" == *"hosting:sites:list"* ]]; then
    echo '{"result":{"sites":[{"name":"projects/creative-studio-mock-project/sites/creative-studio-mock-f9d5d","type":"DEFAULT_SITE"}]}}'
    exit 0
elif [[ "$*" == *"apps:create"* ]]; then
    echo "Firebase app created successfully."
    exit 0
fi
echo "firebase mock executed: $*" >&2
exit 0
EOF
chmod +x "${MOCK_BIN}/firebase"

cat << 'EOF' > "${MOCK_BIN}/terraform"
#!/usr/bin/env bash
if [[ "$1" == "version" ]]; then
    if [[ "$*" == *"-json"* ]]; then
        echo '{"terraform_version":"1.14.1"}'
    else
        echo "Terraform v1.14.1"
    fi
    exit 0
elif [[ "$1" == "init" ]]; then
    echo "Terraform initialized successfully."
    exit 0
elif [[ "$1" == "plan" ]]; then
    echo "Terraform plan encountered zero changes."
    exit 0
elif [[ "$1" == "apply" ]]; then
    echo "Terraform applied successfully."
    exit 0
elif [[ "$1" == "output" ]]; then
    if [[ "$*" == *"frontend_service_url"* ]]; then
        echo "https://creative-studio-mock-f9d5d.web.app"
    elif [[ "$*" == *"backend_service_url"* ]]; then
        echo "https://cstudio-be-xyz-uc.a.run.app"
    else
        echo "mock-output-value"
    fi
    exit 0
fi
echo "terraform mock executed: $*" >&2
exit 0
EOF
chmod +x "${MOCK_BIN}/terraform"

cat << 'EOF' > "${MOCK_BIN}/gsutil"
#!/usr/bin/env bash
echo "gsutil mock executed successfully."
exit 0
EOF
chmod +x "${MOCK_BIN}/gsutil"

cat << 'EOF' > "${MOCK_BIN}/jq"
#!/usr/bin/env bash
if [[ "$*" == *".oauthClientId"* ]]; then
    echo "999999999999-mockedclientid.apps.googleusercontent.com"
    exit 0
elif [[ "$*" == *"DEFAULT_SITE"* ]]; then
    echo "projects/creative-studio-mock-project/sites/creative-studio-mock-f9d5d"
    exit 0
elif [[ "$*" == *".sdkConfig.apiKey"* ]]; then
    echo "mock-api-key-xyz"
    exit 0
elif [[ "$*" == *".terraform_version"* ]]; then
    echo "1.14.1"
    exit 0
fi
echo "mock-jq-result"
exit 0
EOF
chmod +x "${MOCK_BIN}/jq"

cat << 'EOF' > "${MOCK_BIN}/git"
#!/usr/bin/env bash
if [[ "$*" == *"ls-remote"* ]]; then
    exit 0
elif [[ "$*" == *"clone"* ]]; then
    if [[ "$*" == *"izumi-agent"* ]]; then
        mkdir -p "/tmp/izumi-agent/.venv/bin"
        mkdir -p "/tmp/izumi-agent/scripts"
        cat << 'SUB_EOF' > "/tmp/izumi-agent/scripts/deploy_to_agent_engine.py"
print("Mock deploy script created")
SUB_EOF
    else
        eval "last_arg=\${$#}"
        mkdir -p "$last_arg/infrastructure/modules"
        mkdir -p "$last_arg/backend"
        mkdir -p "$last_arg/frontend"
        touch "$last_arg/bootstrap.sh"
    fi
    exit 0
elif [[ "$*" == *"branch --show-current"* || "$*" == *"rev-parse"* || "$*" == *"show-ref"* ]]; then
    echo "feature/infra-changes"
    exit 0
elif [[ "$*" == *"remote get-url"* ]]; then
    echo "https://github.com/GoogleCloudPlatform/gcc-creative-studio.git"
    exit 0
fi
exit 0
EOF
chmod +x "${MOCK_BIN}/git"

cat << 'EOF' > "${MOCK_BIN}/curl"
#!/usr/bin/env bash
echo '{"oauthClientId":"999999999999-mockedclientid.apps.googleusercontent.com"}'
exit 0
EOF
chmod +x "${MOCK_BIN}/curl"

cat << 'EOF' > "${MOCK_BIN}/uv"
#!/usr/bin/env bash
if [[ "$*" == *"venv"* ]]; then
    eval "last_arg=\${$#}"
    mkdir -p "$last_arg/bin"
    cat << 'SUB_EOF' > "$last_arg/bin/python"
#!/usr/bin/env bash
echo "projects/creative-studio-mock-project/locations/us-central1/reasoningEngines/12345678"
exit 0
SUB_EOF
    chmod +x "$last_arg/bin/python"
fi
echo "uv mock executed successfully."
exit 0
EOF
chmod +x "${MOCK_BIN}/uv"

# Inject MOCK_BIN at head of PATH
export PATH="${MOCK_BIN}:${PATH}"
info "Mock cloud CLI environment activated on PATH."

# --- Configure Test Profile in Home Directory ---
MOCK_PROFILE_DIR="${HOME}/.cstudio/profiles"
mkdir -p "${MOCK_PROFILE_DIR}"
TEST_PROFILE_PATH="${MOCK_PROFILE_DIR}/test_automated.cstudio_bootstrap.conf"

cat <<EOF > "${TEST_PROFILE_PATH}"
GCP_PROJECT_ID="creative-studio-mock-project"
GITHUB_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio.git"
GITHUB_BRANCH="feature/infra-changes"
ENV_NAME="dev-test"
GITHUB_CONN_NAME="gh-mock-conn-test"
AUTO_OAUTH_CLIENT_ID="999999999999-mockedclientid.apps.googleusercontent.com"
LAST_COMPLETED_STEP=4
REPO_ROOT="${TEST_WORKSPACE}/gcc-creative-studio"
EOF
info "Initialized simulated deployment profile at: ${TEST_PROFILE_PATH}"

# --- TEST CASE 1: Verify Non-Interactive Execution & Parameter Seeding ---
info "Executing TEST CASE 1: Running bootstrap.sh against test profile via CLI flags..."
cd "${TEST_WORKSPACE}/gcc-creative-studio"

# Execute in automated mode without tty interaction
if ! bash ./bootstrap.sh --profile "test_automated.cstudio_bootstrap.conf" --auto-approve > "${TEST_WORKSPACE}/test_output.log" 2>&1; then
    cat "${TEST_WORKSPACE}/test_output.log" >&2
    fail "bootstrap.sh failed during automated execution!"
fi
success "TEST CASE 1 PASSED: Script completed uninterrupted without prompting!"

# --- TEST CASE 2: Verify .tfvars Generation & Firebase Hosting Site ID Persistence ---
info "Executing TEST CASE 2: Verifying self-healing .tfvars generation and hosting domain binding..."

TFVARS_FILE="${TEST_WORKSPACE}/gcc-creative-studio/infrastructure/dev-test.tfvars"
if [ ! -f "${TFVARS_FILE}" ]; then
    cat "${TEST_WORKSPACE}/test_output.log" >&2
    fail "Expected file ${TFVARS_FILE} was not generated!"
fi

# Assert required parameter bindings exist in .tfvars
grep -q 'project_id[[:space:]]*=[[:space:]]*"creative-studio-mock-project"' "${TFVARS_FILE}" || { cat "${TEST_WORKSPACE}/test_output.log" >&2; fail "project_id missing from .tfvars!"; }
grep -q 'region[[:space:]]*=[[:space:]]*"us-central1"' "${TFVARS_FILE}" || { cat "${TEST_WORKSPACE}/test_output.log" >&2; fail "region missing from .tfvars!"; }
grep -q 'resource_prefix[[:space:]]*=[[:space:]]*"cs"' "${TFVARS_FILE}" || { cat "${TEST_WORKSPACE}/test_output.log" >&2; fail "resource_prefix missing from .tfvars!"; }
grep -q 'firebase_site_id[[:space:]]*=[[:space:]]*"creative-studio-mock-f9d5d"' "${TFVARS_FILE}" || { cat "${TEST_WORKSPACE}/test_output.log" >&2; fail "firebase_site_id (mocked domain) missing from .tfvars!"; }

# Assert hosting domain is properly saved into persistent home profile (quote-agnostic match)
if ! grep -q 'AUTO_FIREBASE_SITE_ID=.*creative-studio-mock-f9d5d' "${TEST_PROFILE_PATH}"; then
    echo "=== TEST OUTPUT LOG ===" >&2
    cat "${TEST_WORKSPACE}/test_output.log" >&2
    echo "=== PROFILE CONTENTS ===" >&2
    cat "${TEST_PROFILE_PATH}" >&2
    fail "AUTO_FIREBASE_SITE_ID was not saved into persistent profile!"
fi
success "TEST CASE 2 PASSED: .tfvars generated with verified root parameters and hosting domain persisted!"

# --- TEST CASE 3: Verify Resumption from Late Stage (Step 10) ---
info "Executing TEST CASE 3: Verifying idempotent resumption from late stage..."
sed -i.bak 's/LAST_COMPLETED_STEP=.*/LAST_COMPLETED_STEP=9/g' "${TEST_PROFILE_PATH}" && rm -f "${TEST_PROFILE_PATH}.bak"

if ! bash ./bootstrap.sh --profile "test_automated.cstudio_bootstrap.conf" --auto-approve > "${TEST_WORKSPACE}/test_resumption.log" 2>&1; then
    cat "${TEST_WORKSPACE}/test_resumption.log" >&2
    fail "bootstrap.sh failed during intermediate stage resumption!"
fi
success "TEST CASE 3 PASSED: Resumed from Step 10 cleanly without directory traversal errors!"

# --- TEST CASE 4: Verify Stdin ('curl | bash') Invocation from External Directory ---
info "Executing TEST CASE 4: Simulating stdin ('curl | bash') invocation from external directory..."
CURL_TEST_DIR="${TEST_WORKSPACE}/curl_simulation_workspace"
mkdir -p "${CURL_TEST_DIR}"
cd "${CURL_TEST_DIR}"

CURL_PROFILE_PATH="${MOCK_PROFILE_DIR}/test_curl_simulation.cstudio_bootstrap.conf"
cat <<EOF > "${CURL_PROFILE_PATH}"
GCP_PROJECT_ID="creative-studio-mock-project"
GITHUB_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio.git"
GITHUB_BRANCH="feature/infra-changes"
ENV_NAME="dev-curl-test"
GITHUB_CONN_NAME="gh-mock-conn-test"
AUTO_OAUTH_CLIENT_ID="999999999999-mockedclientid.apps.googleusercontent.com"
LAST_COMPLETED_STEP=3
EOF

# Simulate curl piping script into bash -s from external workspace
if ! cat "${BOOTSTRAP_SCRIPT}" | bash -s -- --profile "test_curl_simulation.cstudio_bootstrap.conf" --auto-approve > "${CURL_TEST_DIR}/test_curl.log" 2>&1; then
    cat "${CURL_TEST_DIR}/test_curl.log" >&2
    fail "bootstrap.sh failed during simulated stdin ('curl | bash') invocation!"
fi

# Assert REPO_ROOT accurately locked onto cloned repository inside external workspace
grep -q "REPO_ROOT=.*${CURL_TEST_DIR}/gcc-creative-studio" "${CURL_PROFILE_PATH}" || { cat "${CURL_TEST_DIR}/test_curl.log" >&2; fail "REPO_ROOT was not correctly resolved during stdin invocation!"; }
success "TEST CASE 4 PASSED: Stdin ('curl | bash') style invocation correctly resolved path and completed cleanly!"

# --- TEST CASE 5: Verify Parent Directory Invocation ('bash gcc-creative-studio/bootstrap.sh') ---
info "Executing TEST CASE 5: Simulating parent directory CLI invocation ('bash gcc-creative-studio/bootstrap.sh')..."
PARENT_TEST_DIR="${TEST_WORKSPACE}/parent_simulation_workspace"
mkdir -p "${PARENT_TEST_DIR}/gcc-creative-studio/infrastructure/modules"
mkdir -p "${PARENT_TEST_DIR}/gcc-creative-studio/backend"
mkdir -p "${PARENT_TEST_DIR}/gcc-creative-studio/frontend"
cp "${BOOTSTRAP_SCRIPT}" "${PARENT_TEST_DIR}/gcc-creative-studio/bootstrap.sh"
chmod +x "${PARENT_TEST_DIR}/gcc-creative-studio/bootstrap.sh"
cd "${PARENT_TEST_DIR}"

PARENT_PROFILE_PATH="${MOCK_PROFILE_DIR}/test_parent_simulation.cstudio_bootstrap.conf"
cat <<EOF > "${PARENT_PROFILE_PATH}"
GCP_PROJECT_ID="creative-studio-mock-project"
GITHUB_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio.git"
GITHUB_BRANCH="feature/infra-changes"
ENV_NAME="dev-parent-test"
GITHUB_CONN_NAME="gh-mock-conn-test"
AUTO_OAUTH_CLIENT_ID="999999999999-mockedclientid.apps.googleusercontent.com"
LAST_COMPLETED_STEP=9
EOF
touch "${PARENT_TEST_DIR}/gcc-creative-studio/infrastructure/dev-parent-test.tfvars"

if ! bash gcc-creative-studio/bootstrap.sh --profile "test_parent_simulation.cstudio_bootstrap.conf" --auto-approve > "${PARENT_TEST_DIR}/test_parent.log" 2>&1; then
    cat "${PARENT_TEST_DIR}/test_parent.log" >&2
    fail "bootstrap.sh failed during parent directory invocation ('bash gcc-creative-studio/bootstrap.sh')!"
fi

# Assert REPO_ROOT dynamically resolved via script directory lookup without throwing cd /infrastructure errors
grep -q "REPO_ROOT=.*${PARENT_TEST_DIR}/gcc-creative-studio" "${PARENT_PROFILE_PATH}" || { cat "${PARENT_TEST_DIR}/test_parent.log" >&2; fail "REPO_ROOT was not correctly resolved during parent directory invocation!"; }
success "TEST CASE 5 PASSED: Parent directory invocation ('bash gcc-creative-studio/bootstrap.sh') dynamically resolved path and completed cleanly!"

# Clean up test profiles from user's actual home folder
rm -f "${TEST_PROFILE_PATH}" "${CURL_PROFILE_PATH}" "${PARENT_PROFILE_PATH}"

echo -e "\n${C_GREEN}============================================================${C_RESET}"
echo -e "${C_GREEN} 🎉 ALL OFFLINE BOOTSTRAP TESTS PASSED SUCCESSFULLY! 🎉 ${C_RESET}"
echo -e "${C_GREEN}============================================================${C_RESET}"
exit 0
