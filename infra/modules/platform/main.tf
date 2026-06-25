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

# --- Shared Platform Resources ---

resource "google_storage_bucket" "genmedia" {
  name                        = "${var.gcp_project_id}-cs-${var.environment}-bucket"
  location                    = var.gcp_region
  uniform_bucket_level_access = true

  cors {
    origin          = ["*"]
    method          = ["GET", "PUT", "POST", "DELETE", "HEAD", "OPTIONS"]
    response_header = ["Content-Type", "Access-Control-Allow-Origin", "x-goog-resumable", "Authorization", "Origin"]
    max_age_seconds = 3600
  }
}

resource "google_service_account" "bucket_reader_sa" {
  account_id   = "cs-${var.environment}-read"
  display_name = "SA for reading GenMedia (${var.environment}) bucket"
}

resource "google_storage_bucket_iam_member" "bucket_viewer_binding" {
  bucket = google_storage_bucket.genmedia.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.bucket_reader_sa.email}"
}

resource "google_storage_bucket_iam_member" "bucket_creator_binding" {
  bucket = google_storage_bucket.genmedia.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.bucket_reader_sa.email}"
}

data "google_project" "project" {
  project_id = var.gcp_project_id
}

# --- Predictable URLs & Environment Variables ---
locals {
  region_code  = join("", [for s in split("-", var.gcp_region) : substr(s, 0, 1)])
  
  # Use LB URL if IAP is enabled, otherwise use the direct Cloud Run URL
  backend_url = var.iap_oauth2_client_id != "" ? (var.domain_name != "" ? "https://${var.domain_name}" : "https://${module.iap_load_balancer[0].load_balancer_ip}") : "https://${var.backend_service_name}-${data.google_project.project.number}.${var.gcp_region}.run.app"

  frontend_url = "https://${var.firebase_site_id}.web.app" # Predictable Firebase URL

  backend_env_vars = merge(
    lookup(var.be_env_vars, "common", {}),
    lookup(var.be_env_vars, var.environment, {}),
    {
      "CORS_ORIGINS"           = "[\"${local.frontend_url}\"]"
      "GENMEDIA_BUCKET"        = google_storage_bucket.genmedia.name
      "SIGNING_SA_EMAIL"       = google_service_account.bucket_reader_sa.email
      "BACKEND_URL"            = local.backend_url
      "WORKFLOWS_EXECUTOR_URL" = "${local.backend_url}/api/workflows-executor"
      "IAP_EXPECTED_AUDIENCE"  = var.iap_expected_audience
    }
  )
}



# --- Cloud Build Repository Connection ---
resource "google_cloudbuildv2_repository" "source_repo" {
  provider          = google-beta
  name              = var.github_repo_name
  location          = var.gcp_region
  parent_connection = "projects/${var.gcp_project_id}/locations/${var.gcp_region}/connections/${var.github_conn_name}"
  remote_uri        = "https://github.com/${var.github_repo_owner}/${var.github_repo_name}.git"
}

# Postgres Database related
# 1. Read the Secret (Created by Bootstrap script)
data "google_secret_manager_secret_version" "db_password" {
  secret  = "creative-studio-db-password"
  project = var.gcp_project_id
  version = "latest"
}

# 2. Call PostgreSQL Module
module "postgresql" {
  source      = "../postgresql"
  project_id  = var.gcp_project_id
  region      = var.gcp_region
  
  # Pass the ACTUAL value to create the user
  db_password = data.google_secret_manager_secret_version.db_password.secret_data
}

# --- Service Module Calls ---
module "backend_service" {
  source = "../cloud-run-service"

  gcp_project_id        = var.gcp_project_id
  gcp_region            = var.gcp_region
  environment           = var.environment
  service_name          = var.backend_service_name
  resource_prefix       = "cs-be"
  github_conn_name      = var.github_conn_name
  github_repo_owner     = var.github_repo_owner
  github_repo_name      = var.github_repo_name
  github_branch_name    = var.github_branch_name
  cloudbuild_yaml_path  = "backend/cloudbuild.yaml"
  included_files_glob   = ["backend/**"]
  container_env_vars    = local.backend_env_vars
  runtime_secrets = var.backend_runtime_secrets
  custom_audiences      = var.backend_custom_audiences
  scaling_min_instances = 1
  source_repository_id = google_cloudbuildv2_repository.source_repo.id
  cpu = var.be_cpu
  memory = var.be_memory
  build_substitutions   = merge(var.be_build_substitutions,
    {
      _REGION = var.gcp_region
      _SERVICE_NAME = var.backend_service_name
    }
  )

