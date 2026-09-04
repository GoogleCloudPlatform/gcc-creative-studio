# --- Artifact Registry Module ---
module "artifact" {
  source = "./modules/artifact"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment

  depends_on = [google_project_service.apis]
}

# --- Compute Module (Cloud Run) ---
module "compute" {
  source = "./modules/compute"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment
  depends_on      = [google_secret_manager_secret_version.app_secrets_placeholder]
  
  # The deployment script dynamically sets this value (e.g., "latest" or "v1.2.0")
  app_version     = var.app_version
  service_name    = "${var.resource_prefix}-${var.environment}-backend"

  # Direct VPC routing configurations
  vpc_network_name = module.network.network_name
  vpc_subnet_name = module.network.cloud_run_subnet_name
  database_ip     = module.database.private_ip_address
  
  # Dynamically construct the image URL. 
  # For initial deployments (when version is 'latest'), we use a Google placeholder image 
  # to prevent Cloud Run from crashing before the actual Docker image is built and pushed.
  image_url       = var.app_version == "latest" ? "us-docker.pkg.dev/cloudrun/container/hello" : "${module.artifact.repository_url}/${var.backend_image_name}:${var.app_version}"

  # References the list keys to configure secret environment block mappings
  secret_ids      = var.application_secrets

  container_env_vars = {
    PROJECT_ID                       = var.project_id
    DB_NAME                          = module.database.database_name
    DB_USER                          = module.database.user_name
    INSTANCE_CONNECTION_NAME         = module.database.instance_connection_name
    GENMEDIA_BUCKET                  = google_storage_bucket.genmedia.name
    AGENT_LOCATION                   = var.agent_location
  }

  runtime_secrets = {
    "DB_PASS" = module.database.secret_id
  }
}