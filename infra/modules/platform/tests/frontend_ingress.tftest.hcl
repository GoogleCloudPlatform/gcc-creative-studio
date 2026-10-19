# Plan-only test: the frontend Cloud Run service accepts traffic only from the
# load balancer when IAP is on, and from anywhere when IAP is off, the same as
# the backend. Without this, turning IAP off (Level 3 rollback) left the
# frontend unreachable until someone edited main.tf.

mock_provider "google" {}

mock_provider "google-beta" {}

mock_provider "tls" {}

mock_provider "random" {}

variables {
  gcp_project_id            = "test-project"
  gcp_region                = "us-central1"
  environment               = "development"
  backend_service_name      = "cs-backend"
  backend_custom_audiences  = []
  be_env_vars               = {}
  frontend_service_name     = "cs-frontend"
  frontend_custom_audiences = []
  github_conn_name          = "test-conn"
  github_repo_owner         = "test-owner"
  github_repo_name          = "test-repo"
  github_branch_name        = "main"
}

run "frontend_open_when_iap_off" {
  command = plan

  variables {
    iap_oauth2_client_id = ""
  }

  assert {
    condition     = module.frontend_service.ingress == "INGRESS_TRAFFIC_ALL"
    error_message = "With IAP off, the frontend must accept traffic from anywhere."
  }

  assert {
    condition     = module.frontend_service.ingress == module.backend_service.ingress
    error_message = "Frontend and backend ingress should match."
  }
}

run "frontend_load_balancer_only_when_iap_on" {
  command = plan

  variables {
    iap_oauth2_client_id     = "test-iap-client"
    iap_oauth2_client_secret = "test-iap-secret"
  }

  assert {
    condition     = module.frontend_service.ingress == "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    error_message = "With IAP on, the frontend must accept traffic only from the load balancer."
  }

  assert {
    condition     = module.frontend_service.ingress == module.backend_service.ingress
    error_message = "Frontend and backend ingress should match."
  }
}
