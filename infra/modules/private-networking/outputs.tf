output "network_self_link" {
  description = "The VPC used by Cloud SQL private IP and the VPC Access connector."
  value       = local.network_self_link
}

output "vpc_connector_id" {
  description = "The backend Serverless VPC Access connector ID."
  value       = google_vpc_access_connector.backend.id
}