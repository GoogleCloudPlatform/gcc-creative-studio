variable "gcp_project_id" {
  type        = string
  description = "The GCP project ID"
}

variable "gcp_region" {
  type        = string
  description = "The GCP region for the Cloud Run service"
}

variable "backend_service_name" {
  type        = string
  description = "The name of the Cloud Run backend service"
}

variable "frontend_service_name" {
  type        = string
  description = "The name of the Cloud Run frontend service"
}

variable "backend_cloud_run_name" {
  type        = string
  description = "Optional Cloud Run backend service resource name reference for IAM binding ordering"
  default     = ""
}

variable "frontend_cloud_run_name" {
  type        = string
  description = "Optional Cloud Run frontend service resource name reference for IAM binding ordering"
  default     = ""
}


variable "org_id" {
  type        = string
  description = "The Organization ID for the Workforce Identity Pool"
  default     = ""
}

variable "entra_client_id" {
  type        = string
  description = "Microsoft Entra Client ID for Workforce Identity Federation"
  default     = ""
}

variable "entra_tenant_id" {
  type        = string
  description = "Microsoft Entra Tenant ID for Workforce Identity Federation"
  default     = ""
}

variable "entra_client_secret" {
  type        = string
  description = "Microsoft Entra Client Secret for Workforce Identity Federation"
  default     = ""
  sensitive   = true
}


variable "iap_oauth2_client_id" {
  type        = string
  description = "OAuth2 Client ID for Identity-Aware Proxy"
  default     = ""
}

variable "iap_oauth2_client_secret" {
  type        = string
  description = "OAuth2 Client Secret for Identity-Aware Proxy"
  default     = ""
  sensitive   = true
}

variable "domain_name" {
  type        = string
  description = "The domain name for the Load Balancer Managed SSL Certificate"
  default     = ""
}

variable "iap_access_members" {
  type        = list(string)
  description = "The list of IAM members allowed to access the application via IAP (e.g. user:email@domain.com, group:email@domain.com, domain:domain.com)."
  default     = []
}

variable "entra_access_group_ids" {
  type        = list(string)
  description = "Object IDs of the Entra groups whose members may open the app through IAP. Required when Entra sign-in is used; only these groups get in, not everyone in the tenant. The groups must be assigned to the Entra app and sent in its groups claim."
  default     = []

  validation {
    condition     = length(var.entra_access_group_ids) > 0 || (var.org_id == "" && var.workforce_pool_id == "")
    error_message = "Entra sign-in needs at least one access group: set entra_access_group_ids to the Entra group object ID(s) allowed to use the app."
  }
}

variable "workforce_pool_id" {
  type        = string
  description = "An existing Workforce Identity Pool ID (e.g. cs-workforce-pool). Required if using an existing pool instead of creating a new one."
  default     = ""
}