  # database
  cloud_sql_connection_name = module.postgresql.connection_name
  db_name                   = module.postgresql.db_name
  db_user                   = module.postgresql.db_user
  
  # Pass the Secret ID reference (NOT the value) for Cloud Run
  db_secret_id              = "creative-studio-db-password"

  # Restrict ingress to Internal + GCLB if IAP is enabled
  ingress                   = var.iap_oauth2_client_id != "" ? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_ALL"
}



resource "google_firebase_project" "default" {
  provider = google-beta
  project = var.gcp_project_id
}

module "frontend_service" {
  source = "../cloud-run-service"

  gcp_project_id        = var.gcp_project_id
  gcp_region            = var.gcp_region
  environment           = var.environment
  service_name          = var.frontend_service_name
  resource_prefix       = "cs-fe"
  github_conn_name      = var.github_conn_name
  github_repo_owner     = var.github_repo_owner
  github_repo_name      = var.github_repo_name
  github_branch_name    = var.github_branch_name
  cloudbuild_yaml_path  = "frontend/cloudbuild-run.yaml"
  included_files_glob   = ["frontend/**"]
  container_env_vars    = {}
  runtime_secrets       = {}
  custom_audiences      = var.frontend_custom_audiences
  scaling_min_instances = 1
  source_repository_id  = google_cloudbuildv2_repository.source_repo.id
  cpu                   = "1000m"
  memory                = "1024Mi"
  build_substitutions   = merge(var.fe_build_substitutions,
    {
      _REGION = var.gcp_region
      _SERVICE_NAME = var.frontend_service_name
    }
  )

  # database (dummy values to satisfy variables)
  cloud_sql_connection_name = module.postgresql.connection_name
  db_name                   = module.postgresql.db_name
  db_user                   = module.postgresql.db_user
  db_secret_id              = "creative-studio-db-password"

  # Restrict ingress to Internal + GCLB
  ingress                   = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
}


module "frontend_secrets" {
  source = "../secret-manager"

  gcp_project_id    = var.gcp_project_id
  secret_names      = var.frontend_secrets
  accessor_sa_email = module.frontend_service.trigger_sa_email
}

module "backend_secrets" {
  source = "../secret-manager"

  gcp_project_id    = var.gcp_project_id
  secret_names      = var.backend_secrets
  accessor_sa_email = module.backend_service.trigger_sa_email
}

# --- Cross-Module Permissions ---

# Grant the Frontend's deploy trigger (which runs `firebase deploy`)
# permission to "get" the Backend's Cloud Run service to validate the rewrite rule.
resource "google_cloud_run_v2_service_iam_member" "fe_trigger_can_view_backend" {
  provider = google-beta
  project  = var.gcp_project_id
  name     = module.backend_service.service_name
  location = module.backend_service.location
  role     = "roles/run.viewer"
  member   = "serviceAccount:${module.frontend_service.trigger_sa_email}"
}

module "iap_load_balancer" {
  count  = var.iap_oauth2_client_id != "" ? 1 : 0
  source = "../iap-load-balancer"

  gcp_project_id           = var.gcp_project_id
  gcp_region               = var.gcp_region
  backend_service_name     = var.backend_service_name
  frontend_service_name    = var.frontend_service_name
  org_id                   = var.org_id
  entra_client_id          = var.entra_client_id
  entra_tenant_id          = var.entra_tenant_id
  entra_client_secret      = var.entra_client_secret
  iap_oauth2_client_id     = var.iap_oauth2_client_id
  iap_oauth2_client_secret = var.iap_oauth2_client_secret
  domain_name              = var.domain_name
  iap_access_members       = var.iap_access_members
  workforce_pool_id        = var.workforce_pool_id
}





