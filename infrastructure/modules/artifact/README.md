# Artifact Registry Module

This module creates a Google Artifact Registry repository configured as a remote proxy for an external registry (defaulting to GitHub Container Registry).

## Features

- Remote Repository mode to proxy external registries.
- Vulnerability scanning enabled (inherited from project).
- Cleanup policy to delete stale cached layers.

## Usage

```hcl
module "artifact" {
  source = "./modules/artifact"

  project_id      = "my-project-id"
  region          = "us-central1"
  resource_prefix = "cstudio"
  environment     = "dev"
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | The GCP project ID. | `string` | n/a | yes |
| `region` | The GCP region where the Artifact Registry will be created. | `string` | n/a | yes |
| `resource_prefix` | Standard naming prefix assigned to the deployment. | `string` | n/a | yes |
| `environment` | Deployment environment identifier. | `string` | n/a | yes |
| `labels` | A map of labels to apply to the resource. | `map(string)` | `{}` | no |
| `repository_id` | The ID of the repository. | `string` | `"ghcr-proxy"` | no |
| `remote_uri` | The URI of the remote repository to proxy. | `string` | `"https://ghcr.io"` | no |
| `cleanup_older_than` | Cleanup policy condition: delete cached layers unaccessed for this duration. | `string` | `"2592000s"` | no |

## Outputs

| Name | Description |
|------|-------------|
| `repository_id` | The ID of the Artifact Registry repository. |
| `repository_name` | The fully qualified name of the repository. |
| `repository_url` | The URL of the repository (without image name). |
