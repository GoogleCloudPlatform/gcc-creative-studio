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

resource "google_service_account" "run_sa" {
  account_id   = "${var.service_name}-sa"
  display_name = "Service Account for Cloud Run ${var.service_name}"
  project      = var.project_id
}

resource "google_cloud_run_v2_service" "this" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.run_sa.email

    containers {
      image = var.image
      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = var.cloud_sql_connection_name
      }
      env {
        name  = "DB_HOST"
        value = "/cloudsql/${var.cloud_sql_connection_name}"
      }
      env {
        name  = "DB_NAME"
        value = var.db_name
      }
      env {
        name  = "DB_USER"
        value = var.db_user
      }
      env {
        name = "DB_PASS"
        value_source {
          secret_key_ref {
            secret  = var.db_secret_id
            version = "latest"
          }
        }
      }

      # Dynamic block for additional non-secret env vars
      dynamic "env" {
        for_each = var.container_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.cloud_sql_connection_name]
      }
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }
  }

  deletion_protection = false
}

# IAM Bindings

# Access to database password secret
resource "google_secret_manager_secret_iam_member" "db_password_access" {
  secret_id = var.db_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run_sa.email}"
  project   = var.project_id
}

# Cloud SQL Client role to connect to the instance
resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}
