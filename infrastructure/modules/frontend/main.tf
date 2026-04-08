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

# Creates the Firebase Hosting site
resource "google_firebase_hosting_site" "this" {
  provider = google-beta
  project  = var.firebase_project_id
  site_id  = var.firebase_site_id
}

# Conditional Custom Domain
resource "google_firebase_hosting_custom_domain" "this" {
  count       = var.custom_domain != null ? 1 : 0
  provider    = google-beta
  project     = var.firebase_project_id
  site_id     = google_firebase_hosting_site.this.site_id
  domain_name = var.custom_domain
}

# Conditional Build Trigger and IAM Bindings

resource "google_service_account" "trigger_sa" {
  count        = var.enable_trigger ? 1 : 0
  account_id   = "${var.resource_prefix}-${var.environment}-trig"
  display_name = "SA for ${var.service_name} Trigger (${var.environment})"
  project      = var.project_id
}

resource "google_cloudbuild_trigger" "this" {
  count           = var.enable_trigger ? 1 : 0
  name            = "${var.service_name}-trigger"
  location        = var.region
  service_account = google_service_account.trigger_sa[0].id
  filename        = var.cloudbuild_yaml_path
  project         = var.project_id
  substitutions   = var.build_substitutions

  repository_event_config {
    repository = var.source_repository_id
    push {
      branch = "^${var.github_branch_name}$"
    }
  }

  included_files = var.included_files_glob
}

resource "google_project_iam_member" "firebase_admin" {
  count   = var.enable_trigger ? 1 : 0
  project = var.project_id
  role    = "roles/firebasehosting.admin"
  member  = "serviceAccount:${google_service_account.trigger_sa[0].email}"
}

resource "google_project_iam_member" "logging_writer" {
  count   = var.enable_trigger ? 1 : 0
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.trigger_sa[0].email}"
}
