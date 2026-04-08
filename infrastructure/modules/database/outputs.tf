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

output "connection_name" {
  description = "The connection name of the database instance."
  value       = google_sql_database_instance.default.connection_name
}

output "db_name" {
  description = "The name of the database."
  value       = google_sql_database.default.name
}

output "db_user" {
  description = "The database user name."
  value       = google_sql_user.default.name
}

output "private_ip_address" {
  description = "The private IP address of the database instance."
  value       = google_sql_database_instance.default.private_ip_address
}
