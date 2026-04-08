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

output "backend_service_url" {
  description = "The URL of the deployed backend service."
  value       = module.backend.service_url
}

output "frontend_service_url" {
  description = "The URL of the deployed frontend service."
  value       = module.frontend.default_url
}

output "cloud_sql_connection_name" {
  description = "The connection name of the Cloud SQL instance."
  value       = module.database.connection_name
}

output "network_id" {
  description = "The ID of the VPC network."
  value       = module.network.network_id
}

output "vpc_connector_id" {
  description = "The ID of the Serverless VPC Access connector."
  value       = module.network.connector_id
}
