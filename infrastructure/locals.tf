data "google_project" "project" {
  project_id = var.project_id
}

locals {
  # Cloud Run's deterministic URL: https://<service>-<project_number>.<region>.run.app
  # Built from plan-time values because module.compute.service_uri cannot be fed back
  # into the same module's env vars without a dependency cycle.
  backend_url = "https://${var.resource_prefix}-${var.environment}-backend-${data.google_project.project.number}.${var.region}.run.app"
}