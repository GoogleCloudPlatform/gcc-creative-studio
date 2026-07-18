# --- Cloud Armor (WAF) ---
resource "google_compute_security_policy" "policy" {
  name = "${var.resource_prefix}-${var.environment}-waf-policy"

  # Enable Machine Learning DDoS Protection
  adaptive_protection_config {
    layer_7_ddos_defense_config {
      enable          = true
      rule_visibility = "STANDARD"
    }
  }

  # Rate Limiting (e.g., max 100 requests per minute per IP)
  rule {
    action   = "rate_based_ban"
    priority = 500
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = var.rate_limit_count
        interval_sec = var.rate_limit_interval_sec
      }
      ban_duration_sec = var.ban_duration_sec
    }
    description = "Rate limit abusive traffic"
  }

  # Expanded OWASP Protection
  rule {
    action   = "deny(403)"
    priority = 1000
    match {
      expr {
        # Combine SQLi, XSS, and LFI checks
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable') || evaluatePreconfiguredExpr('xss-v33-stable') || evaluatePreconfiguredExpr('lfi-v33-stable')"
      }
    }
    description = "Block OWASP Top 10 attacks"
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "Default allow"
  }
}

# --- Global Load Balancer ---
module "lb-http" {
  source  = "terraform-google-modules/lb-http/google//modules/serverless_negs"
  version = "~> 12.0" # Always pin versions for production stability

  project = var.project_id

  # Dynamic base name to safely isolate multi-tenant/customer deployments
  name = "${var.resource_prefix}-${var.environment}-lb"

  # SSL Configuration (Mandatory Production Custom Domain Setup)
  ssl                             = true
  managed_ssl_certificate_domains = [var.domain_name]
  https_redirect                  = true

  backends = {
    default = {
      description = "Backend routing for Serverless Cloud Run integration"
      groups = [
        {
          group = var.serverless_neg_id
        }
      ]

      # Correct parameter mapping for v12.0 caching rules
      enable_cdn      = var.enable_cdn
      security_policy = google_compute_security_policy.policy.name

      # Full audit visibility required by Enterprise InfoSec policies
      log_config = {
        enable      = true
        sample_rate = var.log_sample_rate
      }

      iap_config = {
        enable = false
      }
    }
  }
}