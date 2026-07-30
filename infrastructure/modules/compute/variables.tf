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

variable "vpc_subnet_name" {
  type        = string
  description = "The name of the subnet allocated for Cloud Run Direct VPC Egress."
}

variable "vpc_network_name" {
  type        = string
  description = "The simple name of the VPC network."
}

variable "database_ip" {
  type        = string
  description = "The private IP address of the Cloud SQL instance."
}

variable "secret_ids" {
  type        = set(string)
  description = "List of Secret Manager secret IDs to map to environment variables."
}

variable "custom_audiences" {
  type        = list(string)
  description = "Custom audiences for the Cloud Run service."
  default     = []
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
    "roles/workflows.editor",
    "roles/workflows.invoker",
    "roles/secretmanager.secretAccessor",
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",
  ]
}

variable "app_version" {
  type = string
  description = "version of the creative studio app we're deploying"
  default = "latest"
}
