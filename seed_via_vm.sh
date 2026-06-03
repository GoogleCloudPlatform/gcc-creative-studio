#!/bin/bash
# A script to fully automate the creation of a temporary VM, database seeding, and cleanup.
# Run this from your Google Cloud Shell.

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
export PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    fail "Could not determine active gcloud project. Please run 'gcloud config set project [ID]' first."
fi

export PROJECT_NUM=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
export COMPUTE_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

info "Using Project ID: ${C_YELLOW}${PROJECT_ID}${C_RESET} (${PROJECT_NUM})"

# ==========================================
# Step 1: Grant Permissions to Compute SA
# ==========================================
step_1() {
    info "Granting required permissions to default Compute Engine Service Account..."
    
    # 1. Secret Manager Access
    gcloud secrets add-iam-policy-binding "creative-studio-db-password" \
        --role="roles/secretmanager.secretAccessor" \
        --member="serviceAccount:$COMPUTE_SA" \
        --project="$PROJECT_ID" --quiet

    # 2. Cloud SQL Client
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --role="roles/cloudsql.client" \
        --member="serviceAccount:$COMPUTE_SA" \
        --condition=None --quiet

    # 3. Cloud SQL Viewer
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --role="roles/cloudsql.viewer" \
        --member="serviceAccount:$COMPUTE_SA" \
        --condition=None --quiet

    # 4. GCS Object Admin
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --role="roles/storage.objectAdmin" \
        --member="serviceAccount:$COMPUTE_SA" \
        --condition=None --quiet

    success "Permissions granted to default Compute SA."
}

# ==========================================
# Step 2: Setup Temporary Network Pathways
# ==========================================
step_2() {
    info "Setting up temporary networking pathways (Router, NAT, and Firewall)..."
    
    # Create Router
    gcloud compute routers create temp-router \
        --network="cs-vpc-development" \
        --region="us-central1" \
        --project="$PROJECT_ID"

    # Create NAT Gateway
    gcloud compute routers nats create temp-nat \
        --router="temp-router" \
        --region="us-central1" \
        --nat-custom-subnet-ip-ranges="cs-subnet-development" \
        --auto-allocate-nat-external-ips \
        --project="$PROJECT_ID"

    # Allow Ingress from Google IAP range to port 22
    gcloud compute firewall-rules create temp-allow-iap-ssh \
        --network="cs-vpc-development" \
        --allow=tcp:22 \
        --source-ranges="35.235.240.0/20" \
        --project="$PROJECT_ID"

    success "Temporary network pathways set up."
}

# ==========================================
# Step 3: Create VM, Seed, and Execute
# ==========================================
step_3() {
    info "Creating temporary seed VM (temp-seed-vm)..."
    
    gcloud compute instances create temp-seed-vm \
        --zone="us-central1-a" \
        --machine-type="e2-micro" \
        --network="cs-vpc-development" \
        --subnet="cs-subnet-development" \
        --no-address \
        --scopes="https://www.googleapis.com/auth/cloud-platform" \
        --shielded-secure-boot \
        --shielded-vtpm \
        --shielded-integrity-monitoring \
        --metadata="startup-script=sudo apt-get update && sudo apt-get install -y git" \
        --project="$PROJECT_ID"

    success "VM created successfully."
    
    info "Waiting for VM to initialize (30 seconds)..."
    sleep 30

    info "SSHing into temp-seed-vm to run database seeding..."
    
    # Run the seeding commands inside the VM via SSH
    gcloud compute ssh temp-seed-vm \
        --zone="us-central1-a" \
        --tunnel-through-iap \
        --project="$PROJECT_ID" \
        --command="
            set -e
            echo '=== Inside VM: Waiting for Git to install ==='
            for i in {1..30}; do
                if command -v git >/dev/null 2>&1; then
                    break
                fi
                echo -n '.'
                sleep 2
            done
            if ! command -v git >/dev/null 2>&1; then
                echo 'Git installation timed out!'
                exit 1
            fi
            echo 'Git is ready!'
            echo '=== Inside VM: Cloning Repository ==='
            git clone -b DRS-compliance https://github.com/PKAgarwal157/gcc-creative-studio.git ~/gcc-creative-studio
            cd ~/gcc-creative-studio
            chmod +x seed_only.sh
            echo '=== Inside VM: Running Seeding Script ==='
            ./seed_only.sh
        "

    success "Database seeding finished successfully."
}

# ==========================================
# Step 4: Cleanup
# ==========================================
cleanup() {
    info "Cleaning up temporary resources..."
    
    # Delete VM
    gcloud compute instances delete temp-seed-vm --zone="us-central1-a" --project="$PROJECT_ID" --quiet || warn "Failed to delete VM"

    # Delete Firewall Rule
    gcloud compute firewall-rules delete temp-allow-iap-ssh --project="$PROJECT_ID" --quiet || warn "Failed to delete Firewall rule"

    # Delete NAT Gateway and Router
    gcloud compute routers nats delete temp-nat --router="temp-router" --region="us-central1" --project="$PROJECT_ID" --quiet || warn "Failed to delete NAT Gateway"
    gcloud compute routers delete temp-router --region="us-central1" --project="$PROJECT_ID" --quiet || warn "Failed to delete Router"

    success "Cleanup complete."
}

# Run the lifecycle
trap cleanup EXIT
step_1
step_2
step_3
