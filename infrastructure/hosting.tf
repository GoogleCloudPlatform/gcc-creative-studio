
# Creates the Firebase Hosting site to deploy to
resource "google_firebase_hosting_site" "frontend" {
  provider = google-beta
  project  = var.project_id
  site_id  = var.firebase_site_id
}

# Conditionally map the Custom Domain if provided
resource "google_firebase_hosting_custom_domain" "custom_domain" {
  provider = google-beta
  # Evaluates to 1 if a domain string is provided, 0 if left blank
  count = var.custom_domain != "" ? 1 : 0

  project       = var.project_id
  site_id       = google_firebase_hosting_site.frontend.site_id
  custom_domain = var.custom_domain

  # Prevent Terraform runs from timing out while waiting for manual DNS propagation
  wait_dns_verification = false
}