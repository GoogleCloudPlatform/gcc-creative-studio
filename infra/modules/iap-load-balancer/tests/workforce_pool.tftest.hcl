# Plan-only regression test for T-1: the Entra workforce pool provider must
# attach to a reused pool (workforce_pool_id set) without indexing the pool
# resource, which has count = 0 in that case.

mock_provider "google" {}

mock_provider "google-beta" {}

mock_provider "tls" {}

mock_provider "random" {
  # Make the generated pool id known at plan time so it can be asserted on.
  override_during = plan

  mock_resource "random_id" {
    defaults = {
      hex = "abcd1234"
    }
  }
}

variables {
  gcp_project_id        = "test-project"
  gcp_region            = "us-central1"
  backend_service_name  = "cs-backend"
  frontend_service_name = "cs-frontend"
  org_id                = "123456789012"
  entra_tenant_id       = "00000000-0000-0000-0000-000000000001"
  entra_client_id       = "00000000-0000-0000-0000-000000000002"
  entra_client_secret   = "dummy-secret"
}

run "creates_pool_when_only_org_id_set" {
  command = plan

  assert {
    condition     = length(google_iam_workforce_pool.pool) == 1
    error_message = "Expected the module to create a workforce pool."
  }

  assert {
    condition     = google_iam_workforce_pool.pool[0].workforce_pool_id == "cs-workforce-pool-abcd1234"
    error_message = "Created pool should use the generated pool id."
  }

  assert {
    condition     = google_iam_workforce_pool_provider.entra[0].workforce_pool_id == google_iam_workforce_pool.pool[0].workforce_pool_id
    error_message = "Provider should attach to the created pool."
  }
}

run "reuses_existing_pool_when_workforce_pool_id_set" {
  command = plan

  variables {
    workforce_pool_id = "existing-pool"
  }

  assert {
    condition     = length(google_iam_workforce_pool.pool) == 0
    error_message = "No pool should be created when workforce_pool_id is set."
  }

  assert {
    condition     = length(random_id.pool_suffix) == 0
    error_message = "No pool suffix should be generated when reusing a pool."
  }

  assert {
    condition     = google_iam_workforce_pool_provider.entra[0].workforce_pool_id == "existing-pool"
    error_message = "Provider should attach to the existing pool."
  }
}
