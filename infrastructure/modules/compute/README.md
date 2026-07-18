# Compute Module (Cloud Run)

This module creates a Cloud Run service for the backend application, along with a service account and necessary IAM bindings. It also creates a Serverless Network Endpoint Group (NEG) for Load Balancer integration.

## Features

- Deploys a Cloud Run service with specified image and resources.
- Configures environment variables and secrets.
- Attaches Cloud SQL instance via Cloud SQL Auth Proxy (implicit in Cloud Run).
- Sets up probes (startup and liveness).
- Creates a Serverless NEG.

## Usage

```hcl
module "compute" {
  source = "./modules/compute"

  project_id      = "my-project-id"
  region          = "us-central1"
  environment     = "dev"
  resource_prefix = "cstudio"
  service_name    = "backend"
  
  # Image configuration
  ar_repo_id         = "ghcr-proxy"
  github_org_or_user = "my-org"
  github_repo_name   = "my-repo"
  image_tag          = "latest"

  cloud_sql_connection_name = module.database.instance_connection_name
  db_name                   = module.database.database_name
  db_user                   = module.database.user_name
  db_secret_id              = module.database.secret_id
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | The GCP project ID. | `string` | n/a | yes |
| `region` | The GCP region where resources will be created. | `string` | n/a | yes |
| `environment` | The deployment environment. | `string` | n/a | yes |
| `resource_prefix` | Prefix to be used for resource naming. | `string` | n/a | yes |
| `service_name` | The name of the Cloud Run service. | `string` | n/a | yes |
| `image_url` | The URL of the container image to deploy (fallback if not constructing). | `string` | n/a | yes |
| `ar_repo_id` | The Artifact Registry repository ID. | `string` | n/a | yes |
| `github_org_or_user` | The GitHub organization or user name. | `string` | n/a | yes |
| `github_repo_name` | The GitHub repository name. | `string` | n/a | yes |
| `image_tag` | The image tag to deploy. | `string` | n/a | yes |
| `custom_audiences` | Custom audiences for the Cloud Run service. | `list(string)` | `[]` | no |
| `cloud_sql_connection_name` | The connection name of the Cloud SQL instance. | `string` | n/a | yes |
| `db_name` | The name of the database to connect to. | `string` | n/a | yes |
| `db_user` | The database user for connection. | `string` | n/a | yes |
| `db_secret_id` | The Secret Manager secret ID containing the database password. | `string` | n/a | yes |
| `cpu` | CPU limit for the Cloud Run container. | `string` | `"1000m"` | no |
| `memory` | Memory limit for the Cloud Run container. | `string` | `"512Mi"` | no |
| `container_env_vars` | Map of non-secret environment variables. | `map(string)` | `{}` | no |
| `runtime_secrets` | Map of environment variable names to Secret Manager secret names. | `map(string)` | `{}` | no |
| `scaling_min_instances` | Minimum number of container instances. | `number` | `0` | no |
| `scaling_max_instances` | Maximum number of container instances. | `number` | `10` | no |
| `run_sa_project_roles` | List of IAM roles to assign to the Cloud Run service account. | `list(string)` | (see variables.tf) | no |

## Outputs

| Name | Description |
|------|-------------|
| `service_name` | The name of the Cloud Run service. |
| `service_uri` | The URI of the Cloud Run service. |
| `service_location` | The location/region of the Cloud Run service. |
| `service_account_email` | The email address of the runtime service account. |
| `service_account_name` | The fully-qualified name of the runtime service account. |
| `serverless_neg_id` | The fully qualified ID of the serverless network endpoint group. |
