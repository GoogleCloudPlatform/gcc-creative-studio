# Progress

## Status

- **State**: Executing
- **Current Objective**: Correct bootstrap branch reuse before resuming the private Cloud SQL deployment.

## Plan

- [x] Phase 1: Check branch, repository state, deployment wiring, and provider constraints.
- [x] Phase 2: Establish the private Cloud SQL concept and risks.
- [x] Phase 3: Implement Terraform networking and Cloud Run connectivity.
- [x] Phase 4: Add deployment, validation, and teardown documentation.
- [x] Phase 5: Run available validation and commit.
- [ ] Phase 6: Validate and commit bootstrap branch-resume correction.

## Journal

### 2026-08-20 Private Cloud SQL Deployment

- Validated fresh Cloud Shell checkout — **Finding**: Terraform initialized the private-networking module, then Google provider v7.45.0 rejected `project` on `google_service_networking_connection` — **Decision**: remove the unsupported attribute; the fully qualified VPC self link identifies the network-owning project.
- Resumed deployment investigation — **Finding**: Cloud SQL apply attempted a public IP despite the feature branch setting `ipv4_enabled = false`; bootstrap reuses an existing checkout without previously switching it to the branch entered by the user — **Decision**: update a clean existing checkout to the selected branch before reuse and document the recovery commands.
- Committed implementation — **Finding**: static diagnostics and Git whitespace checks pass, while `uv`, `terraform`, and `gcloud` are unavailable locally — **Decision**: commit the reviewed change without apply; require Cloud Shell Terraform formatting, validation, plan review, and runtime validation before deployment.
- Implemented private connectivity — **Finding**: the application selected `IPTypes.PUBLIC` when `USE_CLOUD_SQL_AUTH_PROXY` was unset, despite mounting the Cloud SQL socket — **Decision**: configure the Python Connector with an explicit validated IP type and set `CLOUD_SQL_IP_TYPE=PRIVATE` in the deployment.
- Added VPC resources — **Finding**: the provider configuration has no version constraints or lock file — **Decision**: use the broadly supported Serverless VPC Access connector rather than Direct VPC egress; use `PRIVATE_RANGES_ONLY` to avoid requiring Cloud NAT for Internet traffic.
- Validation environment — **Finding**: neither `uv` nor `terraform` is installed in the local execution environment — **Decision**: record focused test and Terraform validation as pending Cloud Shell or a configured developer environment.
- Inspected the organisation fork on `feature/KN-DATAX-15064-deploy-creative-studio` — **Finding**: existing untracked `AGENTS.md` and `README_monorepo.md` are user files and will remain untouched — **Decision**: make implementation changes only in tracked Creative Studio deployment files.
- Traced the database path — **Finding**: the backend Cloud Run service mounts the Cloud SQL Auth Proxy socket at `/cloudsql/<instance-connection-name>` but has no VPC connectivity; PostgreSQL enables public IPv4 — **Decision**: retain the socket path and add private VPC connectivity for the backend only.
- Reviewed provider declarations — **Finding**: the example environment does not constrain Google provider versions — **Decision**: use Serverless VPC Access connector fields rather than require Direct VPC egress support from an unknown provider version.