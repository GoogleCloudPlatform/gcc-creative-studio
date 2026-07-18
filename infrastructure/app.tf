# --- Artifact Registry Module ---
module "artifact" {
  source = "./modules/artifact"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment
}

# --- Compute Module (Cloud Run) ---
module "compute" {
  source = "./modules/compute"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment
  
  # The deployment script dynamically sets this value (e.g., "latest" or "v1.2.0")
  app_version     = var.app_version

  # Direct VPC routing configurations
  vpc_subnet_name = module.network.cloud_run_subnet_name
  database_ip     = module.database.private_ip_address
  
  # Dynamically construct the image URL using the injected app_version
  image_url       = "${module.artifact.repository_url}/${var.backend_image_name}:${var.app_version}"

  # References the list keys to configure secret environment block mappings
  secret_ids      = var.application_secrets
}