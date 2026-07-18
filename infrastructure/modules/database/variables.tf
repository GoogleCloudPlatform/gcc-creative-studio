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
  description = "The ID of the project in which resources will be created."
}

variable "region" {
  type        = string
  description = "The region in which resources will be created."
}

variable "resource_prefix" {
  type        = string
  description = "Standard naming prefix assigned to the deployment."
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier."
}

variable "vpc_id" {
  type        = string
  description = "The VPC network ID where the Cloud SQL instance will be connected via Private Services Access."
}

variable "psa_connection_dependency" {
  type        = any
  description = "Dependency on the Private Services Access connection resource to ensure networking is established before instance creation."
  default     = null
}

variable "database_version" {
  type        = string
  description = "The database version to use for the Cloud SQL instance."
  default     = "POSTGRES_18"
}

variable "db_tier" {
  type        = string
  description = "The machine tier/type for the Cloud SQL instance."
  default     = "db-c4a-highmem-4"
}

variable "db_availability_type" {
  type        = string
  description = "The availability type for the Cloud SQL instance (ZONAL or REGIONAL)."
  default     = "REGIONAL"
}

variable "initial_disk_size" {
  type        = number
  description = "The initial disk size in GB for the Cloud SQL instance."
  default     = 10
}

variable "max_disk_size" {
  type        = number
  description = "The maximum disk size in GB for auto-resizing."
  default     = 100
}

variable "labels" {
  type        = map(string)
  description = "A map of user labels to assign to the Cloud SQL instance."
  default     = {}
}

variable "db_name" {
  type        = string
  description = "The name of the default database to create."
  default     = "creative_studio"
}

variable "db_user" {
  type        = string
  description = "The name of the default database user to create."
  default     = "app_user"
}

variable "db_password_version" {
  type        = number
  description = "The version integer for the database user password to track updates."
  default     = 1
}

variable "deletion_protection" {
  type        = bool
  description = "Whether to enable deletion protection on the Cloud SQL instance."
  default     = false
}
