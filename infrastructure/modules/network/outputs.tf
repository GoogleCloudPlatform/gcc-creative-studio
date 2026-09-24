output "network_id" {
  description = "The fully qualified ID of the VPC network."
  value       = google_compute_network.vpc.id
}

output "network_name" {
  description = "The simple name of the VPC network."
  value       = google_compute_network.vpc.name
}

output "cloud_run_subnet_name" {
  description = "The name of the subnet allocated for Cloud Run Direct VPC Egress."
  value       = google_compute_subnetwork.cloud_run_subnet.name
}

# Architectural Guardrail: Resolves classic GCP Terraform deployment race conditions.
# Cloud SQL modules must explicitly reference this output in their 'depends_on' block
# to guarantee the peering connection finishes provisioning before database creation begins.
output "peering_completed" {
  description = "Dependency trigger string confirming Private Services Access peering is active."
  value       = google_service_networking_connection.private_vpc_connection.id
}