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

variable "repository_id" {
  type        = string
  description = "The ID of the Artifact Registry repository."
}

variable "service_name" {
  type        = string
  description = "The name of the Cloud Run service targeted by the build."
}

variable "source_repository_id" {
  type        = string
  description = "The ID of the Cloud Build V2 source repository."
}

variable "github_branch_name" {
  type        = string
  description = "The branch name to trigger builds from."
  default     = "main"
}

variable "cloudbuild_yaml_path" {
  type        = string
  description = "The path to the cloudbuild.yaml file."
  default     = "cloudbuild.yaml"
}

variable "included_files_glob" {
  type        = list(string)
  description = "A list of glob patterns for files that should trigger the build."
  default     = ["**"]
}

variable "build_substitutions" {
  type        = map(string)
  description = "A map of substitution variables for the Cloud Build trigger."
  default     = {}
}
