data "google_project" "project" {
  project_id = var.project_id
}

locals {
  # Deterministic Cloud Run URL for the backend service.
  #
  # Built by hand rather than read from google_cloud_run_v2_service.backend.uri
  # because that service consumes this value in its own env block, and a
  # resource referencing its own attribute creates a Terraform dependency
  # cycle.
  #
  # Must stay in sync with the compute module's service_name, which is
  # "${var.resource_prefix}-${var.environment}-backend".
  backend_url = "https://${var.resource_prefix}-${var.environment}-backend-${data.google_project.project.number}.${var.region}.run.app"
}
