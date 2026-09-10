variable "project_id" {
  type        = string
  description = "The customer's Google Cloud project ID."
}

variable "region" {
  type        = string
  description = "The primary GCP region for network subnets."
}

variable "resource_prefix" {
  type        = string
  description = "Standard naming prefix assigned to the customer deployment."
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier (e.g., 'dev', 'stg', 'prd')."
}

variable "cloud_run_cidr" {
  type        = string
  description = "Dedicated CIDR range for Cloud Run Direct VPC egress (minimum /28 recommended)."
  default     = "10.0.0.0/26"
}
