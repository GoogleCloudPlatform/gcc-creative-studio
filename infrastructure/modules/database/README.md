# Database Module (Cloud SQL)

This module creates a Cloud SQL Postgres instance with Private Services Access (Private IP only), a default database, and a default user. It also stores the generated password in Secret Manager.

## Features

- Creates Cloud SQL instance with Private IP.
- Generates random password and stores it in Secret Manager securely (write-only, not in state).
- Enables IAM authentication.
- Configures backups and point-in-time recovery.

## Usage

```hcl
module "database" {
  source = "./modules/database"

  project_id      = "my-project-id"
  region          = "us-central1"
  resource_prefix = "cstudio"
  environment     = "dev"
  vpc_id          = module.network.network_id
  
  # Ensure peering is ready
  psa_connection_dependency = module.network.peering_completed
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | The ID of the project in which resources will be created. | `string` | n/a | yes |
| `region` | The region in which resources will be created. | `string` | n/a | yes |
| `resource_prefix` | Standard naming prefix assigned to the deployment. | `string` | n/a | yes |
| `environment` | Deployment environment identifier. | `string` | n/a | yes |
| `vpc_id` | The VPC network ID where the Cloud SQL instance will be connected. | `string` | n/a | yes |
| `psa_connection_dependency` | Dependency on the Private Services Access connection. | `any` | `null` | no |
| `database_version` | The database version to use. | `string` | `"POSTGRES_18"` | no |
| `db_tier` | The machine tier/type for the Cloud SQL instance. | `string` | `"db-c4a-highmem-4"` | no |
| `db_availability_type` | The availability type (ZONAL or REGIONAL). | `string` | `"REGIONAL"` | no |
| `initial_disk_size` | The initial disk size in GB. | `number` | `10` | no |
| `max_disk_size` | The maximum disk size in GB for auto-resizing. | `number` | `100` | no |
| `labels` | A map of user labels to assign to the instance. | `map(string)` | `{}` | no |
| `db_name` | The name of the default database to create. | `string` | `"creative_studio"` | no |
| `db_user` | The name of the default database user to create. | `string` | `"app_user"` | no |
| `db_password_version` | The version integer for the database user password. | `number` | `1` | no |
| `deletion_protection` | Whether to enable deletion protection. | `bool` | `false` | no |

## Outputs

| Name | Description |
|------|-------------|
| `instance_name` | The name of the Cloud SQL instance. |
| `instance_connection_name` | The connection name of the Cloud SQL instance. |
| `private_ip_address` | The private IP address assigned to the Cloud SQL instance. |
| `database_name` | The name of the created default database. |
| `user_name` | The name of the created database user. |
| `secret_id` | The ID of the Secret Manager secret storing the password. |
| `secret_name` | The resource name of the Secret Manager secret. |
