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
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region for resources"
  type        = string
}

variable "network_name" {
  description = "The name of the VPC network"
  type        = string
  default     = "creative-studio-vpc"
}

variable "subnet_cidr" {
  description = "The CIDR range for the Serverless VPC Access connector subnet"
  type        = string
  default     = "10.0.1.0/28"
}

variable "db_peering_ip_range" {
  description = "The CIDR range for Cloud SQL Private Services Access (Not currently used in main.tf, use peering_prefix_length instead unless you want to specify a fixed range)"
  type        = string
  default     = "10.1.0.0/16"
}

variable "enable_nat" {
  description = "Enable Cloud NAT for the VPC"
  type        = bool
  default     = false
}

# New variables for higher configurability

variable "vpc_connector_machine_type" {
  description = "The machine type for the Serverless VPC Access connector"
  type        = string
  default     = "e2-micro"
}

variable "vpc_connector_min_instances" {
  description = "The minimum number of instances for the Serverless VPC Access connector"
  type        = number
  default     = 2
}

variable "vpc_connector_max_instances" {
  description = "The maximum number of instances for the Serverless VPC Access connector"
  type        = number
  default     = 3
}

variable "peering_prefix_length" {
  description = "The prefix length for the private IP allocation for Cloud SQL"
  type        = number
  default     = 16
}

variable "internal_source_ranges" {
  description = "Additional source ranges allowed in the internal firewall rule"
  type        = list(string)
  default     = ["10.0.0.0/8"]
}
