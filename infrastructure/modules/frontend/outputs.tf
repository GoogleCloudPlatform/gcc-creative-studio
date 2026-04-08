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

output "site_id" {
  description = "The ID of the Firebase Hosting site."
  value       = google_firebase_hosting_site.this.site_id
}

output "default_url" {
  description = "The default URL of the Firebase Hosting site."
  value       = "https://${google_firebase_hosting_site.this.site_id}.web.app"
}

output "custom_domain" {
  description = "The custom domain configured, if any."
  value       = var.custom_domain != null ? google_firebase_hosting_custom_domain.this[0].domain_name : null
}

output "trigger_id" {
  description = "The ID of the Cloud Build trigger, if enabled."
  value       = var.enable_trigger ? google_cloudbuild_trigger.this[0].id : null
}

output "trigger_service_account_email" {
  description = "The email of the service account used by the trigger, if enabled."
  value       = var.enable_trigger ? google_service_account.trigger_sa[0].email : null
}
