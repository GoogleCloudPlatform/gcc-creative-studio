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

locals {

  # The format requires: REGION-docker.pkg.dev / PROJECT_ID / PROXY_REPO_ID / GH_ORG / GH_REPO / IMAGE_NAME
  # Notice we omit 'ghcr.io/' because the remote repo configuration handles that root domain mapping automatically.
  cloud_run_image_url = "${var.region}-docker.pkg.dev/${var.project_id}/${var.ar_repo_id}/${var.github_org_or_user}/${var.github_repo_name}/backend:${var.image_tag}"

  
  # Merge hardcoded standard env vars with user-provided ones
  all_env_vars = merge(
    {
      "INSTANCE_CONNECTION_NAME"      = var.cloud_sql_connection_name
      "DB_HOST"                       = "/cloudsql/${var.cloud_sql_connection_name}"
      "DB_NAME"                       = var.db_name
      "DB_USER"                       = var.db_user
      "BACKEND_SERVICE_ACCOUNT_EMAIL" = google_service_account.run_sa.email
    },
    var.container_env_vars
  )

  # Merge hardcoded secrets with user-provided ones
  all_secrets = merge(
    {
      "DB_PASS" = var.db_secret_id
    },
    var.runtime_secrets
  )
}

resource "google_cloud_run_v2_service" "backend" {
  name                = var.service_name
  location            = var.region
  custom_audiences    = var.custom_audiences
  deletion_protection = false
  
  # Lock network to the Load Balancer ONLY
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = google_service_account.run_sa.email
    
    # Workaround for "Domain Restricted Sharing" org policies
    annotations = {
      "run.googleapis.com/invoker-iam-disabled" = "true"
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.cloud_sql_connection_name]
      }
    }

    containers {
      image = local.cloud_run_image_url

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      # non secret env vars
      dynamic "env" {
        for_each = local.all_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      # secrets
      dynamic "env" {
        for_each = local.all_secrets
        content {
          name = env.key # The ENV_VAR_NAME
          value_source {
            secret_key_ref {
              secret  = env.value # The SECRET_NAME
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name = "cloudsql"
        mount_path = "/cloudsql"
      }

      # Startup and Liveness Probes
      startup_probe {
        http_get {
          path = "/health/ready" # Your API's health endpoint
          port = 8080
        }
        initial_delay_seconds = 2
        timeout_seconds       = 1
        failure_threshold     = 3
      }
      
      liveness_probe {
        http_get {
          path = "/health/live"
        }
        period_seconds = 10
      }

    }
    scaling {
      min_instance_count = var.scaling_min_instances
      max_instance_count = var.scaling_max_instances
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

resource "google_service_account" "run_sa" {
  account_id   = "${var.resource_prefix}-${var.environment}-run"
  display_name = "SA for ${var.service_name} (${var.environment}) Runtime"
}

resource "google_project_iam_member" "run_sa_project_bindings" {
  for_each = toset(var.run_sa_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_service_account_iam_member" "run_sa_act_as_self" {
  service_account_id = google_service_account.run_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.run_sa.email}"
}

# The Serverless NEG targeting this specific service
resource "google_compute_region_network_endpoint_group" "serverless_neg" {
  name                  = "${var.resource_prefix}-${var.environment}-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.backend.name
  }
}