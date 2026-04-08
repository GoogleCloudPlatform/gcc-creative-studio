# Copyright 2026 Google LLC
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

variable "project_id" {
  type        = string
  description = "The GCP Project ID."
}

variable "region" {
  type        = string
  description = "The GCP region for resources."
}

variable "environment" {
  type        = string
  description = "The deployment environment (e.g., 'dev', 'prod')."
}

# --- Network Module Variables ---
variable "network_name" {
  description = "The name of the VPC network"
  default     = "creative-studio-vpc"
}

variable "subnet_cidr" {
  description = "The CIDR range for the Serverless VPC Access connector subnet"
  default     = "10.0.1.0/28"
}

variable "db_peering_ip_range" {
  description = "The CIDR range for Cloud SQL Private Services Access"
  default     = "10.1.0.0/16"
}

variable "enable_nat" {
  type        = bool
  description = "Enable Cloud NAT for the VPC"
  default     = false
}

variable "vpc_connector_machine_type" {
  description = "The machine type for the Serverless VPC Access connector"
  default     = "e2-micro"
}

variable "vpc_connector_min_instances" {
  description = "The minimum number of instances for the Serverless VPC Access connector"
  default     = 2
}

variable "vpc_connector_max_instances" {
  description = "The maximum number of instances for the Serverless VPC Access connector"
  default     = 3
}

variable "peering_prefix_length" {
  description = "The prefix length for the private IP allocation for Cloud SQL"
  default     = 16
}

variable "internal_source_ranges" {
  type        = list(string)
  description = "Additional source ranges allowed in the internal firewall rule"
  default     = ["10.0.0.0/8"]
}

# --- Database Module Variables ---
variable "db_name" {
  description = "The name of the database."
  default     = "creative_studio"
}

variable "db_user" {
  description = "The database user name."
  default     = "studio_user"
}

variable "db_password" {
  description = "The database password."
  sensitive   = true
}

variable "db_tier" {
  description = "The machine tier for the Cloud SQL instance."
  default     = "db-perf-optimized-N-2"
}

variable "database_version" {
  description = "The database version to use."
  default     = "POSTGRES_18"
}

variable "db_disk_size" {
  type        = number
  description = "The size of the data disk, in GB."
  default     = 10
}

variable "db_disk_type" {
  description = "The type of data disk."
  default     = "PD_SSD"
}

variable "db_disk_autoresize" {
  type        = bool
  description = "Whether to enable automatic disk size growth."
  default     = true
}

variable "db_availability_type" {
  description = "The availability type of the Cloud SQL instance."
  default     = "ZONAL"
}

variable "db_deletion_protection" {
  type        = bool
  description = "Whether to protect the instance from deletion."
  default     = false
}

variable "db_backup_enabled" {
  type        = bool
  description = "Whether to enable backups."
  default     = true
}

variable "db_point_in_time_recovery_enabled" {
  type        = bool
  description = "Whether to enable point-in-time recovery."
  default     = true
}

variable "db_query_insights_enabled" {
  type        = bool
  description = "Whether to enable Query Insights."
  default     = true
}

variable "db_database_flags" {
  type        = map(string)
  description = "A map of database flags to apply to the instance."
  default     = {}
}

# --- Backend Module Variables ---
variable "backend_service_name" {
  type        = string
  description = "The name of the Cloud Run service."
}

variable "backend_image" {
  description = "The Docker image to run for the backend."
  default     = "us-docker.pkg.dev/cloudrun/container/hello:latest"
}

variable "backend_cpu" {
  description = "CPU limits for the backend container."
  default     = "1000m"
}

variable "backend_memory" {
  description = "Memory limits for the backend container."
  default     = "512Mi"
}

variable "backend_min_instances" {
  type        = number
  description = "Minimum number of backend container instances."
  default     = 0
}

variable "backend_max_instances" {
  type        = number
  description = "Maximum number of backend container instances."
  default     = 10
}

variable "backend_env_vars" {
  type        = map(string)
  description = "Additional non-secret environment variables for the backend container."
  default     = {}
}

# --- Build Module Variables ---
variable "build_repository_id" {
  type        = string
  description = "The ID of the Artifact Registry repository."
}

variable "source_repository_id" {
  type        = string
  description = "The ID of the Cloud Build V2 source repository."
}

variable "github_branch_name" {
  description = "The branch name to trigger builds from."
  default     = "main"
}

variable "backend_cloudbuild_yaml_path" {
  description = "The path to the cloudbuild.yaml file for backend."
  default     = "backend/cloudbuild.yaml"
}

variable "backend_included_files_glob" {
  type        = list(string)
  description = "Glob patterns for backend files that should trigger the build."
  default     = ["backend/**"]
}

variable "backend_build_substitutions" {
  type        = map(string)
  description = "Substitution variables for the backend Cloud Build trigger."
  default     = {}
}

# --- Frontend Module Variables ---
variable "firebase_project_id" {
  type        = string
  description = "The Firebase Project ID."
}

variable "firebase_site_id" {
  type        = string
  description = "The site ID for Firebase Hosting."
}

variable "custom_domain" {
  type        = string
  description = "Optional custom domain to link to the Firebase site."
  default     = null
}

variable "frontend_enable_trigger" {
  type        = bool
  description = "Whether to enable the Cloud Build trigger for frontend deployment."
  default     = true
}

variable "frontend_cloudbuild_yaml_path" {
  description = "The path to the cloudbuild.yaml file for frontend."
  default     = "frontend/cloudbuild-deploy.yaml"
}

variable "frontend_included_files_glob" {
  type        = list(string)
  description = "Glob patterns for frontend files that should trigger the build."
  default     = ["frontend/**"]
}

variable "frontend_build_substitutions" {
  type        = map(string)
  description = "Substitution variables for the frontend Cloud Build trigger."
  default     = {}
}

# --- Secrets Module Variables ---
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

# --- Common GitHub variables needed for repo connection ---
variable "github_conn_name" {
  type        = string
  description = "The name of the Cloud Build GitHub connection."
}

variable "github_repo_owner" {
  type        = string
  description = "The owner of the GitHub repository."
}

variable "github_repo_name" {
  type        = string
  description = "The name of the GitHub repository."
}
