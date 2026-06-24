terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0"
    }
  }
}

data "google_project" "project" {
  project_id = var.gcp_project_id
}

locals {
  # If org_id is provided, we create a pool called cs-workforce-pool, otherwise use the provided pool ID
  resolved_pool_id = var.org_id != "" ? "locations/global/workforcePools/cs-workforce-pool" : var.workforce_pool_id
  use_workforce    = local.resolved_pool_id != ""
}

# --- 1. Workforce Identity Federation ---

resource "google_iam_workforce_pool" "pool" {
  count             = var.org_id != "" ? 1 : 0
  provider          = google-beta
  workforce_pool_id = "cs-workforce-pool"
  parent            = "organizations/${var.org_id}"
  location          = "global"
}

resource "google_iam_workforce_pool_provider" "entra" {
  count             = (var.org_id != "" && var.entra_tenant_id != "" && var.entra_client_id != "") ? 1 : 0
  provider          = google-beta
  workforce_pool_id = google_iam_workforce_pool.pool[0].workforce_pool_id
  provider_id       = "entra-provider"
  location          = "global"

  oidc {
    issuer_uri = "https://login.microsoftonline.com/${var.entra_tenant_id}/v2.0"
    client_id  = var.entra_client_id
    
    client_secret {
      value {
        plain_text = var.entra_client_secret
      }
    }
    
    web_sso_config {
      response_type             = "CODE"
      assertion_claims_behavior = "MERGE_USER_INFO_OVER_ID_TOKEN_CLAIMS"
    }
  }


  attribute_mapping = {
    "google.subject"      = "assertion.sub"
    "google.display_name" = "assertion.name"
    "google.email"        = "has(assertion.email) ? assertion.email : assertion.preferred_username"
  }

}

# --- 2. Load Balancer Resources ---

# IP Address for the Load Balancer
resource "google_compute_global_address" "lb_ip" {
  name = "cs-backend-lb-ip"
}

# Serverless NEG pointing to Cloud Run backend
resource "google_compute_region_network_endpoint_group" "be_neg" {
  name                  = "cs-backend-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.gcp_region

  cloud_run {
    service = var.backend_service_name
  }
}

# Serverless NEG pointing to Cloud Run frontend
resource "google_compute_region_network_endpoint_group" "fe_neg" {
  name                  = "cs-frontend-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.gcp_region

  cloud_run {
    service = var.frontend_service_name
  }
}

# Backend Service with IAP Enabled (Backend API)
resource "google_compute_backend_service" "be_service" {
  name                  = "cs-backend-lb-service"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.be_neg.id
  }

  # If IAP Client ID and Secret are provided, configure IAP
  dynamic "iap" {
    for_each = (var.iap_oauth2_client_id != "" && var.iap_oauth2_client_secret != "") ? [1] : []
    content {
      oauth2_client_id     = var.iap_oauth2_client_id
      oauth2_client_secret = var.iap_oauth2_client_secret
      enabled              = true
    }
  }
}

# Backend Service with IAP Enabled (Frontend Static)
resource "google_compute_backend_service" "fe_service" {
  name                  = "cs-frontend-lb-service"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.fe_neg.id
  }

  dynamic "iap" {
    for_each = (var.iap_oauth2_client_id != "" && var.iap_oauth2_client_secret != "") ? [1] : []
    content {
      oauth2_client_id     = var.iap_oauth2_client_id
      oauth2_client_secret = var.iap_oauth2_client_secret
      enabled              = true
    }
  }
}

# URL Map to route traffic (Default to Frontend, /api/* to Backend)
resource "google_compute_url_map" "url_map" {
  name            = "cs-backend-url-map"
  default_service = google_compute_backend_service.fe_service.id

  host_rule {
    hosts        = ["*"]
    path_matcher = "all-paths"
  }

  path_matcher {
    name            = "all-paths"
    default_service = google_compute_backend_service.fe_service.id

    path_rule {
      paths   = ["/api", "/api/*"]
      service = google_compute_backend_service.be_service.id
    }
  }
}


# SSL Certificate (if domain name is provided, use Google managed, else fallback to a placeholder self-signed or unmanaged)
resource "google_compute_managed_ssl_certificate" "lb_cert" {
  count = var.domain_name != "" ? 1 : 0
  name  = "cs-backend-lb-cert"
  managed {
    domains = [var.domain_name]
  }
}

