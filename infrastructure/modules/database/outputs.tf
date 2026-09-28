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

output "instance_name" {
  description = "The name of the Cloud SQL instance."
  value       = google_sql_database_instance.default.name
}

output "instance_connection_name" {
  description = "The connection name of the Cloud SQL instance to be used in connection strings."
  value       = google_sql_database_instance.default.connection_name
}

output "private_ip_address" {
  description = "The private IP address assigned to the Cloud SQL instance."
  value       = google_sql_database_instance.default.private_ip_address
}

output "database_name" {
  description = "The name of the created default database."
  value       = google_sql_database.default.name
}

output "user_name" {
  description = "The name of the created database user."
  value       = google_sql_user.app_user.name
}

output "secret_id" {
  description = "The ID of the Secret Manager secret storing the database password."
  value       = google_secret_manager_secret.db_secret.secret_id
}

output "secret_name" {
  description = "The resource name of the Secret Manager secret storing the database password."
  value       = google_secret_manager_secret.db_secret.name
}
