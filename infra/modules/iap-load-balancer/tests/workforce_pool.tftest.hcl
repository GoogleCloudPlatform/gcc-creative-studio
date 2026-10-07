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
  entra_access_group_ids = ["aaaa-access-group"]
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

  assert {
    condition     = google_iam_workforce_pool_provider.entra[0].attribute_mapping["google.subject"] == "assertion.oid"
    error_message = "Provider should map google.subject to assertion.oid."
  }

  assert {
    condition     = output.workforce_pool_id == "cs-workforce-pool-abcd1234"
    error_message = "Output workforce_pool_id should match the generated pool id."
  }

  assert {
    condition     = output.entra_redirect_uri == "https://auth.cloud.google/signin-callback/locations/global/workforcePools/cs-workforce-pool-abcd1234/providers/entra-provider"
    error_message = "Output entra_redirect_uri should use the generated pool id."
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

  assert {
    condition     = output.workforce_pool_id == "existing-pool"
    error_message = "Output workforce_pool_id should match the existing pool id."
  }

  assert {
    condition     = output.entra_redirect_uri == "https://auth.cloud.google/signin-callback/locations/global/workforcePools/existing-pool/providers/entra-provider"
    error_message = "Output entra_redirect_uri should use the existing pool id."
  }
}

run "no_pool_when_neither_org_id_nor_workforce_pool_id_set" {
  command = plan

  variables {
    org_id            = ""
    workforce_pool_id = ""
  }

  assert {
    condition     = length(google_iam_workforce_pool.pool) == 0
    error_message = "No pool should be created when org_id and workforce_pool_id are empty."
  }

  assert {
    condition     = output.workforce_pool_id == ""
    error_message = "Output workforce_pool_id should be empty when workforce federation is disabled."
  }

  assert {
    condition     = output.entra_redirect_uri == ""
    error_message = "Output entra_redirect_uri should be empty when workforce federation is disabled."
  }
}

# Q3: in Entra mode, IAP must let in only members of the named Entra access
# group(s), never the whole workforce pool.
run "iap_access_limited_to_entra_access_group" {
  command = plan

  assert {
    condition     = google_iam_workforce_pool_provider.entra[0].attribute_mapping["google.groups"] == "assertion.groups"
    error_message = "Provider should map google.groups to assertion.groups so IAP can check group membership."
  }

  assert {
    condition     = google_iap_web_backend_service_iam_member.backend_entra_group["aaaa-access-group"].member == "principalSet://iam.googleapis.com/locations/global/workforcePools/cs-workforce-pool-abcd1234/group/aaaa-access-group"
    error_message = "Backend IAP access should be granted to the Entra access group."
  }

  assert {
    condition     = google_iap_web_backend_service_iam_member.frontend_entra_group["aaaa-access-group"].member == "principalSet://iam.googleapis.com/locations/global/workforcePools/cs-workforce-pool-abcd1234/group/aaaa-access-group"
    error_message = "Frontend IAP access should be granted to the Entra access group."
  }
}

run "entra_mode_refuses_empty_access_group_list" {
  command = plan

  variables {
    entra_access_group_ids = []
  }

  expect_failures = [var.entra_access_group_ids]
}

run "google_mode_needs_no_access_group" {
  command = plan

  variables {
    org_id                 = ""
    workforce_pool_id      = ""
    entra_access_group_ids = []
  }

  assert {
    condition     = length(google_iap_web_backend_service_iam_member.backend_entra_group) == 0
    error_message = "No Entra group grant should exist outside Entra mode."
  }
}
