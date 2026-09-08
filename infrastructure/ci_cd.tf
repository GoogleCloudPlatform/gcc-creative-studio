# --- GitHub Repository Connection ---
resource "google_cloudbuildv2_repository" "source_repo" {
  provider          = google-beta
  name              = var.github_repo_name
  location          = var.region
  parent_connection = "projects/${var.project_id}/locations/${var.region}/connections/${var.github_conn_name}"
  remote_uri        = "https://github.com/${var.github_repo_owner}/${var.github_repo_name}.git"
}

# --- Cloud Build Trigger Service Account ---
resource "google_service_account" "trigger_sa" {
  account_id   = "${var.resource_prefix}-trig-sa"
  display_name = "Cloud Build Trigger Service Account"
}

# Give the trigger SA permission to deploy to Cloud Run
resource "google_project_iam_member" "run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to act as the backend service account
resource "google_service_account_iam_member" "backend_sa_user" {
  service_account_id = module.compute.service_account_name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to access secrets
resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to deploy to Vertex AI (Reasoning Engine)
resource "google_project_iam_member" "aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to act as the AI Agent service account
resource "google_service_account_iam_member" "agent_sa_user" {
  service_account_id = module.compute.agent_service_account_name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to read from the Cloud Build source bucket
resource "google_project_iam_member" "storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to deploy to Firebase Hosting
resource "google_project_iam_member" "firebase_admin" {
  project = var.project_id
  role    = "roles/firebasehosting.admin"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to write to Artifact Registry
resource "google_project_iam_member" "ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# Give the trigger SA permission to write logs
resource "google_project_iam_member" "logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.trigger_sa.email}"
}

# --- Frontend Trigger ---
resource "google_cloudbuild_trigger" "frontend_trigger" {
  name            = "${var.resource_prefix}-${var.environment}-frontend-trigger"
  location        = var.region
  service_account = google_service_account.trigger_sa.id
  filename        = "frontend/cloudbuild-deploy.yaml"
  substitutions = {
    _GCP_PROJECT_ID      = var.project_id
    _BACKEND_URL         = module.compute.service_uri
    _BACKEND_SERVICE_ID  = module.compute.service_name
    _FIREBASE_SITE_ID    = google_firebase_hosting_site.frontend.site_id
    _FE_SERVICE_NAME     = "${var.resource_prefix}-${var.environment}-frontend"
  }

  repository_event_config {
    repository = google_cloudbuildv2_repository.source_repo.id
    push {
      branch = "^${var.github_branch_name}$"
    }
  }

  included_files = ["frontend/**"]
}

# --- Backend Trigger ---
resource "google_cloudbuild_trigger" "backend_trigger" {
  name            = "${module.compute.service_name}-trigger"
  location        = var.region
  service_account = google_service_account.trigger_sa.id
  filename        = "backend/cloudbuild.yaml"
  substitutions = {
    _GCP_PROJECT_ID   = var.project_id
    _GCP_REGION       = var.region
    _REPO_NAME        = module.artifact.repository_name
    _SERVICE_NAME     = module.compute.service_name
    _DOCKER_IMAGE_URL = "${var.region}-docker.pkg.dev/${var.project_id}/${module.artifact.repository_name}/${var.backend_image_name}"
  }

  repository_event_config {
    repository = google_cloudbuildv2_repository.source_repo.id
    push {
      branch = "^${var.github_branch_name}$"
    }
  }

  included_files = ["backend/**"]
}
