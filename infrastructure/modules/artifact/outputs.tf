output "repository_id" {
  description = "The ID of the Artifact Registry repository."
  value       = google_artifact_registry_repository.cstudio_repo.repository_id
}

output "repository_name" {
  description = "The fully qualified name of the repository."
  value       = google_artifact_registry_repository.cstudio_repo.name
}


output "repository_url" {
  description = "The fully qualified URL to the local Docker repository."
  # Format: us-central1-docker.pkg.dev/project-id/cs-dev-repo
  value       = "${google_artifact_registry_repository.cstudio_repo.location}-docker.pkg.dev/${google_artifact_registry_repository.cstudio_repo.project}/${google_artifact_registry_repository.cstudio_repo.repository_id}"
}