# In a production context with no domain name, you might need a self-signed cert.
# For automation, we will define a self-signed SSL certificate if domain_name is empty.
resource "tls_private_key" "example" {
  count     = var.domain_name == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "example" {
  count           = var.domain_name == "" ? 1 : 0
  private_key_pem = tls_private_key.example[0].private_key_pem

  subject {
    common_name  = "example.com"
    organization = "Creative Studio Local"
  }

  validity_period_hours = 8760 # 1 year

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "google_compute_ssl_certificate" "fallback_cert" {
  count           = var.domain_name == "" ? 1 : 0
  name            = "cs-backend-fallback-cert"
  private_key     = tls_private_key.example[0].private_key_pem
  certificate     = tls_self_signed_cert.example[0].cert_pem
}

# Target HTTPS Proxy
resource "google_compute_target_https_proxy" "https_proxy" {
  name             = "cs-backend-https-proxy"
  url_map          = google_compute_url_map.url_map.id
  ssl_certificates = compact([
    var.domain_name != "" ? google_compute_managed_ssl_certificate.lb_cert[0].id : "",
    var.domain_name == "" ? google_compute_ssl_certificate.fallback_cert[0].id : ""
  ])
}


# Forwarding Rule (Frontend IP)
resource "google_compute_global_forwarding_rule" "forwarding_rule" {
  name                  = "cs-backend-forwarding-rule"
  ip_address            = google_compute_global_address.lb_ip.address
  target                = google_compute_target_https_proxy.https_proxy.id
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# Allow IAP service agent to access Cloud Run
resource "google_project_service_identity" "iap_sa" {
  provider = google-beta
  project  = var.gcp_project_id
  service  = "iap.googleapis.com"
}

resource "google_cloud_run_v2_service_iam_member" "iap_can_invoke_backend" {
  project  = var.gcp_project_id
  name     = var.backend_service_name
  location = var.gcp_region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap_sa.email}"
}

resource "google_cloud_run_v2_service_iam_member" "iap_can_invoke_frontend" {
  project  = var.gcp_project_id
  name     = var.frontend_service_name
  location = var.gcp_region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap_sa.email}"
}

# Grant users IAP secured Web App User role on backend service
resource "google_iap_web_backend_service_iam_member" "member" {
  for_each            = toset(var.iap_access_members)
  project             = var.gcp_project_id
  web_backend_service = google_compute_backend_service.be_service.name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.key
}

# Grant users IAP secured Web App User role on frontend service
resource "google_iap_web_backend_service_iam_member" "fe_member" {
  for_each            = toset(var.iap_access_members)
  project             = var.gcp_project_id
  web_backend_service = google_compute_backend_service.fe_service.name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.key
}

# Configure IAP Settings to prioritize Workforce Identity Federation on backend service
resource "google_iap_settings" "default" {
  count    = (var.iap_oauth2_client_id != "" && local.use_workforce) ? 1 : 0
  provider = google-beta
  name     = "projects/${var.gcp_project_id}/iap_web/compute/services/${google_compute_backend_service.be_service.name}"

  access_settings {
    identity_sources = ["WORKFORCE_IDENTITY_FEDERATION"]

    workforce_identity_settings {
      workforce_pools = [local.resolved_pool_id]
      oauth2 {
        client_id     = var.iap_oauth2_client_id
        client_secret = var.iap_oauth2_client_secret
      }
    }
  }
}

# Configure IAP Settings to prioritize Workforce Identity Federation on frontend service
resource "google_iap_settings" "fe_default" {
  count    = (var.iap_oauth2_client_id != "" && local.use_workforce) ? 1 : 0
  provider = google-beta
  name     = "projects/${var.gcp_project_id}/iap_web/compute/services/${google_compute_backend_service.fe_service.name}"

  access_settings {
    identity_sources = ["WORKFORCE_IDENTITY_FEDERATION"]

    workforce_identity_settings {
      workforce_pools = [local.resolved_pool_id]
      oauth2 {
        client_id     = var.iap_oauth2_client_id
        client_secret = var.iap_oauth2_client_secret
      }
    }
  }
}




