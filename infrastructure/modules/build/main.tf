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

# Service Account for Cloud Build Trigger
resource "google_service_account" "trigger_sa" {
  account_id   = "${var.service_name}-trigger-sa"
  display_name = "Service Account for Cloud Build Trigger ${var.service_name}"
  project      = var.project_id
}

# Artifact Registry Repository
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = var.repository_id
  description   = "Docker repository for ${var.service_name}"
  format        = "DOCKER"
  project       = var.project_id
}

# Cloud Build Trigger
resource "google_cloudbuild_trigger" "this" {
  name            = "${var.service_name}-trigger"
  location        = var.region
  service_account = google_service_account.trigger_sa.id
  filename        = var.cloudbuild_yaml_path
  project         = var.project_id

  substitutions   = merge(var.build_substitutions, {
    _REPO_NAME = google_artifact_registry_repository.repo.name
  })

  repository_event_config {
    repository = var.source_repository_id
    push {
      branch = "^${var.github_branch_name}$"
    }
  }

  included_files = var.included_files_glob
}

# IAM Bindings for Trigger SA

# Allow Cloud Build to write logs
resource "google_project_iam_member" "logging_writer_binding" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Allow Cloud Build to write to Artifact Registry
resource "google_artifact_registry_repository_iam_member" "ar_writer_binding" {
  location   = var.region
  repository = google_artifact_registry_repository.repo.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.trigger_sa.email}"
  project    = var.project_id
}

# Allow Cloud Build to manage Cloud Run services (deploy)
resource "google_project_iam_member" "run_developer_binding" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Note: The binding to allow the trigger SA to act as the Cloud Run runtime SA
# (roles/iam.serviceAccountUser) should be handled in the platform module
# because it requires referencing the service account created in the backend module.
