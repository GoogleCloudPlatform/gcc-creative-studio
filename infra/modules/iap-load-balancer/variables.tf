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

variable "workforce_pool_id" {
  type        = string
  description = "An existing Workforce Identity Pool ID (e.g. cs-workforce-pool). Required if using an existing pool instead of creating a new one."
  default     = ""
}


