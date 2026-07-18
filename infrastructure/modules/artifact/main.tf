# infra/modules/artifact-registry/main.tf

resource "google_artifact_registry_repository" "cstudio_repo" {
  location      = var.region
  repository_id = "${var.resource_prefix}-${var.environment}-${var.repository_id}"
  description   = "Local private registry for Creative Studio with vulnerability scanning"
  format        = "DOCKER"

  # Explicitly enable vulnerability scanning
  # Note: This requires 'containerscanning.googleapis.com' to be enabled in the project
  # Ensure the mirror scans every image it caches
  vulnerability_scanning_config {
    enablement_config = "INHERITED" # Inherits project-level scan settings
  }

  # Cost Guardrail: Automatically purge cached layers unaccessed for 30 days
  cleanup_policies {
    id     = "delete-stale-cache"
    action = "DELETE"
    condition {
      older_than = var.cleanup_older_than
    }
  }

  labels = merge(var.labels, {
    component = "artifact-registry"
    region    = var.region
  })
}
