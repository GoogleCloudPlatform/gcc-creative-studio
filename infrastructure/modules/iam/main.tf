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

locals {
  role_members = flatten([
    for role, members in var.project_roles : [
      for member in members : {
        role   = role
        member = member
      }
    ]
  ])
}

resource "google_project_iam_member" "project_bindings" {
  for_each = {
    for rm in local.role_members : "${rm.role}-${rm.member}" => rm
  }
  project = var.project_id
  role    = each.value.role
  member  = each.value.member
}
