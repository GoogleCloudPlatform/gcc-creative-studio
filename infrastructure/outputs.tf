output "firebase_dns_verification_records" {
  description = "The target DNS records you must add to your domain registrar to verify ownership and activate SSL."
  # Safely handle the output depending on whether the resource count is 0 or 1
  value = length(google_firebase_hosting_custom_domain.custom_domain) > 0 ? (
    google_firebase_hosting_custom_domain.custom_domain[0].required_dns_updates
  ) : null
}

output "cloud_sql_connection_name" {
  description = "The connection name of the Cloud SQL instance."
  value       = module.database.instance_connection_name
}

output "db_name" {
  description = "The name of the database."
  value       = module.database.database_name
}

output "db_user" {
  description = "The database user name."
  value       = module.database.user_name
}

output "db_secret_id" {
  description = "Secret Manager secret ID for DB Password."
  value       = module.database.secret_id
}

output "frontend_service_url" {
  description = "The default Firebase Hosting URL."
  value       = "https://${google_firebase_hosting_site.frontend.site_id}.web.app"
}

output "backend_service_url" {
  description = "The URL of the backend service."
  value       = module.compute.service_uri
}

output "cloud_run_subnet_name" {
  description = "The subnet name allocated for Cloud Run Direct VPC Egress."
  value       = module.network.cloud_run_subnet_name
}



