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

  # Merge hardcoded standard env vars with user-provided ones
  all_env_vars = merge(
    {
      "DB_HOST"                       = var.database_ip
      "BACKEND_SERVICE_ACCOUNT_EMAIL" = google_service_account.run_sa.email
    },
    var.container_env_vars
  )

  # Merge hardcoded secrets with user-provided ones
  all_secrets = merge(
    { for s in var.secret_ids : upper(s) => s },
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

    vpc_access {
      network_interfaces {
        network = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image_url

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


      # Startup and Liveness Probes
      startup_probe {
        http_get {
          path = "/" # Your API's health endpoint
          port = 8080
        }
        initial_delay_seconds = 2
        timeout_seconds       = 1
        failure_threshold     = 3
      }
      
      liveness_probe {
        http_get {
          path = "/"
          port = 8080
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

resource "google_service_account" "agent_sa" {
  account_id   = "${var.resource_prefix}-${var.environment}-agent"
  display_name = "Dedicated SA for AI Agents (${var.environment})"
}

# Grant Cloud Run Invoker role to the dedicated AI Agent Service Account
resource "google_cloud_run_v2_service_iam_member" "agent_engine_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}