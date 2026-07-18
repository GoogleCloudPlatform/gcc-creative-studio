output "load_balancer_ip" {
  description = "The external IP address of the Load Balancer."
  value       = module.lb-http.external_ip
}
