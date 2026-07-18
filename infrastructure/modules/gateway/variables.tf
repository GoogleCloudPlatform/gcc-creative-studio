variable "project_id" {
  type        = string
  description = "The customer's Google Cloud project ID hosting the gateway infrastructure."
}

variable "resource_prefix" {
  type        = string
  description = "Standard naming prefix assigned to the customer deployment (e.g., 'cstudio')."
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier (e.g., 'eval', 'staging', 'prod')."
}

variable "domain_name" {
  type        = string
  description = "The mandated custom domain string linked to the external load balancer."
}

variable "serverless_neg_id" {
  type        = string
  description = "The fully qualified self-link resource ID of the serverless Network Endpoint Group."
}

variable "rate_limit_count" {
  type        = number
  description = "Max requests per minute per IP before rate limiting applies."
  default     = 100
}

variable "rate_limit_interval_sec" {
  type        = number
  description = "Interval in seconds for rate limiting."
  default     = 60
}

variable "ban_duration_sec" {
  type        = number
  description = "Duration in seconds to ban abusive IPs."
  default     = 300
}

variable "enable_cdn" {
  type        = bool
  description = "Whether to enable Cloud CDN on the backend."
  default     = false
}

variable "log_sample_rate" {
  type        = number
  description = "Sample rate for request logging (0.0 to 1.0)."
  default     = 1.0
}
