# --- Database Module ---
module "database" {
  source = "./modules/database"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment

  vpc_id = module.network.network_id

  # Guardrail: Explicitly wait for Private Services Access peering to 
  # finish provisioning before kicking off database creation.
  depends_on = [module.network.peering_completed]
}

# --- Storage Buckets ---
resource "google_storage_bucket" "genmedia" {
  name                        = "${var.project_id}-cs-${var.environment}-bucket"
  location                    = var.region
  uniform_bucket_level_access = true

  cors {
    origin          = ["*"]
    method          = ["GET", "PUT", "POST", "DELETE", "HEAD", "OPTIONS"]
    response_header = ["Content-Type", "Access-Control-Allow-Origin", "x-goog-resumable", "Authorization", "Origin"]
    max_age_seconds = 3600
  }
}

resource "google_service_account" "bucket_reader_sa" {
  account_id   = "cs-${var.environment}-bkt-reader"
  display_name = "SA for reading GenMedia (${var.environment}) bucket"
}

resource "google_storage_bucket_iam_member" "bucket_viewer_binding" {
  bucket = google_storage_bucket.genmedia.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.bucket_reader_sa.email}"
}

resource "google_storage_bucket_iam_member" "object_creator_binding" {
  bucket = google_storage_bucket.genmedia.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.bucket_reader_sa.email}"
}

# --- Secret Manager ---
# Create the "shell" for each secret in the specified application list
resource "google_secret_manager_secret" "app_secrets" {
  for_each = var.application_secrets

  project   = var.project_id
  secret_id = each.key

  replication {
    user_managed {
      replicas {
        location = var.region # restricted to the infra region
      }
    }
  }

  labels = merge(var.labels, {
    component  = "security"
    managed_by = "terraform"
  })
}

# Grant Secret Access directly to the Cloud Run Service Account
resource "google_secret_manager_secret_iam_member" "backend_accessor" {
  for_each = var.application_secrets

  project   = google_secret_manager_secret.app_secrets[each.key].project
  secret_id = google_secret_manager_secret.app_secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"

  # References backend module's service account output dynamically
  member = "serviceAccount:${module.compute.service_account_email}"
}
