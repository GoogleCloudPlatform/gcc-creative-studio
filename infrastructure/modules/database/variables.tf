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
  description = "The GCP project ID."
}

variable "region" {
  description = "The GCP region."
}

variable "vpc_network_id" {
  description = "The ID (self-link) of the VPC network."
}

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

variable "tier" {
  description = "The machine tier for the Cloud SQL instance."
  default     = "db-perf-optimized-N-2"
}

variable "database_version" {
  description = "The database version to use."
  default     = "POSTGRES_18"
}

variable "disk_size" {
  description = "The size of the data disk, in GB."
  type        = number
  default     = 10
}

variable "disk_type" {
  description = "The type of data disk."
  default     = "PD_SSD"
}

variable "disk_autoresize" {
  description = "Whether to enable automatic disk size growth."
  type        = bool
  default     = true
}

variable "availability_type" {
  description = "The availability type of the Cloud SQL instance (ZONAL or REGIONAL)."
  default     = "ZONAL"
}

variable "deletion_protection" {
  description = "Whether to protect the instance from deletion."
  type        = bool
  default     = false
}

variable "backup_enabled" {
  description = "Whether to enable backups."
  type        = bool
  default     = true
}

variable "point_in_time_recovery_enabled" {
  description = "Whether to enable point-in-time recovery."
  type        = bool
  default     = true
}

variable "query_insights_enabled" {
  description = "Whether to enable Query Insights."
  type        = bool
  default     = true
}

variable "database_flags" {
  description = "A map of database flags to apply to the instance."
  type        = map(string)
  default     = {}
}
