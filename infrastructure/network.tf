module "network" {
  source = "./modules/network"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment
  cloud_run_cidr  = var.cloud_run_cidr

  depends_on = [google_project_service.apis]
}
