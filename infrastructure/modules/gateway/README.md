# Gateway Module (Load Balancer & WAF)

This module creates a Global HTTP(S) Load Balancer with Serverless Network Endpoint Group (NEG) integration and a Cloud Armor security policy (WAF) with rate limiting and OWASP protection.

## Features

- Global HTTP(S) Load Balancer with SSL termination.
- Cloud Armor security policy with:
    - Adaptive Protection (DDoS defense).
    - Rate limiting.
    - OWASP Top 10 protection rules.
- Serverless NEG integration for Cloud Run.

## Usage

```hcl
module "gateway" {
  source = "./modules/gateway"

  project_id        = "my-project-id"
  resource_prefix   = "cstudio"
  environment       = "dev"
  domain_name       = "app.creativestudio.com"
  serverless_neg_id = module.compute.serverless_neg_id
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | The GCP project ID. | `string` | n/a | yes |
| `resource_prefix` | Standard naming prefix assigned to the deployment. | `string` | n/a | yes |
| `environment` | Deployment environment identifier. | `string` | n/a | yes |
| `domain_name` | The custom domain string linked to the load balancer. | `string` | n/a | yes |
| `serverless_neg_id` | The self-link ID of the serverless NEG. | `string` | n/a | yes |
| `rate_limit_count` | Max requests per minute per IP before rate limiting. | `number` | `100` | no |
| `rate_limit_interval_sec` | Interval in seconds for rate limiting. | `number` | `60` | no |
| `ban_duration_sec` | Duration in seconds to ban abusive IPs. | `number` | `300` | no |
| `enable_cdn` | Whether to enable Cloud CDN on the backend. | `bool` | `false` | no |
| `log_sample_rate` | Sample rate for request logging (0.0 to 1.0). | `number` | `1.0` | no |

## Outputs

| Name | Description |
|------|-------------|
| `load_balancer_ip` | The external IP address of the Load Balancer. |
