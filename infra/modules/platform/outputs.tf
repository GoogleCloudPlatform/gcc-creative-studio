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

# modules/platform/outputs.tf

output "backend_service_url" {
  description = "The URL of the deployed backend service."
  value       = module.backend_service.service_url # This one is correct
}

output "frontend_service_url" {
  description = "The URL of the deployed frontend service."
  value       = module.frontend_service.service_url
}

output "cloud_sql_connection_name" {
  description = "The connection name of the Cloud SQL instance to be used by the bootstrap script."
  value       = module.postgresql.connection_name
}

output "load_balancer_ip" {
  value       = var.iap_oauth2_client_id != "" ? module.iap_load_balancer[0].load_balancer_ip : ""
  description = "The external IP address of the Global HTTP(S) Load Balancer."
}

output "iap_expected_audience" {
  value       = var.iap_oauth2_client_id != "" ? module.iap_load_balancer[0].iap_expected_audience : ""
  description = "The expected Audience (aud) claim for IAP JWT validation."
}

