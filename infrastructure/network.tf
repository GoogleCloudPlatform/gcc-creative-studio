module "network" {
  source = "./modules/network"

  project_id      = var.project_id
  region          = var.region
  resource_prefix = var.resource_prefix
  environment     = var.environment
  cloud_run_cidr  = var.cloud_run_cidr
}

module "gateway" {
  source = "./modules/gateway"

  project_id      = var.project_id
  resource_prefix = var.resource_prefix
  environment     = var.environment
  domain_name     = var.domain_name

  # Connects the serverless NEG exposed from the compute bundle
  serverless_neg_id = module.compute.serverless_neg_id
}
