# Google Cloud Creative Studio: Private IP Deployment Guide

This guide details how to deploy Creative Studio with a **Private IP only** Cloud SQL database and configure the **Cloud Run** backend to access it securely using **Direct VPC egress**. 

Because the database does not expose a public IP, the initial setup is split into a **two-step lifecycle** to comply with network security boundaries.

---

## Architecture Overview
1.  **Private Database:** The Cloud SQL Postgres database has public access disabled (`ipv4_enabled = false`) and uses VPC Peering (`servicenetworking.googleapis.com`) to receive connections.
2.  **Serverless Egress:** Cloud Run backend service is connected directly to the VPC subnet using Direct VPC egress (`egress = "ALL_TRAFFIC"`), allowing it to query the database internally.
3.  **Secure Seeding:** Database seeding is performed using a temporary jump-box VM residing inside the VPC to securely load templates and assets.

---

## Setup Lifecycle (Step-by-Step)

### Phase 1: Deploy Infrastructure
Run the bootstrap script from your standard **Google Cloud Shell** session to deploy the network, database, secrets, and Cloud Build triggers:

```bash
curl -sSL https://raw.githubusercontent.com/PKAgarwal157/gcc-creative-studio/private-ip-cloudsql/bootstrap.sh | bash
```
*   When prompted for your fork URL, enter: `https://github.com/PKAgarwal157/gcc-creative-studio.git`
*   When prompted for the branch, enter: `private-ip-cloudsql`
*   *Note: This script will complete successfully but will skip the database seeding step, which must be run internally inside the VPC.*

---

### Phase 2: Grant Seeding Permissions
The temporary setup VM will run as the project's **Default Compute Engine Service Account**. Before creating the VM, run these commands in your **Cloud Shell** to grant the service account access to Secret Manager, Cloud SQL, and the Asset Storage bucket:

```bash
# Get your project details
export PROJECT_ID=$(gcloud config get project)
export PROJECT_NUM=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
export COMPUTE_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

# 1. Grant Secret Manager Access (to retrieve DB password)
gcloud secrets add-iam-policy-binding "creative-studio-db-password" \
    --role="roles/secretmanager.secretAccessor" \
    --member="serviceAccount:$COMPUTE_SA" \
    --project="$PROJECT_ID"

# 2. Grant Cloud SQL Client Access (to run the DB proxy)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --role="roles/cloudsql.client" \
    --member="serviceAccount:$COMPUTE_SA"

# 3. Grant Cloud SQL Viewer Access (to locate the DB instance connection name)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --role="roles/cloudsql.viewer" \
    --member="serviceAccount:$COMPUTE_SA"

# 4. Grant GCS Object Admin Access (to upload asset templates)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --role="roles/storage.objectAdmin" \
    --member="serviceAccount:$COMPUTE_SA"
```

---

### Phase 3: Run Database Seeding inside the VPC
Since your local terminal cannot reach the private IP of the database, you must run the seeding script from a temporary VM inside the VPC.

#### 1. Setup Temporary Networking & Firewall (in Cloud Shell)
Create a temporary Cloud Router, NAT Gateway (so the VM can pull dependencies from GitHub/npm), and a firewall rule to allow IAP SSH connections:

```bash
# Create Router
gcloud compute routers create temp-router \
    --network="cs-vpc-development" \
    --region="us-central1"

# Create NAT Gateway
gcloud compute routers nats create temp-nat \
    --router="temp-router" \
    --region="us-central1" \
    --nat-custom-subnet-ip-ranges="cs-subnet-development" \
    --auto-allocate-nat-external-ips

# Allow Ingress from Google IAP range to port 22
gcloud compute firewall-rules create temp-allow-iap-ssh \
    --network="cs-vpc-development" \
    --allow=tcp:22 \
    --source-ranges="35.235.240.0/20"
```

#### 2. Create the Temporary VM (in Cloud Shell)
Create a private VM (using `--no-address` to comply with external IP blocks, and Shielded VM configurations to comply with secure boot org policies):

```bash
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
    --metadata="startup-script=sudo apt-get update && sudo apt-get install -y git"
```

#### 3. Tunnel SSH and Run the Seeding Script
SSH into the private VM, clone the repository, and run the standalone seeding script:

```bash
# SSH into the VM (IAP tunnels securely to the private IP)
gcloud compute ssh temp-seed-vm --zone="us-central1-a" --tunnel-through-iap

# --- Inside the VM Session ---
# Clone the repository
git clone -b private-ip-cloudsql https://github.com/PKAgarwal157/gcc-creative-studio.git ~/gcc-creative-studio

# Navigate and execute the seeding script
cd ~/gcc-creative-studio
chmod +x seed_only.sh
./seed_only.sh

# Exit VM when complete
exit
```

---

### Phase 4: Clean Up & Trigger Deployments

#### 1. Delete Temporary Resources (in Cloud Shell)
Once seeding is complete, delete the temporary VM and network pathways to avoid costs:

```bash
# Delete VM
gcloud compute instances delete temp-seed-vm --zone="us-central1-a" --quiet

# Delete Firewall Rule
gcloud compute firewall-rules delete temp-allow-iap-ssh --quiet

# Delete NAT Gateway and Router
gcloud compute routers nats delete temp-nat --router="temp-router" --region="us-central1" --quiet
gcloud compute routers delete temp-router --region="us-central1" --quiet
```

#### 2. Optional: Manually Trigger Initial Builds (in Cloud Shell)
If you did not trigger the builds during the `bootstrap.sh` script execution (or if you need to redeploy the containers), you can trigger the Cloud Build pipelines manually using these commands:

```bash
# Trigger Backend
gcloud builds triggers run "cstudio-be-trigger" \
    --branch="private-ip-cloudsql" \
    --project="$PROJECT_ID" \
    --region="us-central1"

# Trigger Frontend
gcloud builds triggers run "${PROJECT_ID}-trigger" \
    --branch="private-ip-cloudsql" \
    --project="$PROJECT_ID" \
    --region="us-central1"
```
