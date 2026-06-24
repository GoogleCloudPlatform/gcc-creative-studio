# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

variable "gcp_project_id" { type = string }
variable "gcp_region" { type = string }
variable "environment" { type = string }


variable "firebase_site_id" {
  type        = string
  description = "The site ID for the Firebase Hosting site. Must be unique across all Firebase projects."
  default     = ""
}

# Backend specific variables
variable "backend_service_name" { type = string }
variable "backend_custom_audiences" { type = list(string) }
variable "be_env_vars" { type = map(map(string)) }

variable "be_build_substitutions" {
  type        = map(string)
  description = "A map of substitution variables for the backend Cloud Build trigger."
  default     = {}
}

# Frontend specific variables
variable "frontend_service_name" { type = string }
variable "frontend_custom_audiences" { type = list(string) }

variable "fe_build_substitutions" {
  type        = map(string)
  description = "A map of substitution variables for the frontend Cloud Build trigger."
  default     = {}
}

# Common GitHub variables
variable "github_conn_name" { type = string }
variable "github_repo_owner" { type = string }
variable "github_repo_name" { type = string }
variable "github_branch_name" { type = string }

variable "be_cpu" {
  type = string
  default = "2000m"
}

variable "be_memory" {
  type = string
  default = "2048Mi"
}

variable "fe_cpu" {
  type = string
  default = "2000m"
}

variable "fe_memory" {
  type = string
  default = "2048Mi"
}

variable "frontend_secrets" {
  type        = list(string)
  description = "A list of secret names required by the frontend build."
  default     = []
}

variable "backend_secrets" {
  type        = list(string)
  description = "A list of secret names required by the backend build."
  default     = []
}

variable "backend_runtime_secrets" {
  type        = map(string)
  description = "Secrets to mount in the backend container at runtime."
  default     = {}
}

variable "iap_expected_audience" {
  type        = string
  description = "The expected Audience (aud) claim for Identity-Aware Proxy (IAP) JWT validation."
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
  description = "The list of IAM members allowed to access the application via IAP."
  default     = []
}

variable "workforce_pool_id" {
  type        = string
  description = "An existing Workforce Identity Pool ID (e.g. cs-workforce-pool)."
  default     = ""
}



