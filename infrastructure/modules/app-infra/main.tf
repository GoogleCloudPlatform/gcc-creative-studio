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

# --- Shared Platform Resources ---

resource "google_storage_bucket" "genmedia" {
  name                        = "${var.project_id}-cs-${var.environment}-bucket"
  location                    = var.region
  uniform_bucket_level_access = true
  project                     = var.project_id

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
  project      = var.project_id
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

# --- Cloud Build Repository Connection ---
resource "google_cloudbuildv2_repository" "source_repo" {
  provider          = google-beta
  name              = var.build_repository_id
  location          = var.region
  project           = var.project_id
  parent_connection = "projects/${var.project_id}/locations/${var.region}/connections/${var.github_conn_name}"
  remote_uri        = "https://github.com/${var.github_repo_owner}/${var.github_repo_name}.git"
}

# --- Module Calls ---

# 1. Network
module "network" {
  source = "../network"

  project_id                  = var.project_id
  region                      = var.region
  network_name                = var.network_name
  subnet_cidr                 = var.subnet_cidr
  enable_nat                  = var.enable_nat
  vpc_connector_machine_type  = var.vpc_connector_machine_type
  vpc_connector_min_instances = var.vpc_connector_min_instances
  vpc_connector_max_instances = var.vpc_connector_max_instances
  peering_prefix_length       = var.peering_prefix_length
  internal_source_ranges      = var.internal_source_ranges
}

# 2. Database
module "database" {
  source = "../database"

  project_id                     = var.project_id
  region                         = var.region
  vpc_network_id                 = module.network.network_id
  db_name                        = var.db_name
  db_user                        = var.db_user
  db_password                    = var.db_password
  tier                           = var.db_tier
  database_version               = var.database_version
  disk_size                      = var.db_disk_size
  disk_type                      = var.db_disk_type
  disk_autoresize                = var.db_disk_autoresize
  availability_type              = var.db_availability_type
  deletion_protection            = var.db_deletion_protection
  backup_enabled                 = var.db_backup_enabled
  point_in_time_recovery_enabled = var.db_point_in_time_recovery_enabled
  query_insights_enabled         = var.db_query_insights_enabled
  database_flags                 = var.db_database_flags

  # Ensure DB creation waits for VPC peering to be established
  depends_on = [module.network]
}

# 3. Build (Backend Trigger)
module "build" {
  source = "../build"

  project_id           = var.project_id
  region               = var.region
  repository_id        = var.build_repository_id
  service_name         = var.backend_service_name
  source_repository_id = google_cloudbuildv2_repository.source_repo.id
  github_branch_name   = var.github_branch_name
  cloudbuild_yaml_path = var.backend_cloudbuild_yaml_path
  included_files_glob  = var.backend_included_files_glob
  build_substitutions  = var.backend_build_substitutions
}

# 4. Backend (Cloud Run)
module "backend" {
  source = "../backend"

  project_id                = var.project_id
  region                    = var.region
  service_name              = var.backend_service_name
  image                     = var.backend_image
  vpc_connector_id          = module.network.connector_id
  cloud_sql_connection_name = module.database.connection_name
  db_name                   = module.database.db_name
  db_user                   = module.database.db_user
  db_secret_id              = "creative-studio-db-password" # Assuming this name as per bootstrap
  cpu                       = var.backend_cpu
  memory                    = var.backend_memory
  min_instances             = var.backend_min_instances
  max_instances             = var.backend_max_instances
  container_env_vars        = merge(
    var.backend_env_vars,
    {
      "GENMEDIA_BUCKET"  = google_storage_bucket.genmedia.name
      "SIGNING_SA_EMAIL" = google_service_account.bucket_reader_sa.email
    }
  )
}

# 5. Frontend (Firebase Hosting)
module "frontend" {
  source = "../frontend"

  project_id           = var.project_id
  firebase_project_id  = var.firebase_project_id
  firebase_site_id     = var.firebase_site_id
  custom_domain        = var.custom_domain
  enable_trigger       = var.frontend_enable_trigger
  region               = var.region
  cloudbuild_yaml_path = var.frontend_cloudbuild_yaml_path
  build_substitutions  = var.frontend_build_substitutions
  source_repository_id = google_cloudbuildv2_repository.source_repo.id
  github_branch_name   = var.github_branch_name
  included_files_glob  = var.frontend_included_files_glob
  environment          = var.environment
  service_name         = var.firebase_site_id
}

# 6. Secrets (Frontend)
module "frontend_secrets" {
  source = "../secrets"

  project_id        = var.project_id
  secret_names      = var.frontend_secrets
  accessor_sa_email = "frontend-${var.environment}-trig@${var.project_id}.iam.gserviceaccount.com"
}

# 7. Secrets (Backend)
module "backend_secrets" {
  source = "../secrets"

  project_id        = var.project_id
  secret_names      = var.backend_secrets
  accessor_sa_email = "${var.backend_service_name}-sa@${var.project_id}.iam.gserviceaccount.com"
}

# 8. IAM Module for cross-module and project-level bindings
module "iam" {
  source     = "../iam"
  project_id = var.project_id

  project_roles = {
    # Allow trigger SA to act as runtime SA
    "roles/iam.serviceAccountUser" = [
      "serviceAccount:${module.build.trigger_service_account_email}"
    ]
    # Allow frontend trigger to view backend service (as in original)
    "roles/run.viewer" = compact([
      var.frontend_enable_trigger ? "serviceAccount:${module.frontend.trigger_service_account_email}" : ""
    ])
  }
}
