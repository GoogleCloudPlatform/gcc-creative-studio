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
  description = "The GCP project ID."
}

variable "region" {
  type        = string
  description = "The GCP region where resources will be created."
}

variable "environment" {
  type        = string
  description = "The deployment environment (e.g., development, staging, production)."
}

variable "resource_prefix" {
  type        = string
  description = "Prefix to be used for resource naming."
}

variable "service_name" {
  type        = string
  description = "The name of the Cloud Run service."
}

variable "image_url" {
  type        = string
  description = "The URL of the container image to deploy."
}

variable "ar_repo_id" {
  type        = string
  description = "The Artifact Registry repository ID."
}

variable "github_org_or_user" {
  type        = string
  description = "The GitHub organization or user name."
}

variable "github_repo_name" {
  type        = string
  description = "The GitHub repository name."
}

variable "image_tag" {
  type        = string
  description = "The image tag to deploy."
}

variable "custom_audiences" {
  type        = list(string)
  description = "Custom audiences for the Cloud Run service."
  default     = []
}

variable "cloud_sql_connection_name" {
  type        = string
  description = "The connection name of the Cloud SQL instance to mount."
}

variable "db_name" {
  type        = string
  description = "The name of the database to connect to."
}

variable "db_user" {
  type        = string
  description = "The database user for connection."
}

variable "db_secret_id" {
  type        = string
  description = "The Secret Manager secret ID containing the database password."
}

variable "cpu" {
  type        = string
  description = "CPU limit for the Cloud Run container."
  default     = "1000m"
}

variable "memory" {
  type        = string
  description = "Memory limit for the Cloud Run container."
  default     = "512Mi"
}

variable "container_env_vars" {
  type        = map(string)
  description = "Map of non-secret environment variables for the container."
  default     = {}
}

variable "runtime_secrets" {
  type        = map(string)
  description = "Map of environment variable names to Secret Manager secret names for runtime secrets."
  default     = {}
}

variable "scaling_min_instances" {
  type        = number
  description = "Minimum number of container instances."
  default     = 0
}

variable "scaling_max_instances" {
  type        = number
  description = "Maximum number of container instances."
  default     = 10
}

variable "run_sa_project_roles" {
  type        = list(string)
  description = "List of IAM roles to assign to the Cloud Run service account at the project level."
  default = [
    "roles/aiplatform.user",
    "roles/storage.objectAdmin",
    "roles/firebase.developAdmin",
    "roles/iam.serviceAccountTokenCreator",
    "roles/cloudsql.client", # for Cloud SQL Auth Proxy
    "roles/workflows.editor",
    "roles/workflows.invoker",
    "roles/secretmanager.secretAccessor",
  ]
}

variable "app_version" {
  type = string
  description = "version of the creative studio app we're deploying"
  default = "latest"
}
