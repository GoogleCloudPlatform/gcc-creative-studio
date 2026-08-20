variable "project_id" {
  type        = string
  description = "The project that hosts Cloud Run and the VPC Access connector."
}

variable "network_project_id" {
  type        = string
  description = "The project that owns the VPC and Private Services Access resources."
}

variable "region" {
  type        = string
  description = "The region for the Serverless VPC Access connector."
}

variable "network_name" {
  type        = string
  description = "Name for the dedicated VPC when network_self_link is not supplied."
}

variable "network_self_link" {
  type        = string
  description = "Approved existing VPC self link. Leave empty to create a dedicated VPC."
  default     = ""
}

variable "private_services_range_name" {
  type        = string
  description = "Name of the global range reserved for Private Services Access."
}

variable "private_services_range_address" {
  type        = string
  description = "Unused RFC 1918 base address for the Private Services Access range."
}

variable "private_services_range_prefix_length" {
  type        = number
  description = "Prefix length for the Private Services Access range."
  default     = 16
}

variable "vpc_connector_name" {
  type        = string
  description = "Name of the backend Serverless VPC Access connector."
}

variable "vpc_connector_cidr" {
  type        = string
  description = "Unused /28 CIDR reserved for the Serverless VPC Access connector."
}