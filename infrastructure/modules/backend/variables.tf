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
  description = "The GCP region for the resources."
}

variable "service_name" {
  type        = string
  description = "The name of the Cloud Run service."
}

variable "image" {
  type        = string
  description = "The Docker image to run."
  default     = "us-docker.pkg.dev/cloudrun/container/hello:latest"
}

variable "vpc_connector_id" {
  type        = string
  description = "The ID of the Serverless VPC Access connector."
}

variable "cloud_sql_connection_name" {
  type        = string
  description = "Cloud SQL Instance Connection Name."
}

variable "db_name" {
  type        = string
  description = "The name of the database."
}

variable "db_user" {
  type        = string
  description = "The database user name."
}

variable "db_secret_id" {
  type        = string
  description = "Secret Manager Secret ID for DB Password."
}

variable "cpu" {
  type        = string
  description = "CPU limits for the container."
  default     = "1000m"
}

variable "memory" {
  type        = string
  description = "Memory limits for the container."
  default     = "512Mi"
}

variable "min_instances" {
  type        = number
  description = "Minimum number of container instances."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum number of container instances."
  default     = 10
}

variable "container_env_vars" {
  type        = map(string)
  description = "Additional non-secret environment variables for the container."
  default     = {}
}
