variable "project_id" {
  type        = string
  description = "The GCP project ID."
}

variable "region" {
  type        = string
  description = "The GCP region where the Artifact Registry will be created."
}

variable "resource_prefix" {
  type        = string
  description = "Standard naming prefix assigned to the deployment."
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier."
}

variable "labels" {
  type        = map(string)
  description = "A map of labels to apply to the resource."
  default     = {}
}

variable "repository_id" {
  type        = string
  description = "The ID of the repository."
  default     = "ghcr-proxy"
}

variable "remote_uri" {
  type        = string
  description = "The URI of the remote repository to proxy."
  default     = "https://ghcr.io"
}

variable "cleanup_older_than" {
  type        = string
  description = "Cleanup policy condition: delete cached layers unaccessed for this duration."
  default     = "2592000s"
}
