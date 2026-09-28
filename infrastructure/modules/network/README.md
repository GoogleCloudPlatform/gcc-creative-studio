# Network Module (VPC & Peering)

This module creates a custom VPC network, a dedicated subnet for Cloud Run Direct VPC Egress, and establishes Private Services Access (VPC Peering) with Google-managed services (for Cloud SQL). It also adds baseline firewall rules to allow internal traffic.

## Features

- Custom VPC network with regional routing.
- Dedicated subnet for Cloud Run egress.
- Private Services Access connection for Cloud SQL.
- Firewall rule to allow internal traffic from Cloud Run subnet.

## Usage

```hcl
module "network" {
  source = "./modules/network"

  project_id      = "my-project-id"
  region          = "us-central1"
  resource_prefix = "cstudio"
  environment     = "dev"
  cloud_run_cidr  = "10.0.0.0/26"
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | The customer's Google Cloud project ID. | `string` | n/a | yes |
| `region` | The primary GCP region for network subnets. | `string` | n/a | yes |
| `resource_prefix` | Standard naming prefix assigned to the deployment. | `string` | n/a | yes |
| `environment` | Deployment environment identifier. | `string` | n/a | yes |
| `cloud_run_cidr` | Dedicated CIDR range for Cloud Run Direct VPC egress. | `string` | `"10.0.0.0/26"` | no |

## Outputs

| Name | Description |
|------|-------------|
| `network_id` | The fully qualified ID of the VPC network. |
| `network_name` | The simple name of the VPC network. |
| `cloud_run_subnet_name` | The name of the subnet allocated for Cloud Run. |
| `peering_completed` | Dependency trigger string confirming Private Services Access peering is active. |
