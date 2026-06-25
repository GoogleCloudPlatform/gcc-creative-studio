output "load_balancer_ip" {
  value       = google_compute_global_address.lb_ip.address
  description = "The external IP address of the Global HTTP(S) Load Balancer."
}

output "iap_expected_audience" {
  value       = "/projects/${data.google_project.project.number}/global/backendServices/${google_compute_backend_service.be_service.generated_id}"
  description = "The expected Audience (aud) claim for IAP JWT validation."
}
