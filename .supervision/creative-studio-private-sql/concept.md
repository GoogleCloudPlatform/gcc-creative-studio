# Concept: Creative Studio Private SQL

## Intent

Deploy the internal Creative Studio trial in `iconic-ds-creative-studio-dev` in `us-central1` without a public Cloud SQL address. Preserve the existing Cloud Run Cloud SQL Auth Proxy socket integration while making the proxy reach the instance over private networking.

## Constraints

- The deployment must use `feature/KN-DATAX-15064-deploy-creative-studio` in the organisation-owned fork.
- The inherited `constraints/sql.restrictPublicIp` policy prohibits public Cloud SQL IP addresses.
- Do not apply or destroy infrastructure until Terraform plan review confirms the private design.
- Do not store credentials, Terraform state, generated environment directories, bootstrap state, or tfvars containing real values in Git.
- Keep project resources and the VPC connector in `us-central1`; use no shared development project resources.
- The existing administrative Shared VPC arrangement may require network-user or service-agent permissions in the host project. Terraform must accept an approved existing network rather than assume it can create a new one there.

## Design

- Create a reusable Terraform networking module that either creates a dedicated VPC or consumes an explicitly supplied approved VPC network.
- Reserve a global internal range and create Private Services Access peering for `servicenetworking.googleapis.com`.
- Configure Cloud SQL PostgreSQL with `ipv4_enabled = false` and the selected VPC network. The instance receives only a private address.
- Create a regional Serverless VPC Access connector with a non-overlapping `/28` CIDR range in `us-central1`.
- Attach only the backend Cloud Run service to that connector with `PRIVATE_RANGES_ONLY` egress. The backend's Cloud SQL Python Connector is explicitly configured for `PRIVATE` IP; this corrects the former implicit `PUBLIC` connector path.
- Enable the Compute Engine, Service Networking, and Serverless VPC Access APIs. Retain existing Cloud SQL client and Secret Manager IAM bindings.
- Expose non-sensitive outputs needed to validate the connection and document manual host-project permissions where a Shared VPC is selected.

## Trade-offs

- A Serverless VPC Access connector has ongoing cost and throughput/scale limits, but is supported by established Cloud Run Terraform fields and avoids requiring a newer provider for Direct VPC egress.
- A dedicated VPC is self-contained for a time-boxed trial, while an existing Shared VPC can meet organisational networking requirements but needs host-project coordination and preallocated non-overlapping ranges.
- `PRIVATE_RANGES_ONLY` routes database traffic privately without forcing all Internet-bound backend traffic through a NAT gateway. This is the smallest change compatible with the Cloud SQL Python Connector path.