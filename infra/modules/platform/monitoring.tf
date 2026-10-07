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

# --- Sign-in alerts (opt-in) ---
# When enable_auth_alerts is true, Cloud Monitoring emails the deployer admin
# (ADMIN_USER_EMAIL in be_env_vars) when:
#   - Entra role sync fails (Microsoft Graph could not be read),
#   - the break-glass admin keeps admin only because of its exemption,
#   - the backend rejects many invalid IAP tokens in a short time.
# The backend writes these as structured logs with an event_type field.

locals {
  auth_alerts_enabled = var.enable_auth_alerts ? 1 : 0
  alert_email         = lookup(local.backend_env_vars, "ADMIN_USER_EMAIL", "")

  backend_logs = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${module.backend_service.service_name}\"",
  ])

  # One alert per log event that should reach a person on its own.
  auth_log_alerts = {
    entra_role_sync_failed = {
      name = "Entra role sync failed"
      doc  = "The backend could not read a user's Entra groups from Microsoft Graph, so it removed that user's admin and workflows roles until the next successful check. Check the Graph app secret, its permissions, and Microsoft Graph status."
    }
    break_glass_admin_retained = {
      name = "Break-glass admin kept admin by exemption"
      doc  = "The deployer admin would have lost the admin role (not in an Entra admin group, or Graph was down) and kept it only because of the break-glass exemption. Check whether this was expected."
    }
  }
}

resource "google_project_service" "monitoring" {
  count              = local.auth_alerts_enabled
  project            = var.gcp_project_id
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "admin_email" {
  count        = local.auth_alerts_enabled
  project      = var.gcp_project_id
  display_name = "Creative Studio admin (${var.environment})"
  type         = "email"
  labels = {
    email_address = local.alert_email
  }

  lifecycle {
    precondition {
      condition     = can(regex("^[^@\\s]+@[^@\\s]+$", local.alert_email))
      error_message = "enable_auth_alerts needs ADMIN_USER_EMAIL in be_env_vars to be a real email address."
    }
  }

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_alert_policy" "auth_log_event" {
  for_each     = var.enable_auth_alerts ? local.auth_log_alerts : {}
  project      = var.gcp_project_id
  display_name = "Creative Studio (${var.environment}): ${each.value.name}"
  combiner     = "OR"

  conditions {
    display_name = each.value.name
    condition_matched_log {
      filter = "${local.backend_logs} AND jsonPayload.event_type=\"${each.key}\""
    }
  }

  # Log-match alerts need a rate limit: at most one email per 5 minutes.
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }

  documentation {
    content   = each.value.doc
    mime_type = "text/markdown"
  }

  notification_channels = [google_monitoring_notification_channel.admin_email[0].id]
}

# Counts invalid IAP tokens the backend rejects, so a burst can be alerted on.
resource "google_logging_metric" "iap_invalid_token" {
  count   = local.auth_alerts_enabled
  project = var.gcp_project_id
  name    = "cs-${var.environment}-iap-invalid-token"
  filter  = "${local.backend_logs} AND jsonPayload.event_type=\"iap_invalid_token\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_monitoring_alert_policy" "iap_invalid_token_spike" {
  count        = local.auth_alerts_enabled
  project      = var.gcp_project_id
  display_name = "Creative Studio (${var.environment}): many invalid IAP tokens"
  combiner     = "OR"

  conditions {
    display_name = "More than ${var.invalid_token_alert_threshold} invalid IAP tokens in 5 minutes"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.iap_invalid_token[0].name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.invalid_token_alert_threshold
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  documentation {
    content   = "The backend rejected more invalid IAP tokens than usual. IAP normally blocks bad requests before they reach the backend, so this can mean a misconfigured IAP audience or someone calling the backend directly. Check the backend logs for event_type=\"iap_invalid_token\"."
    mime_type = "text/markdown"
  }

  notification_channels = [google_monitoring_notification_channel.admin_email[0].id]
}
